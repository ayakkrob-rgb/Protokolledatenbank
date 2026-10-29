from decimal import Decimal

from django.conf import settings
from django.db import models

from . import defaults


class SiteSettings(models.Model):
    """Alle im Adminbereich änderbaren Einstellungen (genau ein Datensatz)."""

    PAYMENT_SIMULATION = "simulation"
    PAYMENT_STRIPE = "stripe"
    PAYMENT_MODES = [
        (PAYMENT_SIMULATION, "Simulation – es fließt kein echtes Geld"),
        (PAYMENT_STRIPE, "Stripe – echte Zahlungen und Erstattungen"),
    ]

    EMAIL_SIMULATION = "simulation"
    EMAIL_SMTP = "smtp"
    EMAIL_MODES = [
        (EMAIL_SIMULATION, "Simulation – E-Mails nur im Postausgang speichern"),
        (EMAIL_SMTP, "SMTP – E-Mails wirklich versenden"),
    ]

    SMTP_STARTTLS = "starttls"
    SMTP_SSL = "ssl"
    SMTP_NONE = "none"
    SMTP_SECURITY = [
        (SMTP_STARTTLS, "STARTTLS (meist Port 587)"),
        (SMTP_SSL, "SSL/TLS (meist Port 465)"),
        (SMTP_NONE, "Unverschlüsselt (nicht empfohlen)"),
    ]

    # Allgemein
    site_name = models.CharField("Name der Webseite", max_length=100, default="Protokolldatenbank")
    organization_name = models.CharField("Name der Fachschaft", max_length=150, default="Fachschaft Medizin")
    contact_email = models.EmailField("Kontakt-E-Mail", blank=True)
    home_intro = models.TextField("Begrüßungstext auf der Startseite", default=defaults.HOME_INTRO)
    announcement = models.TextField(
        "Hinweisbanner",
        blank=True,
        help_text="Wird – falls ausgefüllt – oben auf jeder Seite angezeigt (z. B. Wartungsarbeiten).",
    )
    extra_faq = models.TextField("Zusätzliche Hinweise in den FAQ", blank=True)

    # Registrierung
    registration_open = models.BooleanField("Registrierung geöffnet", default=True)
    allowed_email_domains = models.TextField(
        "Erlaubte E-Mail-Domains",
        default="uni-beispiel.de",
        help_text=(
            "Eine Domain pro Zeile, z. B. „uni-musterstadt.de“. Subdomains (z. B. „stud.uni-musterstadt.de“) "
            "sind automatisch erlaubt. Leer lassen = alle Adressen erlaubt (nicht empfohlen)."
        ),
    )

    # Zahlungen
    payment_mode = models.CharField("Zahlungsmodus", max_length=20, choices=PAYMENT_MODES, default=PAYMENT_SIMULATION)
    price = models.DecimalField("Preis pro Paket (€)", max_digits=7, decimal_places=2, default=Decimal("30.00"))
    refund_amount = models.DecimalField(
        "Erstattung bei eigenem Protokoll (€)", max_digits=7, decimal_places=2, default=Decimal("29.00")
    )
    max_examiners_per_purchase = models.PositiveSmallIntegerField("Maximale Prüfer pro Paket", default=4)
    access_duration_days = models.PositiveIntegerField(
        "Zugriffsdauer in Tagen",
        default=0,
        help_text="0 = unbegrenzter Zugriff auf gekaufte Protokolle.",
    )
    stripe_secret_key = models.CharField(
        "Stripe Secret Key",
        max_length=255,
        blank=True,
        help_text="Beginnt mit „sk_live_“ (echt) bzw. „sk_test_“ (Testmodus) oder „rk_…“ für eingeschränkte Schlüssel.",
    )
    stripe_webhook_secret = models.CharField(
        "Stripe Webhook-Signaturgeheimnis",
        max_length=255,
        blank=True,
        help_text="Beginnt mit „whsec_“. Empfohlen, damit Zahlungen auch dann verbucht werden, wenn jemand das Browserfenster zu früh schließt.",
    )
    checkout_consent_text = models.TextField(
        "Zustimmungstext beim Kauf (Widerrufsrecht)", default=defaults.CHECKOUT_CONSENT
    )

    # Uploads
    require_upload_approval = models.BooleanField(
        "Uploads vor Veröffentlichung prüfen",
        default=False,
        help_text=(
            "Aus: Hochgeladene Protokolle sind sofort sichtbar und die Erstattung erfolgt sofort. "
            "An: Ein Admin muss jedes Protokoll freigeben – erst dann wird es veröffentlicht und erstattet."
        ),
    )
    allow_new_examiners = models.BooleanField(
        "Studierende dürfen neue Prüfer anlegen",
        default=True,
        help_text="Ist ein Prüfer noch nicht vorhanden, wird er beim Hochladen automatisch erstellt.",
    )
    min_text_length = models.PositiveIntegerField(
        "Mindestlänge für Protokolle ohne Datei (Zeichen)", default=200
    )
    max_upload_mb = models.PositiveIntegerField("Maximale Dateigröße (MB)", default=20)
    allowed_file_extensions = models.CharField(
        "Erlaubte Dateiendungen", max_length=255, default="pdf, docx, doc, odt, txt, jpg, jpeg, png"
    )
    watermark_downloads = models.BooleanField(
        "PDF-Downloads mit E-Mail-Adresse kennzeichnen",
        default=True,
        help_text="Erschwert die unerlaubte Weitergabe: Jede Seite erhält eine Fußzeile mit der Adresse des Käufers.",
    )
    upload_guidelines = models.TextField("Hinweise auf der Upload-Seite", default=defaults.UPLOAD_GUIDELINES)

    # E-Mail
    email_mode = models.CharField("E-Mail-Modus", max_length=20, choices=EMAIL_MODES, default=EMAIL_SIMULATION)
    email_from = models.CharField(
        "Absender", max_length=200, blank=True, help_text="z. B. „Fachschaft Medizin <protokolle@uni-musterstadt.de>“"
    )
    smtp_host = models.CharField("SMTP-Server", max_length=200, blank=True)
    smtp_port = models.PositiveIntegerField("SMTP-Port", default=587)
    smtp_username = models.CharField("SMTP-Benutzername", max_length=200, blank=True)
    smtp_password = models.CharField("SMTP-Passwort", max_length=255, blank=True)
    smtp_security = models.CharField("Verschlüsselung", max_length=10, choices=SMTP_SECURITY, default=SMTP_STARTTLS)
    notify_email = models.EmailField(
        "Benachrichtigungen an",
        blank=True,
        help_text="Erhält eine E-Mail bei neuen Uploads und bei fehlgeschlagenen Erstattungen.",
    )

    # Rechtliches
    imprint_text = models.TextField("Impressum", default=defaults.IMPRINT)
    privacy_text = models.TextField("Datenschutzerklärung", default=defaults.PRIVACY)
    terms_text = models.TextField("Nutzungsbedingungen", default=defaults.TERMS)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Einstellungen"
        verbose_name_plural = "Einstellungen"

    def __str__(self):
        return "Einstellungen"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    # --- abgeleitete Werte -------------------------------------------------

    @property
    def is_simulation(self):
        return self.payment_mode != self.PAYMENT_STRIPE

    @property
    def effective_stripe_secret_key(self):
        return settings.STRIPE_SECRET_KEY or self.stripe_secret_key

    @property
    def effective_stripe_webhook_secret(self):
        return settings.STRIPE_WEBHOOK_SECRET or self.stripe_webhook_secret

    @property
    def effective_smtp_password(self):
        return settings.SMTP_PASSWORD or self.smtp_password

    @property
    def stripe_key_mode(self):
        key = self.effective_stripe_secret_key
        if not key:
            return ""
        if "_live_" in key:
            return "live"
        if "_test_" in key:
            return "test"
        return "unbekannt"

    @property
    def domain_list(self):
        domains = []
        for line in self.allowed_email_domains.replace(",", "\n").splitlines():
            domain = line.strip().lower().lstrip("@")
            if domain:
                domains.append(domain)
        return domains

    def email_domain_allowed(self, email):
        domains = self.domain_list
        if not domains:
            return True
        host = email.rsplit("@", 1)[-1].lower()
        return any(host == d or host.endswith("." + d) for d in domains)

    @property
    def extension_list(self):
        return sorted(
            {e.strip().lower().lstrip(".") for e in self.allowed_file_extensions.split(",") if e.strip()}
        )

    @property
    def sender(self):
        return self.email_from or settings.DEFAULT_FROM_EMAIL


class EmailLog(models.Model):
    """Postausgang: jede versendete (oder simulierte) E-Mail wird protokolliert."""

    STATUS_SIMULATED = "simulated"
    STATUS_SENT = "sent"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_SIMULATED, "Simuliert"),
        (STATUS_SENT, "Versendet"),
        (STATUS_FAILED, "Fehlgeschlagen"),
    ]

    created_at = models.DateTimeField("Zeitpunkt", auto_now_add=True)
    to = models.CharField("Empfänger", max_length=254)
    subject = models.CharField("Betreff", max_length=255)
    body = models.TextField("Inhalt")
    kind = models.CharField("Art", max_length=40, blank=True)
    status = models.CharField("Status", max_length=20, choices=STATUS_CHOICES)
    error = models.TextField("Fehler", blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "E-Mail"
        verbose_name_plural = "Postausgang"

    def __str__(self):
        return f"{self.to}: {self.subject}"


class AuditLog(models.Model):
    """Logbuch für alle wichtigen Vorgänge (Zahlungen, Erstattungen, Admin-Aktionen)."""

    LEVEL_INFO = "info"
    LEVEL_WARNING = "warning"
    LEVEL_ERROR = "error"
    LEVEL_CHOICES = [(LEVEL_INFO, "Info"), (LEVEL_WARNING, "Warnung"), (LEVEL_ERROR, "Fehler")]

    created_at = models.DateTimeField("Zeitpunkt", auto_now_add=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Ausgelöst von",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    action = models.CharField("Aktion", max_length=60)
    message = models.TextField("Beschreibung")
    level = models.CharField("Stufe", max_length=10, choices=LEVEL_CHOICES, default=LEVEL_INFO)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Logbuch-Eintrag"
        verbose_name_plural = "Logbuch"

    def __str__(self):
        return f"{self.action}: {self.message[:60]}"
