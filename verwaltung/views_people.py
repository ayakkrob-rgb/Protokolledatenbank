"""Verwaltung: Nutzer und Zahlungen (Pakete)."""
import csv

from django.contrib import messages
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import staff_required
from accounts.models import User
from accounts.services import anonymize_user, send_password_reset_email, send_verification_email
from core.audit import audit
from core.models import SiteSettings
from core.utils import format_eur, to_cents
from payments import services as payment_services
from payments.models import Purchase
from protocols.models import Exam, Protocol

from .forms import GrantPackageForm, PurchaseEditForm, UserAdminForm, UserCreateForm
from .helpers import int_or_none, paginate

# --- Nutzer ----------------------------------------------------------------------------------


@staff_required
def user_list(request):
    qs = User.objects.annotate(
        package_count=Count("purchases", filter=Q(purchases__status=Purchase.STATUS_PAID), distinct=True),
        upload_count=Count("uploaded_protocols", distinct=True),
    ).order_by("-date_joined")
    q = request.GET.get("q", "").strip()
    state = request.GET.get("status", "")
    if q:
        qs = qs.filter(Q(email__icontains=q) | Q(name__icontains=q))
    if state == "unbestaetigt":
        qs = qs.filter(email_verified=False, is_active=True)
    elif state == "admins":
        qs = qs.filter(is_staff=True)
    elif state == "gesperrt":
        qs = qs.filter(is_active=False)
    elif state == "kaeufer":
        qs = qs.filter(package_count__gt=0)
    return render(request, "verwaltung/user_list.html", {"page": paginate(request, qs, 50), "q": q, "state": state})


@staff_required
def user_create(request):
    form = UserCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = User.objects.create_user(
            email=form.cleaned_data["email"],
            password=None,
            name=form.cleaned_data["name"],
            is_staff=form.cleaned_data["is_staff"],
            email_verified=True,
        )
        send_password_reset_email(user, request)
        audit("nutzer.angelegt", f"Konto {user.email} angelegt{' (Admin)' if user.is_staff else ''}", actor=request.user)
        messages.success(request, f"Konto angelegt. {user.email} hat eine E-Mail zum Setzen des Passworts erhalten.")
        return redirect("verwaltung:user_detail", pk=user.pk)
    return render(request, "verwaltung/user_create.html", {"form": form})


@staff_required
def user_detail(request, pk):
    user = get_object_or_404(User, pk=pk)
    form = UserAdminForm(instance=user)
    grant_form = GrantPackageForm(initial={"amount": 0})
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "save":
            form = UserAdminForm(request.POST, instance=user)
            if form.is_valid():
                if user == request.user and (not form.cleaned_data["is_staff"] or not form.cleaned_data["is_active"]):
                    messages.error(request, "Du kannst dir nicht selbst die Admin-Rechte entziehen oder dich sperren.")
                else:
                    form.save()
                    audit("nutzer.gespeichert", f"Konto {user.email} bearbeitet ({', '.join(form.changed_data)})", actor=request.user)
                    messages.success(request, "Gespeichert.")
                    return redirect("verwaltung:user_detail", pk=user.pk)
        elif action == "grant":
            grant_form = GrantPackageForm(request.POST)
            if grant_form.is_valid():
                purchase = payment_services.grant_package(
                    user,
                    grant_form.cleaned_data["exam"],
                    list(grant_form.cleaned_data["examiners"]),
                    to_cents(grant_form.cleaned_data["amount"]),
                    actor=request.user,
                    note=grant_form.cleaned_data["note"],
                )
                messages.success(request, f"Paket {purchase.number} freigeschaltet.")
                return redirect("verwaltung:user_detail", pk=user.pk)
        elif action == "verify":
            user.mark_verified()
            audit("nutzer.bestaetigt", f"E-Mail von {user.email} manuell bestätigt", actor=request.user)
            messages.success(request, "E-Mail-Adresse als bestätigt markiert.")
            return redirect("verwaltung:user_detail", pk=user.pk)
        elif action == "resend":
            send_verification_email(user, request)
            messages.success(request, "Bestätigungslink erneut gesendet.")
            return redirect("verwaltung:user_detail", pk=user.pk)
        elif action == "reset":
            send_password_reset_email(user, request)
            messages.success(request, "Link zum Zurücksetzen des Passworts gesendet.")
            return redirect("verwaltung:user_detail", pk=user.pk)
        elif action == "delete":
            if user == request.user:
                messages.error(request, "Du kannst dein eigenes Konto hier nicht löschen.")
            else:
                email = user.email
                anonymize_user(user)
                audit("nutzer.geloescht", f"Konto {email} gelöscht (anonymisiert)", actor=request.user)
                messages.success(request, f"Das Konto {email} wurde gelöscht. Käufe bleiben anonymisiert erhalten.")
                return redirect("verwaltung:users")
    purchases = user.purchases.select_related("exam").prefetch_related("examiners")
    uploads = user.uploaded_protocols.select_related("examiner__exam").order_by("-created_at")
    return render(
        request,
        "verwaltung/user_detail.html",
        {"account": user, "form": form, "grant_form": grant_form, "purchases": purchases, "uploads": uploads},
    )


# --- Zahlungen / Pakete ----------------------------------------------------------------------


def _filtered_purchases(request):
    qs = Purchase.objects.select_related("exam", "user").prefetch_related("examiners")
    q = request.GET.get("q", "").strip()
    filters = {
        "status": request.GET.get("status", ""),
        "erstattung": request.GET.get("erstattung", ""),
        "zahlungsart": request.GET.get("zahlungsart", ""),
        "pruefung": int_or_none(request.GET.get("pruefung")),
    }
    if q:
        number = q.upper().removeprefix("P-").lstrip("0")
        cond = Q(email__icontains=q) | Q(stripe_payment_intent__icontains=q) | Q(stripe_session_id__icontains=q)
        if number.isdigit():
            cond |= Q(pk=int(number))
        qs = qs.filter(cond)
    if filters["status"]:
        qs = qs.filter(status=filters["status"])
    if filters["erstattung"] == "offen":
        qs = qs.filter(refund_status__in=[Purchase.REFUND_FAILED, Purchase.REFUND_MANUAL_PENDING])
    elif filters["erstattung"]:
        qs = qs.filter(refund_status=filters["erstattung"])
    if filters["zahlungsart"]:
        qs = qs.filter(provider=filters["zahlungsart"])
    if filters["pruefung"]:
        qs = qs.filter(exam_id=filters["pruefung"])
    return qs, q, filters


@staff_required
def purchase_list(request):
    qs, q, filters = _filtered_purchases(request)
    paid = qs.filter(status__in=[Purchase.STATUS_PAID, Purchase.STATUS_REVOKED])
    totals = paid.aggregate(revenue=Sum("amount_cents"), refunded=Sum("refunded_cents"))
    totals = {k: v or 0 for k, v in totals.items()}
    totals["net"] = totals["revenue"] - totals["refunded"]
    totals["count"] = paid.count()
    return render(
        request,
        "verwaltung/purchase_list.html",
        {
            "simulated_active": Purchase.objects.filter(
                provider=Purchase.PROVIDER_SIMULATION, status=Purchase.STATUS_PAID
            ).count(),
            "page": paginate(request, qs, 50),
            "q": q,
            "filters": filters,
            "totals": totals,
            "exams": Exam.objects.all(),
            "statuses": Purchase.STATUS_CHOICES,
            "refund_statuses": Purchase.REFUND_CHOICES,
            "providers": Purchase.PROVIDER_CHOICES,
            "querystring": request.GET.urlencode(),
        },
    )


@staff_required
@require_POST
def revoke_simulated(request):
    """Sperrt alle (noch freigeschalteten) Pakete aus dem Simulationsbetrieb – z. B. nach dem Livegang."""
    count = Purchase.objects.filter(provider=Purchase.PROVIDER_SIMULATION, status=Purchase.STATUS_PAID).update(
        status=Purchase.STATUS_REVOKED
    )
    audit("paket.simulierte_gesperrt", f"{count} simulierte Pakete gesperrt", actor=request.user)
    messages.success(request, f"{count} Test-Pakete wurden gesperrt.")
    return redirect("verwaltung:purchases")


@staff_required
def purchase_export(request):
    qs, _, _ = _filtered_purchases(request)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="zahlungen-{timezone.localdate():%Y-%m-%d}.csv"'
    response.write("﻿")
    writer = csv.writer(response, delimiter=";")
    writer.writerow(
        ["Nummer", "Erstellt", "Bezahlt", "E-Mail", "Prüfung", "Prüfer", "Zahlungsart", "Status", "Betrag",
         "Erstattet", "Netto", "Erstattungsstatus", "Erstattet am", "Stripe PaymentIntent", "Stripe Refund", "Notiz"]
    )

    def money(cents):
        return f"{cents / 100:.2f}".replace(".", ",")

    def dt(value):
        return timezone.localtime(value).strftime("%d.%m.%Y %H:%M") if value else ""

    for p in qs.order_by("created_at"):
        writer.writerow(
            [p.number, dt(p.created_at), dt(p.paid_at), p.email, p.exam.code,
             ", ".join(e.name for e in p.examiners.all()), p.get_provider_display(), p.get_status_display(),
             money(p.amount_cents), money(p.refunded_cents), money(p.net_cents), p.get_refund_status_display(),
             dt(p.refunded_at), p.stripe_payment_intent, p.stripe_refund_id, p.admin_note]
        )
    return response


@staff_required
def purchase_detail(request, pk):
    purchase = get_object_or_404(Purchase.objects.select_related("exam", "user", "refund_protocol__examiner"), pk=pk)
    site = SiteSettings.get()
    form = PurchaseEditForm(instance=purchase)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "save":
            form = PurchaseEditForm(request.POST, instance=purchase)
            if form.is_valid():
                form.save()
                audit("paket.bearbeitet", f"{purchase.number} bearbeitet ({', '.join(form.changed_data)})", actor=request.user)
                messages.success(request, "Gespeichert.")
                return redirect("verwaltung:purchase_detail", pk=purchase.pk)
        else:
            _purchase_action(request, purchase, action, site)
            return redirect("verwaltung:purchase_detail", pk=purchase.pk)
    return render(
        request,
        "verwaltung/purchase_detail.html",
        {
            "purchase": purchase,
            "form": form,
            "examiners": purchase.examiners.all(),
            "standard_refund": purchase.exam.refund_cents(site),
            "remaining": purchase.amount_cents - purchase.refunded_cents,
            "uploads": Protocol.objects.filter(uploaded_by=purchase.user, examiner__exam=purchase.exam)
            if purchase.user else [],
        },
    )


def _purchase_action(request, purchase, action, site):
    actor = request.user
    if action == "mark_paid" and purchase.status in (Purchase.STATUS_PENDING, Purchase.STATUS_CANCELLED):
        payment_services.mark_paid(purchase, actor=actor, note=f"manuell als bezahlt markiert von {actor.email}")
        messages.success(request, "Als bezahlt markiert – der Zugriff ist freigeschaltet.")
    elif action == "cancel" and purchase.status == Purchase.STATUS_PENDING:
        payment_services.cancel_purchase(purchase, actor=actor, reason="durch Admin")
        messages.success(request, "Bestellung abgebrochen.")
    elif action == "refund" and purchase.can_be_refunded:
        amount = min(purchase.exam.refund_cents(site), purchase.amount_cents - purchase.refunded_cents)
        result = payment_services.refund_purchase(purchase, amount, actor=actor, reason="durch Admin")
        _refund_message(request, result)
    elif action == "refund_full" and purchase.status in (Purchase.STATUS_PAID, Purchase.STATUS_REVOKED):
        amount = purchase.amount_cents - purchase.refunded_cents
        if amount <= 0:
            messages.info(request, "Es ist nichts mehr zu erstatten.")
        else:
            result = payment_services.refund_purchase(
                purchase, amount, actor=actor, reason="vollständige Erstattung durch Admin", revoke=True,
                allow_after_refund=True,
            )
            _refund_message(request, result)
    elif action == "manual_done" and purchase.refund_status in (Purchase.REFUND_MANUAL_PENDING, Purchase.REFUND_FAILED):
        payment_services.mark_manual_refund_done(purchase, actor)
        messages.success(request, "Erstattung als ausgezahlt markiert.")
    elif action == "revoke" and purchase.status == Purchase.STATUS_PAID:
        Purchase.objects.filter(pk=purchase.pk).update(status=Purchase.STATUS_REVOKED)
        audit("paket.gesperrt", f"Zugriff für {purchase.number} entzogen", actor=actor)
        messages.success(request, "Der Zugriff wurde entzogen.")
    elif action == "restore" and purchase.status == Purchase.STATUS_REVOKED:
        Purchase.objects.filter(pk=purchase.pk).update(status=Purchase.STATUS_PAID)
        audit("paket.entsperrt", f"Zugriff für {purchase.number} wiederhergestellt", actor=actor)
        messages.success(request, "Der Zugriff wurde wiederhergestellt.")
    else:
        messages.error(request, "Diese Aktion ist im aktuellen Zustand nicht möglich.")


def _refund_message(request, result):
    if result.status == "refunded":
        messages.success(request, f"{format_eur(result.amount_cents)} wurden erstattet.")
    elif result.status == "manual":
        messages.warning(request, f"Bitte {format_eur(result.amount_cents)} manuell auszahlen und danach als erledigt markieren.")
    elif result.status == "failed":
        messages.error(request, f"Erstattung fehlgeschlagen: {result.message}")
    else:
        messages.info(request, result.message or "Keine Erstattung durchgeführt.")
