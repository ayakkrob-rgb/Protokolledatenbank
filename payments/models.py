from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from protocols.models import Exam, Examiner, Protocol


class PurchaseQuerySet(models.QuerySet):
    def active(self):
        """Bezahlte Pakete, deren Zugriff (noch) gilt."""
        return self.filter(status=Purchase.STATUS_PAID).filter(
            Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
        )


class Purchase(models.Model):
    """Ein Paket: Zugriff auf die Protokolle von bis zu N Prüfern einer Prüfung."""

    STATUS_PENDING = "pending"
    STATUS_PAID = "paid"
    STATUS_CANCELLED = "cancelled"
    STATUS_REVOKED = "revoked"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Zahlung offen"),
        (STATUS_PAID, "Bezahlt"),
        (STATUS_CANCELLED, "Abgebrochen"),
        (STATUS_REVOKED, "Zugriff entzogen"),
    ]

    PROVIDER_SIMULATION = "simulation"
    PROVIDER_STRIPE = "stripe"
    PROVIDER_MANUAL = "manual"
    PROVIDER_CHOICES = [
        (PROVIDER_SIMULATION, "Simulation"),
        (PROVIDER_STRIPE, "Stripe"),
        (PROVIDER_MANUAL, "Manuell (Admin)"),
    ]

    REFUND_NONE = "none"
    REFUND_PROCESSING = "processing"
    REFUND_DONE = "refunded"
    REFUND_FAILED = "failed"
    REFUND_MANUAL_PENDING = "manual_pending"
    REFUND_CHOICES = [
        (REFUND_NONE, "Keine Erstattung"),
        (REFUND_PROCESSING, "Wird bearbeitet"),
        (REFUND_DONE, "Erstattet"),
        (REFUND_FAILED, "Fehlgeschlagen"),
        (REFUND_MANUAL_PENDING, "Manuell auszahlen"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Nutzer", null=True, on_delete=models.SET_NULL, related_name="purchases"
    )
    email = models.EmailField("E-Mail bei Kauf")
    exam = models.ForeignKey(Exam, verbose_name="Prüfung", on_delete=models.PROTECT, related_name="purchases")
    examiners = models.ManyToManyField(Examiner, verbose_name="Prüfer", related_name="purchases", blank=True)
    amount_cents = models.PositiveIntegerField("Betrag (Cent)")
    currency = models.CharField(max_length=3, default="eur")
    provider = models.CharField("Zahlungsart", max_length=20, choices=PROVIDER_CHOICES)
    status = models.CharField("Status", max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    stripe_session_id = models.CharField("Stripe Checkout-Session", max_length=255, blank=True, db_index=True)
    stripe_payment_intent = models.CharField("Stripe PaymentIntent", max_length=255, blank=True)
    created_at = models.DateTimeField("Erstellt am", auto_now_add=True)
    paid_at = models.DateTimeField("Bezahlt am", null=True, blank=True)
    expires_at = models.DateTimeField("Zugriff bis", null=True, blank=True)

    refund_status = models.CharField(
        "Erstattung", max_length=20, choices=REFUND_CHOICES, default=REFUND_NONE, db_index=True
    )
    refunded_cents = models.PositiveIntegerField("Erstattet (Cent)", default=0)
    refund_requested_cents = models.PositiveIntegerField("Angefragte Erstattung (Cent)", default=0)
    refunded_at = models.DateTimeField("Erstattet am", null=True, blank=True)
    stripe_refund_id = models.CharField("Stripe Refund", max_length=255, blank=True)
    refund_error = models.TextField("Fehlermeldung Erstattung", blank=True)
    refund_protocol = models.ForeignKey(
        Protocol, verbose_name="Erstattet für Protokoll", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="refunded_purchases",
    )
    admin_note = models.TextField("Interne Notiz", blank=True)

    objects = PurchaseQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Paket"
        verbose_name_plural = "Pakete"

    def __str__(self):
        return f"{self.number} – {self.exam.code} – {self.email}"

    @property
    def number(self):
        return f"P-{self.pk:05d}" if self.pk else "P-neu"

    @property
    def is_paid(self):
        return self.status == self.STATUS_PAID

    @property
    def is_active(self):
        return self.is_paid and (self.expires_at is None or self.expires_at > timezone.now())

    @property
    def is_expired(self):
        return self.is_paid and self.expires_at is not None and self.expires_at <= timezone.now()

    @property
    def net_cents(self):
        return self.amount_cents - self.refunded_cents

    @property
    def can_be_refunded(self):
        return self.refund_status in {self.REFUND_NONE, self.REFUND_FAILED} and self.status in {
            self.STATUS_PAID, self.STATUS_REVOKED
        }

    @property
    def stripe_dashboard_url(self):
        if not self.stripe_payment_intent:
            return ""
        from core.models import SiteSettings

        prefix = "test/" if SiteSettings.get().stripe_key_mode == "test" else ""
        return f"https://dashboard.stripe.com/{prefix}payments/{self.stripe_payment_intent}"


class StripeEvent(models.Model):
    """Verarbeitete Stripe-Webhook-Ereignisse (verhindert doppelte Verarbeitung)."""

    event_id = models.CharField(max_length=255, unique=True)
    event_type = models.CharField(max_length=120)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-received_at"]
        verbose_name = "Stripe-Ereignis"
        verbose_name_plural = "Stripe-Ereignisse"

    def __str__(self):
        return f"{self.event_type} ({self.event_id})"
