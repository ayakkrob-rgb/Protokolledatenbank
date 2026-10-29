import logging

import stripe
from django.contrib import messages
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from accounts.decorators import verified_required
from core.models import SiteSettings
from protocols.models import Exam

from . import services, stripe_gateway
from .models import Purchase

logger = logging.getLogger(__name__)


def _own_purchase(request, pk):
    purchase = get_object_or_404(Purchase.objects.select_related("exam"), pk=pk)
    if purchase.user_id != request.user.id and not request.user.is_staff:
        raise Http404
    return purchase


@verified_required
def order(request, slug):
    """Bestellübersicht: zeigt die Auswahl, Preis und Zustimmung – und startet die Zahlung."""
    exam = get_object_or_404(Exam, slug=slug, is_active=True)
    site = SiteSettings.get()
    ids = request.POST.getlist("examiners") if request.method == "POST" else request.GET.getlist("pruefer")
    try:
        examiners = services.validate_selection(request.user, exam, ids, site)
    except services.PurchaseError as exc:
        messages.error(request, str(exc))
        return redirect(exam.get_absolute_url())

    package = services.package_with_free_slots(request.user, exam, site)
    slots = services.free_slots(package, site) if package else 0
    can_add = package is not None and len(examiners) <= slots
    errors = []

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add" and can_add:
            services.add_examiners_to_package(package, examiners, site, actor=request.user)
            messages.success(request, f"{len(examiners)} Prüfer wurden kostenlos zu deinem Paket {package.number} hinzugefügt.")
            return redirect(exam.get_absolute_url())
        if action == "buy":
            if not request.POST.get("consent"):
                errors.append("Bitte bestätige die Hinweise zum Widerrufsrecht.")
            if not request.POST.get("terms"):
                errors.append("Bitte akzeptiere die Nutzungsbedingungen.")
            if not errors:
                for old in Purchase.objects.filter(user=request.user, exam=exam, status=Purchase.STATUS_PENDING):
                    services.cancel_purchase(old, actor=request.user, reason="durch neue Bestellung ersetzt")
                purchase = services.create_purchase(request.user, exam, examiners, site)
                try:
                    return redirect(services.start_checkout(request, purchase, site))
                except services.PurchaseError as exc:
                    messages.error(request, str(exc))
                    return redirect("core:dashboard")

    return render(
        request,
        "payments/order.html",
        {
            "exam": exam,
            "examiners": examiners,
            "price_cents": exam.price_cents(site),
            "refund_cents": exam.refund_cents(site),
            "max_examiners": exam.max_examiners(site),
            "remaining_slots": exam.max_examiners(site) - len(examiners),
            "package": package,
            "free_slots": slots,
            "can_add": can_add,
            "errors": errors,
        },
    )


@verified_required
def simulate(request, pk):
    """Simulierte Bezahlseite – ersetzt Stripe, solange der Simulationsmodus aktiv ist."""
    purchase = _own_purchase(request, pk)
    if purchase.provider != Purchase.PROVIDER_SIMULATION or not SiteSettings.get().is_simulation:
        raise Http404
    if purchase.status == Purchase.STATUS_PAID:
        return redirect("payments:success", pk=purchase.pk)
    if request.method == "POST":
        if request.POST.get("action") == "pay":
            services.mark_paid(purchase, actor=request.user, note="simulierte Zahlung")
            return redirect("payments:success", pk=purchase.pk)
        services.cancel_purchase(purchase, actor=request.user, reason="Simulation abgebrochen")
        messages.info(request, "Die Zahlung wurde abgebrochen. Es wurde nichts berechnet.")
        return redirect(purchase.exam.get_absolute_url())
    return render(
        request,
        "payments/simulate.html",
        {"purchase": purchase, "examiners": purchase.examiners.all()},
    )


@verified_required
def stripe_return(request):
    """Rücksprung von Stripe nach erfolgreicher Zahlung."""
    session_id = request.GET.get("session_id", "")
    if not session_id.startswith("cs_"):
        messages.error(request, "Ungültige Rückmeldung von Stripe.")
        return redirect("core:dashboard")
    try:
        session = stripe_gateway.retrieve_checkout_session(session_id)
    except (stripe.StripeError, stripe_gateway.StripeNotConfigured):
        logger.exception("Checkout-Session %s konnte nicht abgerufen werden", session_id)
        messages.warning(
            request,
            "Wir konnten deine Zahlung gerade nicht bestätigen. Sie wird automatisch verbucht, sobald Stripe sie meldet.",
        )
        return redirect("core:dashboard")
    purchase = services.sync_checkout_session(session, source="Rückleitung")
    if purchase is None or (purchase.user_id != request.user.id and not request.user.is_staff):
        raise Http404
    return redirect("payments:success", pk=purchase.pk)


@verified_required
def success(request, pk):
    purchase = _own_purchase(request, pk)
    return render(request, "payments/success.html", {"purchase": purchase, "examiners": purchase.examiners.all()})


@verified_required
def cancel(request, pk):
    """Rücksprung, wenn die Zahlung bei Stripe abgebrochen wurde."""
    purchase = _own_purchase(request, pk)
    if purchase.status == Purchase.STATUS_PENDING:
        messages.info(
            request,
            "Die Zahlung wurde nicht abgeschlossen. Du kannst sie jederzeit unter „Mein Bereich“ fortsetzen.",
        )
    return redirect(purchase.exam.get_absolute_url())


@verified_required
@require_POST
def resume(request, pk):
    purchase = _own_purchase(request, pk)
    if purchase.status not in (Purchase.STATUS_PENDING, Purchase.STATUS_CANCELLED):
        return redirect("core:dashboard")
    site = SiteSettings.get()
    if purchase.provider == Purchase.PROVIDER_SIMULATION and not site.is_simulation:
        messages.error(request, "Dieses Test-Paket kann nicht mehr bezahlt werden. Bitte wähle die Prüfer neu aus.")
        return redirect(purchase.exam.get_absolute_url())
    if purchase.status == Purchase.STATUS_CANCELLED:
        Purchase.objects.filter(pk=purchase.pk).update(status=Purchase.STATUS_PENDING)
    try:
        return redirect(services.start_checkout(request, purchase, site))
    except services.PurchaseError as exc:
        messages.error(request, str(exc))
        return redirect("core:dashboard")


@verified_required
@require_POST
def discard(request, pk):
    purchase = _own_purchase(request, pk)
    if services.cancel_purchase(purchase, actor=request.user, reason="vom Nutzer verworfen"):
        messages.info(request, "Die offene Bestellung wurde verworfen.")
    return redirect("core:dashboard")


@verified_required
def extend(request, pk):
    """Weitere Prüfer kostenlos zu einem bestehenden Paket hinzufügen (bis zur Höchstzahl)."""
    purchase = _own_purchase(request, pk)
    site = SiteSettings.get()
    slots = services.free_slots(purchase, site)
    if not purchase.is_active or slots == 0:
        messages.info(request, "Zu diesem Paket können keine weiteren Prüfer hinzugefügt werden.")
        return redirect("core:dashboard")
    from protocols.access import unlocked_examiner_ids

    unlocked = unlocked_examiner_ids(request.user)
    candidates = [
        e for e in services.examiners_for_catalog(purchase.exam) if e.pk not in unlocked and e.published_count > 0
    ]
    if request.method == "POST":
        ids = request.POST.getlist("examiners")
        try:
            examiners = services.validate_selection(request.user, purchase.exam, ids, site)
            services.add_examiners_to_package(purchase, examiners, site, actor=request.user)
        except services.PurchaseError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Die Prüfer wurden zu deinem Paket hinzugefügt.")
            return redirect("core:dashboard")
    return render(
        request,
        "payments/extend.html",
        {"purchase": purchase, "candidates": candidates, "free_slots": slots},
    )


@csrf_exempt
@require_POST
def stripe_webhook(request):
    try:
        event = stripe_gateway.parse_webhook(request.body, request.META.get("HTTP_STRIPE_SIGNATURE"))
    except stripe_gateway.StripeNotConfigured:
        logger.warning("Stripe-Webhook empfangen, aber kein Signaturgeheimnis hinterlegt.")
        return HttpResponse("Webhook-Geheimnis fehlt", status=400)
    except (stripe.SignatureVerificationError, ValueError):
        return HttpResponse("Ungültige Signatur", status=400)
    result = services.handle_stripe_event(event)
    return JsonResponse({"received": True, "result": result})
