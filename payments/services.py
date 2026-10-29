"""Geschäftslogik rund um Pakete, Zahlungen und Erstattungen."""
import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta

import stripe
from django.db import transaction
from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

from core.audit import audit
from core.mail import notify_admins, send_template_email
from core.models import AuditLog, SiteSettings
from core.utils import absolute_url, format_eur
from protocols.access import unlocked_examiner_ids
from protocols.models import Examiner, Protocol

from . import stripe_gateway
from .models import Purchase, StripeEvent

logger = logging.getLogger(__name__)


class PurchaseError(Exception):
    pass


# --- Auswahl & Pakete ------------------------------------------------------------


def examiners_for_catalog(exam, include_inactive=False):
    qs = exam.examiners.select_related("subject").annotate(
        published_count=Count("protocols", filter=Q(protocols__status=Protocol.STATUS_PUBLISHED))
    )
    if not include_inactive:
        qs = qs.filter(is_active=True)
    return qs.order_by("subject__sort_order", "subject__name", "name")


def package_with_free_slots(user, exam, site):
    """Aktives Paket dieser Prüfung, dem noch Prüfer hinzugefügt werden können."""
    limit = exam.max_examiners(site)
    return (
        Purchase.objects.active()
        .filter(user=user, exam=exam)
        .annotate(n=Count("examiners"))
        .filter(n__lt=limit)
        .order_by("-paid_at")
        .first()
    )


def validate_selection(user, exam, examiner_ids, site):
    try:
        ids = {int(i) for i in examiner_ids}
    except (TypeError, ValueError):
        raise PurchaseError("Ungültige Auswahl.")
    if not ids:
        raise PurchaseError("Bitte wähle mindestens einen Prüfer aus.")
    limit = exam.max_examiners(site)
    if len(ids) > limit:
        raise PurchaseError(f"Du kannst höchstens {limit} Prüfer pro Paket auswählen.")
    examiners = list(examiners_for_catalog(exam).filter(pk__in=ids, published_count__gt=0))
    if len(examiners) != len(ids):
        raise PurchaseError("Mindestens ein ausgewählter Prüfer ist nicht (mehr) verfügbar.")
    already = unlocked_examiner_ids(user)
    duplicates = [e.name for e in examiners if e.pk in already]
    if duplicates:
        raise PurchaseError(f"Bereits freigeschaltet: {', '.join(duplicates)}.")
    return examiners


def free_slots(purchase, site):
    return max(0, purchase.exam.max_examiners(site) - purchase.examiners.count())


def add_examiners_to_package(purchase, examiners, site, actor=None):
    if not purchase.is_active:
        raise PurchaseError("Dieses Paket ist nicht aktiv.")
    if len(examiners) > free_slots(purchase, site):
        raise PurchaseError("In diesem Paket ist nicht genug Platz für so viele Prüfer.")
    purchase.examiners.add(*examiners)
    audit(
        "paket.erweitert",
        f"{purchase.number}: Prüfer hinzugefügt ({', '.join(e.name for e in examiners)})",
        actor=actor,
    )


def create_purchase(user, exam, examiners, site):
    provider = Purchase.PROVIDER_SIMULATION if site.is_simulation else Purchase.PROVIDER_STRIPE
    purchase = Purchase.objects.create(
        user=user,
        email=user.email,
        exam=exam,
        amount_cents=exam.price_cents(site),
        provider=provider,
    )
    purchase.examiners.set(examiners)
    audit(
        "paket.angelegt",
        f"{purchase.number} für {user.email}: {exam.code}, {len(examiners)} Prüfer, {format_eur(purchase.amount_cents)} ({purchase.get_provider_display()})",
        actor=user,
    )
    if purchase.amount_cents == 0:
        mark_paid(purchase, actor=user)
    return purchase


def start_checkout(request, purchase, site):
    """Gibt die URL zurück, zu der für die Zahlung weitergeleitet wird."""
    if purchase.status == Purchase.STATUS_PAID:
        return reverse("payments:success", args=[purchase.pk])
    if purchase.provider == Purchase.PROVIDER_SIMULATION:
        return reverse("payments:simulate", args=[purchase.pk])
    if purchase.provider != Purchase.PROVIDER_STRIPE:
        raise PurchaseError("Für dieses Paket ist keine Online-Zahlung möglich.")
    success_url = absolute_url(reverse("payments:stripe_return"), request) + "?session_id={CHECKOUT_SESSION_ID}"
    cancel_url = absolute_url(reverse("payments:cancel", args=[purchase.pk]), request)
    try:
        session = stripe_gateway.create_checkout_session(purchase, success_url, cancel_url, site=site)
    except stripe_gateway.StripeNotConfigured as exc:
        audit("stripe.nicht_konfiguriert", str(exc), level=AuditLog.LEVEL_ERROR)
        raise PurchaseError("Die Online-Zahlung ist gerade nicht verfügbar. Bitte informiere die Fachschaft.")
    except stripe.StripeError as exc:
        logger.exception("Stripe Checkout konnte nicht erstellt werden")
        audit("stripe.fehler", f"Checkout für {purchase.number}: {exc}", level=AuditLog.LEVEL_ERROR)
        raise PurchaseError("Die Zahlung konnte nicht gestartet werden. Bitte versuche es in einigen Minuten erneut.")
    purchase.stripe_session_id = session.id
    purchase.save(update_fields=["stripe_session_id"])
    return session.url


def _expiry(site, start):
    if site.access_duration_days:
        return start + timedelta(days=site.access_duration_days)
    return None


def mark_paid(purchase, *, payment_intent="", actor=None, note=""):
    """Bucht ein Paket als bezahlt. Mehrfachaufrufe sind unschädlich."""
    site = SiteSettings.get()
    now = timezone.now()
    with transaction.atomic():
        updated = Purchase.objects.filter(
            pk=purchase.pk, status__in=[Purchase.STATUS_PENDING, Purchase.STATUS_CANCELLED]
        ).update(status=Purchase.STATUS_PAID, paid_at=now, expires_at=_expiry(site, now))
        if payment_intent:
            Purchase.objects.filter(pk=purchase.pk, stripe_payment_intent="").update(stripe_payment_intent=payment_intent)
    purchase.refresh_from_db()
    if not updated:
        if payment_intent and purchase.stripe_payment_intent and purchase.stripe_payment_intent != payment_intent:
            audit(
                "zahlung.doppelt",
                f"{purchase.number}: weitere Zahlung {payment_intent} eingegangen, obwohl bereits bezahlt "
                f"({purchase.stripe_payment_intent}). Bitte im Stripe-Dashboard prüfen und ggf. erstatten.",
                level=AuditLog.LEVEL_WARNING,
            )
        return False
    audit(
        "zahlung.eingegangen",
        f"{purchase.number} bezahlt: {format_eur(purchase.amount_cents)} ({purchase.get_provider_display()})"
        + (f" – {note}" if note else ""),
        actor=actor,
    )
    if purchase.user and purchase.amount_cents > 0:
        send_template_email(
            purchase.email,
            f"Deine Protokolle für {purchase.exam.code} sind freigeschaltet",
            "emails/purchase_confirmation.txt",
            {
                "purchase": purchase,
                "examiners": list(purchase.examiners.all()),
                "refund": format_eur(purchase.exam.refund_cents(site)),
                "dashboard_url": absolute_url("core:dashboard"),
                "upload_url": absolute_url("protocols:upload_start"),
            },
            kind="purchase",
        )
    return True


def cancel_purchase(purchase, actor=None, reason=""):
    updated = Purchase.objects.filter(pk=purchase.pk, status=Purchase.STATUS_PENDING).update(
        status=Purchase.STATUS_CANCELLED
    )
    if updated:
        audit("paket.abgebrochen", f"{purchase.number} abgebrochen{': ' + reason if reason else ''}", actor=actor)
    return bool(updated)


def grant_package(user, exam, examiners, amount_cents, actor, note=""):
    """Admin schaltet ein Paket manuell frei (z. B. Barzahlung oder Freiexemplar)."""
    purchase = Purchase.objects.create(
        user=user,
        email=user.email,
        exam=exam,
        amount_cents=amount_cents,
        provider=Purchase.PROVIDER_MANUAL,
        admin_note=note,
    )
    purchase.examiners.set(examiners)
    mark_paid(purchase, actor=actor, note=f"manuell freigeschaltet von {actor.email}")
    return purchase


# --- Stripe-Rückmeldungen ----------------------------------------------------------


def _get(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _purchase_for_session(session):
    ref = _get(session, "client_reference_id") or (_get(session, "metadata") or {}).get("purchase_id")
    purchase = None
    if ref and str(ref).isdigit():
        purchase = Purchase.objects.filter(pk=int(ref)).first()
    if purchase is None and _get(session, "id"):
        purchase = Purchase.objects.filter(stripe_session_id=_get(session, "id")).first()
    return purchase


def sync_checkout_session(session, source="redirect"):
    """Gleicht eine Stripe-Checkout-Session mit dem Paket ab. Gibt das Paket zurück."""
    purchase = _purchase_for_session(session)
    if purchase is None:
        audit("stripe.unbekannt", f"Checkout-Session {_get(session, 'id')} gehört zu keinem Paket.", level=AuditLog.LEVEL_WARNING)
        return None
    payment_status = _get(session, "payment_status")
    if payment_status in ("paid", "no_payment_required"):
        amount_total = _get(session, "amount_total")
        if amount_total is not None and int(amount_total) != purchase.amount_cents:
            audit(
                "zahlung.betrag_abweichend",
                f"{purchase.number}: Stripe meldet {format_eur(amount_total)}, erwartet {format_eur(purchase.amount_cents)}.",
                level=AuditLog.LEVEL_WARNING,
            )
        mark_paid(
            purchase,
            payment_intent=stripe_gateway.object_id(_get(session, "payment_intent")),
            note=f"Stripe ({source})",
        )
        purchase.refresh_from_db()
    return purchase


def handle_stripe_event(event):
    """Verarbeitet ein (bereits signaturgeprüftes) Webhook-Ereignis."""
    event_id = event.get("id", "")
    event_type = event.get("type", "")
    if StripeEvent.objects.filter(event_id=event_id).exists():
        return "duplicate"
    obj = (event.get("data") or {}).get("object") or {}
    result = "ignored"
    if event_type in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        sync_checkout_session(obj, source="Webhook")
        result = "processed"
    elif event_type in ("checkout.session.expired", "checkout.session.async_payment_failed"):
        purchase = _purchase_for_session(obj)
        if purchase:
            reason = "Zahlung fehlgeschlagen" if event_type.endswith("failed") else "Checkout abgelaufen"
            cancel_purchase(purchase, reason=reason)
        result = "processed"
    elif event_type == "charge.refunded":
        pi = stripe_gateway.object_id(obj.get("payment_intent"))
        purchase = Purchase.objects.filter(stripe_payment_intent=pi).first() if pi else None
        if purchase:
            audit("stripe.erstattung_gemeldet", f"Stripe meldet Erstattung für {purchase.number} (insgesamt {format_eur(obj.get('amount_refunded', 0))}).")
        result = "processed"
    StripeEvent.objects.get_or_create(event_id=event_id, defaults={"event_type": event_type})
    return result


# --- Erstattungen ---------------------------------------------------------------------


@dataclass
class RefundResult:
    purchase: Purchase | None
    status: str  # refunded | manual | failed | none | already
    amount_cents: int = 0
    message: str = ""

    @property
    def ok(self):
        return self.status in {"refunded", "manual"}


def eligible_purchase(user, exam):
    return (
        Purchase.objects.filter(
            user=user, exam=exam, status=Purchase.STATUS_PAID, refund_status=Purchase.REFUND_NONE, amount_cents__gt=0
        )
        .order_by("paid_at", "pk")
        .first()
    )


def reward_uploads(protocols, actor=None):
    """Erstattet für jede Einsendung (Upload-Vorgang) höchstens ein Paket der passenden Prüfung."""
    site = SiteSettings.get()
    results = []
    groups = {}
    for protocol in protocols:
        if protocol.source != Protocol.SOURCE_UPLOAD or protocol.uploaded_by_id is None:
            continue
        groups.setdefault(protocol.submission_key or f"single-{protocol.pk}", []).append(protocol)
    for key, group in groups.items():
        first = group[0]
        already = Purchase.objects.filter(refund_protocol__in=[p.pk for p in group])
        if first.submission_key:
            already = Purchase.objects.filter(refund_protocol__submission_key=first.submission_key)
        if already.exists():
            results.append(RefundResult(already.first(), "already"))
            continue
        exam = first.examiner.exam
        purchase = eligible_purchase(first.uploaded_by, exam)
        if purchase is None:
            results.append(RefundResult(None, "none", message=f"Kein erstattungsfähiges Paket für {exam.code}."))
            continue
        amount = min(exam.refund_cents(site), purchase.amount_cents - purchase.refunded_cents)
        if amount <= 0:
            results.append(RefundResult(purchase, "none"))
            continue
        results.append(refund_purchase(purchase, amount, protocol=first, actor=actor, reason="Upload"))
    return results


def _stripe_refunded_total(payment_intent, site):
    client = stripe_gateway._client(site)
    refunds = client.v1.refunds.list(params={"payment_intent": payment_intent, "limit": 100})
    return sum(r.amount for r in refunds.data if r.status in ("succeeded", "pending", "requires_action"))


def refund_purchase(purchase, amount_cents, *, protocol=None, actor=None, reason="", revoke=False, allow_after_refund=False):
    """Erstattet ``amount_cents`` eines Pakets – je nach Zahlungsart über Stripe, simuliert oder manuell."""
    site = SiteSettings.get()
    allowed_from = [Purchase.REFUND_NONE, Purchase.REFUND_FAILED]
    if allow_after_refund:
        allowed_from.append(Purchase.REFUND_DONE)
    claim = {"refund_status": Purchase.REFUND_PROCESSING, "refund_requested_cents": amount_cents, "refund_error": ""}
    if protocol is not None:
        claim["refund_protocol"] = protocol
    claimed = Purchase.objects.filter(pk=purchase.pk, refund_status__in=allowed_from).update(**claim)
    purchase.refresh_from_db()
    if not claimed:
        return RefundResult(purchase, "already", message="Für dieses Paket läuft bereits eine Erstattung oder sie ist erledigt.")

    status, error, refund_id = "refunded", "", ""
    if purchase.provider == Purchase.PROVIDER_SIMULATION:
        refund_id = f"sim_re_{uuid.uuid4().hex[:16]}"
    elif purchase.provider == Purchase.PROVIDER_MANUAL:
        status = "manual"
    else:
        try:
            if not purchase.stripe_payment_intent:
                raise ValueError("Zu diesem Paket ist keine Stripe-Zahlung (PaymentIntent) gespeichert.")
            already = _stripe_refunded_total(purchase.stripe_payment_intent, site)
            if already >= purchase.refunded_cents + amount_cents:
                refund_id = "bereits-bei-stripe-erstattet"
            else:
                refund = stripe_gateway.create_refund(
                    purchase.stripe_payment_intent,
                    amount_cents,
                    idempotency_key=f"purchase-{purchase.pk}-refund-{purchase.refunded_cents}-{amount_cents}-{uuid.uuid4().hex[:8]}",
                    metadata={"purchase_id": str(purchase.pk), "reason": reason or "Erstattung"},
                    site=site,
                )
                refund_id = refund.id
                if refund.status in ("failed", "canceled"):
                    raise ValueError(f"Stripe meldet Status „{refund.status}“.")
        except (stripe.StripeError, stripe_gateway.StripeNotConfigured, ValueError) as exc:
            status = "failed"
            error = getattr(exc, "user_message", None) or str(exc)
            logger.warning("Erstattung für %s fehlgeschlagen: %s", purchase.number, error)

    now = timezone.now()
    if status == "refunded":
        purchase.refund_status = Purchase.REFUND_DONE
        purchase.refunded_cents += amount_cents
        purchase.refunded_at = now
        purchase.stripe_refund_id = refund_id
        purchase.refund_requested_cents = 0
    elif status == "manual":
        purchase.refund_status = Purchase.REFUND_MANUAL_PENDING
    else:
        purchase.refund_status = Purchase.REFUND_FAILED
        purchase.refund_error = error[:2000]
    if revoke and status != "failed":
        purchase.status = Purchase.STATUS_REVOKED
    purchase.save()

    label = f"{purchase.number}: {format_eur(amount_cents)}" + (f" ({reason})" if reason else "")
    if status == "refunded":
        audit("erstattung.erfolgreich", f"Erstattet {label} – {purchase.get_provider_display()}", actor=actor)
        if purchase.user:
            send_template_email(
                purchase.email,
                "Deine Erstattung ist unterwegs",
                "emails/refund_done.txt",
                {"purchase": purchase, "amount": format_eur(amount_cents), "simulated": purchase.provider == Purchase.PROVIDER_SIMULATION},
                kind="refund",
            )
    elif status == "manual":
        audit("erstattung.manuell", f"Manuell auszuzahlen: {label}", actor=actor, level=AuditLog.LEVEL_WARNING)
        notify_admins("Manuelle Erstattung offen", "emails/admin_refund_manual.txt", {"purchase": purchase, "amount": format_eur(amount_cents)})
    else:
        audit("erstattung.fehlgeschlagen", f"{label}: {error}", actor=actor, level=AuditLog.LEVEL_ERROR)
        notify_admins(
            "Erstattung fehlgeschlagen",
            "emails/admin_refund_failed.txt",
            {"purchase": purchase, "amount": format_eur(amount_cents), "error": error},
        )
    return RefundResult(purchase, status, amount_cents, error)


def mark_manual_refund_done(purchase, actor):
    amount = purchase.refund_requested_cents
    purchase.refund_status = Purchase.REFUND_DONE
    purchase.refunded_cents += amount
    purchase.refund_requested_cents = 0
    purchase.refunded_at = timezone.now()
    purchase.refund_error = ""
    purchase.save()
    audit("erstattung.manuell_erledigt", f"{purchase.number}: {format_eur(amount)} als ausgezahlt markiert", actor=actor)
    if purchase.user:
        send_template_email(
            purchase.email,
            "Deine Erstattung ist unterwegs",
            "emails/refund_done.txt",
            {"purchase": purchase, "amount": format_eur(amount), "simulated": False},
            kind="refund",
        )
