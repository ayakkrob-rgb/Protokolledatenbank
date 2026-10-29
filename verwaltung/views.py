"""Verwaltung: Übersicht, Einstellungen, Postausgang und Logbuch."""
from datetime import timedelta

import stripe
from django.conf import settings
from django.contrib import messages
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import staff_required
from accounts.models import User
from core.audit import audit
from core.mail import send_email
from core.models import AuditLog, EmailLog, SiteSettings
from core.utils import absolute_url
from payments import stripe_gateway
from payments.models import Purchase
from protocols.models import Exam, Examiner, Protocol

from .forms import SETTINGS_SECTIONS, SettingsForm
from .helpers import paginate


def _sum(qs, field):
    return qs.aggregate(total=Sum(field))["total"] or 0


def _alerts(site):
    alerts = []
    if site.is_simulation:
        alerts.append(("warning", "flask", "Zahlungen werden simuliert – es fließt kein echtes Geld.",
                       "Unter Einstellungen → Zahlungen auf „Stripe“ umstellen, sobald ihr live geht.", "zahlungen"))
    else:
        if not site.effective_stripe_webhook_secret:
            alerts.append(("warning", "alert", "Kein Stripe-Webhook eingerichtet.",
                           "Zahlungen werden dann nur verbucht, wenn Studierende nach dem Bezahlen auf die Seite zurückkehren.", "zahlungen"))
        if site.stripe_key_mode == "test":
            alerts.append(("info", "info", "Stripe läuft im Testmodus (sk_test_…).",
                           "Für echte Zahlungen den Live-Schlüssel (sk_live_…) eintragen.", "zahlungen"))
    if not site.is_simulation:
        simulated = Purchase.objects.filter(provider=Purchase.PROVIDER_SIMULATION, status=Purchase.STATUS_PAID).count()
        if simulated:
            alerts.append(("warning", "flask", f"{simulated} Test-Pakete aus dem Simulationsbetrieb sind noch freigeschaltet.",
                           "Wer im Testbetrieb „gekauft“ hat, hat noch Zugriff. Unter Zahlungen kannst du alle Test-Pakete mit einem Klick sperren.", ""))
    if site.email_mode != SiteSettings.EMAIL_SMTP:
        alerts.append(("info", "mail", "E-Mails werden nur simuliert.",
                       "Bestätigungslinks findest du im Postausgang. Für echten Versand SMTP einrichten.", "email"))
    if "uni-beispiel.de" in site.domain_list:
        alerts.append(("warning", "users", "Die erlaubte E-Mail-Domain ist noch der Platzhalter „uni-beispiel.de“.",
                       "Unter Einstellungen → Registrierung eure Uni-Domain eintragen.", "registrierung"))
    if "[Name der Fachschaft]" in site.imprint_text or "Muster" in site.privacy_text:
        alerts.append(("info", "book", "Impressum/Datenschutz enthalten noch Mustertexte.",
                       "Vor dem Livegang unter Einstellungen → Rechtliches anpassen.", "rechtliches"))
    if settings.DEBUG:
        alerts.append(("danger", "alert", "DEBUG ist eingeschaltet.", "Im Betrieb DEBUG=0 setzen.", ""))
    return alerts


@staff_required
def dashboard(request):
    site = SiteSettings.get()
    real = Purchase.objects.exclude(provider=Purchase.PROVIDER_SIMULATION)
    sold = real.filter(status__in=[Purchase.STATUS_PAID, Purchase.STATUS_REVOKED])
    simulated = Purchase.objects.filter(
        provider=Purchase.PROVIDER_SIMULATION, status__in=[Purchase.STATUS_PAID, Purchase.STATUS_REVOKED]
    )
    since = timezone.now() - timedelta(days=30)
    revenue = _sum(sold, "amount_cents")
    refunded = _sum(real, "refunded_cents")
    kpis = {
        "users": User.objects.filter(is_active=True).count(),
        "users_verified": User.objects.filter(is_active=True, email_verified=True).count(),
        "users_new": User.objects.filter(date_joined__gte=since).count(),
        "packages": sold.count(),
        "packages_new": sold.filter(paid_at__gte=since).count(),
        "revenue": revenue,
        "refunded": refunded,
        "net": revenue - refunded,
        "sim_packages": simulated.count(),
        "sim_net": _sum(simulated, "amount_cents") - _sum(simulated, "refunded_cents"),
        "protocols": Protocol.objects.published().count(),
        "protocols_new": Protocol.objects.published().filter(created_at__gte=since).count(),
        "pending": Protocol.objects.filter(status=Protocol.STATUS_PENDING).count(),
        "examiners": Examiner.objects.filter(is_active=True).count(),
        "examiners_new": Examiner.objects.filter(created_via_upload=True, created_at__gte=since).count(),
        "refund_issues": Purchase.objects.filter(
            refund_status__in=[Purchase.REFUND_FAILED, Purchase.REFUND_MANUAL_PENDING]
        ).count(),
    }
    exams = []
    for exam in Exam.objects.all():
        exams.append(
            {
                "exam": exam,
                "examiners": exam.examiners.filter(is_active=True).count(),
                "protocols": Protocol.objects.published().filter(examiner__exam=exam).count(),
                "packages": sold.filter(exam=exam).count(),
            }
        )
    return render(
        request,
        "verwaltung/dashboard.html",
        {
            "kpis": kpis,
            "alerts": _alerts(site),
            "exams": exams,
            "recent_purchases": Purchase.objects.select_related("exam").exclude(status=Purchase.STATUS_CANCELLED)[:8],
            "recent_uploads": Protocol.objects.filter(source=Protocol.SOURCE_UPLOAD)
            .select_related("examiner__exam", "uploaded_by")
            .order_by("-created_at")[:8],
            "recent_log": AuditLog.objects.select_related("actor")[:10],
        },
    )


@staff_required
def site_settings(request):
    site = SiteSettings.get()
    form = SettingsForm(request.POST or None, instance=site)
    if request.method == "POST":
        if form.is_valid():
            before_mode = site.payment_mode
            form.save()
            changed = ", ".join(form.changed_data) or "keine Änderungen"
            audit("einstellungen.gespeichert", f"Einstellungen geändert: {changed}", actor=request.user)
            if "payment_mode" in form.changed_data:
                audit(
                    "einstellungen.zahlungsmodus",
                    f"Zahlungsmodus von „{before_mode}“ auf „{form.instance.payment_mode}“ geändert",
                    actor=request.user,
                    level=AuditLog.LEVEL_WARNING,
                )
            messages.success(request, "Die Einstellungen wurden gespeichert.")
            return redirect(reverse("verwaltung:settings") + f"#{request.POST.get('active_tab', '')}")
        messages.error(request, "Bitte prüfe die markierten Felder.")
    sections = []
    for key, title, icon, names in SETTINGS_SECTIONS:
        fields = []
        for name in names:
            fields.append(form[name])
            if f"clear_{name}" in form.fields and getattr(site, name):
                fields.append(form[f"clear_{name}"])
        sections.append({"key": key, "title": title, "icon": icon, "fields": fields,
                         "has_errors": any(f.errors for f in fields)})
    return render(
        request,
        "verwaltung/settings.html",
        {
            "form": form,
            "sections": sections,
            "webhook_url": absolute_url("payments:stripe_webhook", request),
            "env_overrides": {
                "stripe_secret_key": bool(settings.STRIPE_SECRET_KEY),
                "stripe_webhook_secret": bool(settings.STRIPE_WEBHOOK_SECRET),
                "smtp_password": bool(settings.SMTP_PASSWORD),
            },
            "stripe_mode": site.stripe_key_mode,
        },
    )


@staff_required
@require_POST
def settings_test_email(request):
    to = request.POST.get("to") or request.user.email
    log = send_email(
        to,
        "Test-E-Mail",
        "Diese Test-E-Mail bestätigt, dass der E-Mail-Versand der Protokolldatenbank funktioniert.\n",
        kind="test",
    )
    if log.status == EmailLog.STATUS_SENT:
        messages.success(request, f"Test-E-Mail an {to} wurde versendet.")
    elif log.status == EmailLog.STATUS_SIMULATED:
        messages.info(request, "E-Mail-Modus ist „Simulation“: Die Test-E-Mail liegt im Postausgang.")
    else:
        messages.error(request, f"Versand fehlgeschlagen: {log.error}")
    return redirect(reverse("verwaltung:settings") + "#email")


@staff_required
@require_POST
def settings_test_stripe(request):
    try:
        info = stripe_gateway.test_connection()
    except stripe_gateway.StripeNotConfigured as exc:
        messages.error(request, str(exc))
    except stripe.AuthenticationError:
        messages.error(request, "Stripe lehnt den Schlüssel ab. Bitte den Secret Key prüfen.")
    except stripe.StripeError as exc:
        messages.error(request, f"Stripe-Fehler: {exc.user_message or exc}")
    else:
        mode = "LIVE (echte Zahlungen)" if info["livemode"] else "TEST"
        messages.success(request, f"Verbindung zu Stripe erfolgreich – Modus: {mode}.")
    return redirect(reverse("verwaltung:settings") + "#zahlungen")


@staff_required
def email_list(request):
    qs = EmailLog.objects.all()
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    if q:
        qs = qs.filter(Q(to__icontains=q) | Q(subject__icontains=q))
    if status:
        qs = qs.filter(status=status)
    return render(
        request,
        "verwaltung/email_list.html",
        {"page": paginate(request, qs), "q": q, "status": status, "statuses": EmailLog.STATUS_CHOICES},
    )


@staff_required
def email_detail(request, pk):
    return render(request, "verwaltung/email_detail.html", {"mail": get_object_or_404(EmailLog, pk=pk)})


@staff_required
def audit_list(request):
    qs = AuditLog.objects.select_related("actor")
    q = request.GET.get("q", "").strip()
    level = request.GET.get("level", "")
    if q:
        qs = qs.filter(Q(message__icontains=q) | Q(action__icontains=q) | Q(actor__email__icontains=q))
    if level:
        qs = qs.filter(level=level)
    return render(
        request,
        "verwaltung/audit_list.html",
        {"page": paginate(request, qs, 60), "q": q, "level": level, "levels": AuditLog.LEVEL_CHOICES},
    )
