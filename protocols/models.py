import os
import re
import uuid

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from core.utils import to_cents

def protocol_storage():
    """Geschützter Speicherort – Dateien sind nicht direkt per URL erreichbar."""
    return FileSystemStorage(location=settings.PROTOCOL_FILES_ROOT, base_url=None)


def protocol_upload_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()[:10]
    return f"{timezone.now():%Y/%m}/{uuid.uuid4().hex}{ext}"


class Exam(models.Model):
    code = models.CharField("Kürzel", max_length=20, unique=True, help_text="z. B. „M1“")
    name = models.CharField("Name", max_length=120, help_text="z. B. „Physikum (M1)“")
    slug = models.SlugField("URL-Kürzel", max_length=40, unique=True, blank=True)
    description = models.TextField("Beschreibung", blank=True)
    is_active = models.BooleanField("Aktiv", default=True, help_text="Inaktive Prüfungen sind für Studierende unsichtbar.")
    sort_order = models.PositiveIntegerField("Reihenfolge", default=0)
    price_override = models.DecimalField(
        "Abweichender Preis (€)", max_digits=7, decimal_places=2, null=True, blank=True,
        help_text="Leer lassen = Standardpreis aus den Einstellungen.",
    )
    refund_override = models.DecimalField(
        "Abweichende Erstattung (€)", max_digits=7, decimal_places=2, null=True, blank=True,
        help_text="Leer lassen = Standarderstattung aus den Einstellungen.",
    )
    max_examiners_override = models.PositiveSmallIntegerField(
        "Abweichende max. Prüferzahl", null=True, blank=True,
        help_text="Leer lassen = Standardwert aus den Einstellungen.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "code"]
        verbose_name = "Prüfung"
        verbose_name_plural = "Prüfungen"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.code) or slugify(self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("protocols:exam_detail", args=[self.slug])

    def price_cents(self, site):
        return to_cents(self.price_override if self.price_override is not None else site.price)

    def refund_cents(self, site):
        return to_cents(self.refund_override if self.refund_override is not None else site.refund_amount)

    def max_examiners(self, site):
        return self.max_examiners_override or site.max_examiners_per_purchase


class Subject(models.Model):
    exam = models.ForeignKey(Exam, verbose_name="Prüfung", on_delete=models.CASCADE, related_name="subjects")
    name = models.CharField("Fach", max_length=120)
    sort_order = models.PositiveIntegerField("Reihenfolge", default=0)

    class Meta:
        ordering = ["sort_order", "name"]
        unique_together = [("exam", "name")]
        verbose_name = "Fach"
        verbose_name_plural = "Fächer"

    def __str__(self):
        return self.name


_TITLE_RE = re.compile(
    r"\b(univ\.?-?|prof\.?|professor(in)?|priv\.?-?doz\.?|pd|dr\.?|med\.?|dent\.?|rer\.?|nat\.?|phil\.?|habil\.?|dipl\.?|"
    r"mult\.?|h\.?\s?c\.?|frau|herr|oä|oa|ca|chefarzt|oberarzt|oberärztin|chefärztin)(?=\s|$|\.)",
    re.IGNORECASE,
)


def normalize_person_name(name):
    """Vergleichsschlüssel für Namen – ohne Titel, Satzzeichen und Groß-/Kleinschreibung.

    „Prof. Dr. med. Anna Müller“ und „anna  müller“ ergeben denselben Schlüssel.
    """
    value = _TITLE_RE.sub(" ", name.lower())
    value = re.sub(r"[^\wäöüß]+", " ", value)
    return " ".join(value.split())


class Examiner(models.Model):
    exam = models.ForeignKey(Exam, verbose_name="Prüfung", on_delete=models.CASCADE, related_name="examiners")
    subject = models.ForeignKey(
        Subject, verbose_name="Fach", null=True, blank=True, on_delete=models.SET_NULL, related_name="examiners"
    )
    name = models.CharField("Name", max_length=150, help_text="z. B. „Prof. Dr. Anna Beispiel“")
    institute = models.CharField("Institut / Klinik", max_length=200, blank=True)
    description = models.TextField(
        "Hinweise für Studierende", blank=True, help_text="Für Käufer sichtbar, z. B. Prüfungsstil oder Schwerpunkte."
    )
    is_active = models.BooleanField("Aktiv", default=True, help_text="Inaktive Prüfer können nicht mehr neu gekauft werden.")
    created_via_upload = models.BooleanField("Durch Upload angelegt", default=False)
    name_key = models.CharField(max_length=150, editable=False, db_index=True, default="")
    created_at = models.DateTimeField("Angelegt am", auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Prüfer"
        verbose_name_plural = "Prüfer"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.name = " ".join(self.name.split())
        self.name_key = normalize_person_name(self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("protocols:examiner_detail", args=[self.pk])

    @property
    def initials(self):
        parts = [p for p in normalize_person_name(self.name).split() if p]
        if not parts:
            return "?"
        if len(parts) == 1:
            return parts[0][:2].upper()
        return (parts[0][0] + parts[-1][0]).upper()


class ProtocolQuerySet(models.QuerySet):
    def published(self):
        return self.filter(status=Protocol.STATUS_PUBLISHED)


class Protocol(models.Model):
    STATUS_PENDING = "pending"
    STATUS_PUBLISHED = "published"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Wartet auf Freigabe"),
        (STATUS_PUBLISHED, "Veröffentlicht"),
        (STATUS_REJECTED, "Abgelehnt"),
    ]

    SOURCE_UPLOAD = "upload"
    SOURCE_ADMIN = "admin"
    SOURCE_IMPORT = "import"
    SOURCE_DEMO = "demo"
    SOURCE_CHOICES = [
        (SOURCE_UPLOAD, "Upload durch Studierende"),
        (SOURCE_ADMIN, "Durch Admin angelegt"),
        (SOURCE_IMPORT, "Import (Altbestand)"),
        (SOURCE_DEMO, "Beispieldaten"),
    ]

    examiner = models.ForeignKey(Examiner, verbose_name="Prüfer", on_delete=models.PROTECT, related_name="protocols")
    title = models.CharField("Titel", max_length=200, blank=True)
    exam_date = models.DateField("Prüfungsdatum", null=True, blank=True)
    exam_period = models.CharField(
        "Prüfungszeitraum", max_length=60, blank=True, help_text="z. B. „Herbst 2024“ – wird aus dem Datum ergänzt."
    )
    content = models.TextField("Protokolltext", blank=True)
    file = models.FileField("Datei", storage=protocol_storage, upload_to=protocol_upload_path, blank=True, max_length=255)
    original_filename = models.CharField("Ursprünglicher Dateiname", max_length=255, blank=True)
    file_size = models.PositiveIntegerField("Dateigröße", default=0)
    file_sha256 = models.CharField("Prüfsumme der Datei", max_length=64, blank=True, db_index=True)
    file_text = models.TextField(
        "Text aus der Datei", blank=True, editable=False,
        help_text="Automatisch ausgelesen (PDF/TXT) – für Suche und Kopie-Erkennung.",
    )
    grade = models.CharField("Note", max_length=20, blank=True)
    status = models.CharField("Status", max_length=20, choices=STATUS_CHOICES, default=STATUS_PUBLISHED, db_index=True)
    source = models.CharField("Herkunft", max_length=20, choices=SOURCE_CHOICES, default=SOURCE_ADMIN)
    rejection_reason = models.TextField("Ablehnungsgrund", blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Hochgeladen von", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="uploaded_protocols",
    )
    submission_key = models.CharField(max_length=40, blank=True, db_index=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Geprüft von", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    reviewed_at = models.DateTimeField("Geprüft am", null=True, blank=True)
    published_at = models.DateTimeField("Veröffentlicht am", null=True, blank=True)
    view_count = models.PositiveIntegerField("Aufrufe", default=0)
    download_count = models.PositiveIntegerField("Downloads", default=0)
    created_at = models.DateTimeField("Erstellt am", auto_now_add=True)
    updated_at = models.DateTimeField("Geändert am", auto_now=True)

    objects = ProtocolQuerySet.as_manager()

    class Meta:
        ordering = ["-exam_date", "-created_at"]
        verbose_name = "Protokoll"
        verbose_name_plural = "Protokolle"

    def __str__(self):
        return self.display_title

    def save(self, *args, **kwargs):
        if self.exam_date and not self.exam_period:
            self.exam_period = period_for_date(self.exam_date)
        if self.status == self.STATUS_PUBLISHED and not self.published_at:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("protocols:protocol_detail", args=[self.pk])

    @property
    def exam(self):
        return self.examiner.exam

    @property
    def display_title(self):
        if self.title:
            return self.title
        when = self.exam_date.strftime("%d.%m.%Y") if self.exam_date else self.exam_period
        return f"Protokoll vom {when}" if when else f"Protokoll Nr. {self.pk or '–'}"

    @property
    def date_label(self):
        if self.exam_date:
            return self.exam_date.strftime("%d.%m.%Y")
        return self.exam_period or "Datum unbekannt"

    @property
    def file_extension(self):
        name = self.original_filename or (self.file.name if self.file else "")
        return os.path.splitext(name)[1].lower().lstrip(".")

    @property
    def is_pdf(self):
        return bool(self.file) and self.file_extension == "pdf"

    @property
    def is_image(self):
        return bool(self.file) and self.file_extension in {"jpg", "jpeg", "png"}

    @property
    def is_published(self):
        return self.status == self.STATUS_PUBLISHED

    @property
    def word_count(self):
        return len(self.content.split()) if self.content else 0


def period_for_date(value):
    season = "Frühjahr" if value.month <= 6 else "Herbst"
    return f"{season} {value.year}"
