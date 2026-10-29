from decimal import Decimal

from django import forms

from accounts.models import User
from core.models import SiteSettings
from payments.models import Purchase
from protocols.models import Exam, Examiner, Protocol, Subject
from protocols.services import validate_upload_file

DATE_INPUT = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class ExamForm(forms.ModelForm):
    class Meta:
        model = Exam
        fields = [
            "code", "name", "slug", "description", "is_active", "sort_order",
            "price_override", "refund_override", "max_examiners_override",
        ]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}
        help_texts = {"slug": "Teil der Adresse, z. B. /pruefungen/m1/. Leer lassen = automatisch aus dem Kürzel."}

    def clean(self):
        data = super().clean()
        price, refund = data.get("price_override"), data.get("refund_override")
        site = SiteSettings.get()
        effective_price = price if price is not None else site.price
        effective_refund = refund if refund is not None else site.refund_amount
        if effective_refund > effective_price:
            self.add_error("refund_override", "Die Erstattung darf nicht höher als der Preis sein.")
        return data


class SubjectForm(forms.ModelForm):
    class Meta:
        model = Subject
        fields = ["name", "sort_order"]


class SubjectChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.exam.code} – {obj.name}"


class ExaminerChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        suffix = "" if obj.is_active else " (inaktiv)"
        return f"{obj.exam.code} – {obj.name}{suffix}"


class ExaminerForm(forms.ModelForm):
    subject = SubjectChoiceField(
        label="Fach", queryset=Subject.objects.select_related("exam").order_by("exam__sort_order", "sort_order", "name"),
        required=False, empty_label="– kein Fach –",
    )

    class Meta:
        model = Examiner
        fields = ["exam", "subject", "name", "institute", "description", "is_active"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def clean(self):
        data = super().clean()
        exam, subject, name = data.get("exam"), data.get("subject"), data.get("name")
        if exam and subject and subject.exam_id != exam.pk:
            self.add_error("subject", "Dieses Fach gehört zu einer anderen Prüfung.")
        if exam and name:
            from protocols.models import normalize_person_name

            clash = Examiner.objects.filter(exam=exam, name_key=normalize_person_name(name))
            if self.instance.pk:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                self.add_error(
                    "name",
                    f"Es gibt bereits „{clash.first().name}“ in dieser Prüfung. Nutze ggf. „Zusammenführen“.",
                )
        return data


class MergeExaminerForm(forms.Form):
    target = ExaminerChoiceField(label="Zusammenführen mit", queryset=Examiner.objects.none())

    def __init__(self, *args, source=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["target"].queryset = (
            Examiner.objects.filter(exam=source.exam).exclude(pk=source.pk).select_related("exam").order_by("name")
        )


class ProtocolAdminForm(forms.ModelForm):
    examiner = ExaminerChoiceField(
        label="Prüfer", queryset=Examiner.objects.select_related("exam").order_by("exam__sort_order", "name")
    )
    upload = forms.FileField(label="Datei hochladen / ersetzen", required=False)
    remove_file = forms.BooleanField(label="Vorhandene Datei entfernen", required=False)

    class Meta:
        model = Protocol
        fields = ["examiner", "title", "exam_date", "exam_period", "grade", "content", "status", "rejection_reason"]
        widgets = {
            "exam_date": DATE_INPUT,
            "content": forms.Textarea(attrs={"rows": 14}),
            "rejection_reason": forms.Textarea(attrs={"rows": 2}),
        }

    def clean(self):
        data = super().clean()
        upload = data.get("upload")
        if upload:
            error = validate_upload_file(upload, SiteSettings.get(), enforce_size=False)
            if error:
                self.add_error("upload", error)
        has_file = bool(upload) or (bool(self.instance.file) and not data.get("remove_file"))
        if not has_file and not (data.get("content") or "").strip():
            self.add_error("content", "Bitte Text eingeben oder eine Datei hochladen.")
        return data


class RejectForm(forms.Form):
    reason = forms.CharField(
        label="Begründung (wird dem Uploader per E-Mail geschickt)",
        widget=forms.Textarea(attrs={"rows": 2}),
        initial="Das Protokoll ist leider nicht aussagekräftig genug.",
    )


class ImportForm(forms.Form):
    archive = forms.FileField(label="ZIP-Archiv", help_text="Ordnerstruktur: Prüfung/[Fach/]Prüfer/Datei")
    create_exams = forms.BooleanField(label="Unbekannte Prüfungen automatisch anlegen", required=False)
    status = forms.ChoiceField(
        label="Status der importierten Protokolle",
        choices=[(Protocol.STATUS_PUBLISHED, "Sofort veröffentlichen"), (Protocol.STATUS_PENDING, "Erst prüfen (Freigaben)")],
    )
    dry_run = forms.BooleanField(label="Nur testen (nichts speichern)", required=False)

    def clean_archive(self):
        archive = self.cleaned_data["archive"]
        if not archive.name.lower().endswith(".zip"):
            raise forms.ValidationError("Bitte eine .zip-Datei hochladen.")
        return archive


class UserAdminForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["name", "email", "email_verified", "is_active", "is_staff", "admin_note"]
        widgets = {"admin_note": forms.Textarea(attrs={"rows": 3})}
        labels = {"is_active": "Aktiv (nicht gesperrt)"}

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Diese E-Mail-Adresse wird bereits verwendet.")
        return email


class UserCreateForm(forms.Form):
    name = forms.CharField(label="Name", max_length=150)
    email = forms.EmailField(label="E-Mail-Adresse")
    is_staff = forms.BooleanField(label="Admin (Zugang zur Verwaltung)", required=False)

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Für diese Adresse gibt es bereits ein Konto.")
        return email


class GrantPackageForm(forms.Form):
    exam = forms.ModelChoiceField(label="Prüfung", queryset=Exam.objects.all())
    examiners = forms.ModelMultipleChoiceField(
        label="Prüfer",
        queryset=Examiner.objects.select_related("exam").order_by("exam__sort_order", "name"),
        widget=forms.SelectMultiple(attrs={"size": 8}),
        help_text="Strg/Cmd gedrückt halten für Mehrfachauswahl.",
    )
    amount = forms.DecimalField(
        label="Bezahlter Betrag (€)", min_value=Decimal("0"), max_digits=7, decimal_places=2, initial=Decimal("0"),
        help_text="0 = kostenlos freischalten. Ein Betrag > 0 (z. B. Barzahlung) wird bei Upload manuell erstattet.",
    )
    note = forms.CharField(label="Notiz", required=False)

    def clean(self):
        data = super().clean()
        exam, examiners = data.get("exam"), data.get("examiners")
        if exam and examiners:
            wrong = [e.name for e in examiners if e.exam_id != exam.pk]
            if wrong:
                self.add_error("examiners", f"Gehört nicht zu {exam.code}: {', '.join(wrong)}")
            limit = exam.max_examiners(SiteSettings.get())
            if len(examiners) > limit:
                self.add_error("examiners", f"Höchstens {limit} Prüfer pro Paket.")
        return data


class PurchaseEditForm(forms.ModelForm):
    examiners = forms.ModelMultipleChoiceField(
        label="Freigeschaltete Prüfer", queryset=Examiner.objects.none(), required=False,
        widget=forms.SelectMultiple(attrs={"size": 8}),
    )
    expires_at = forms.DateTimeField(
        label="Zugriff bis", required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        help_text="Leer = unbegrenzt",
    )

    class Meta:
        model = Purchase
        fields = ["examiners", "expires_at", "admin_note"]
        widgets = {"admin_note": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["examiners"].queryset = Examiner.objects.filter(exam=self.instance.exam).order_by("name")


SECRET_FIELDS = ["stripe_secret_key", "stripe_webhook_secret", "smtp_password"]

SETTINGS_SECTIONS = [
    (
        "allgemein", "Allgemein", "settings",
        ["site_name", "organization_name", "contact_email", "home_intro", "announcement", "extra_faq"],
    ),
    ("registrierung", "Registrierung", "users", ["registration_open", "allowed_email_domains"]),
    (
        "zahlungen", "Zahlungen & Stripe", "card",
        [
            "payment_mode", "price", "refund_amount", "max_examiners_per_purchase", "access_duration_days",
            "stripe_secret_key", "stripe_webhook_secret", "checkout_consent_text",
        ],
    ),
    (
        "uploads", "Uploads", "upload",
        [
            "require_upload_approval", "allow_new_examiners", "min_text_length", "max_upload_mb",
            "allowed_file_extensions", "watermark_downloads", "upload_guidelines",
        ],
    ),
    (
        "email", "E-Mail", "mail",
        ["email_mode", "email_from", "smtp_host", "smtp_port", "smtp_username", "smtp_password", "smtp_security", "notify_email"],
    ),
    ("rechtliches", "Rechtliches", "book", ["imprint_text", "privacy_text", "terms_text"]),
]


class SettingsForm(forms.ModelForm):
    clear_stripe_secret_key = forms.BooleanField(label="Gespeicherten Schlüssel löschen", required=False)
    clear_stripe_webhook_secret = forms.BooleanField(label="Gespeichertes Geheimnis löschen", required=False)
    clear_smtp_password = forms.BooleanField(label="Gespeichertes Passwort löschen", required=False)

    class Meta:
        model = SiteSettings
        exclude = ["updated_at"]
        widgets = {
            "home_intro": forms.Textarea(attrs={"rows": 3}),
            "announcement": forms.Textarea(attrs={"rows": 2}),
            "extra_faq": forms.Textarea(attrs={"rows": 4}),
            "allowed_email_domains": forms.Textarea(attrs={"rows": 3}),
            "checkout_consent_text": forms.Textarea(attrs={"rows": 3}),
            "upload_guidelines": forms.Textarea(attrs={"rows": 6}),
            "imprint_text": forms.Textarea(attrs={"rows": 14}),
            "privacy_text": forms.Textarea(attrs={"rows": 18}),
            "terms_text": forms.Textarea(attrs={"rows": 18}),
            "stripe_secret_key": forms.PasswordInput(render_value=False, attrs={"autocomplete": "off"}),
            "stripe_webhook_secret": forms.PasswordInput(render_value=False, attrs={"autocomplete": "off"}),
            "smtp_password": forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._stored = {name: getattr(self.instance, name) for name in SECRET_FIELDS}
        for name in SECRET_FIELDS:
            stored = self._stored[name]
            if stored:
                self.fields[name].widget.attrs["placeholder"] = f"gespeichert (…{stored[-4:]}) – leer lassen = unverändert"

    def clean_stripe_secret_key(self):
        value = (self.cleaned_data.get("stripe_secret_key") or "").strip()
        if value and not value.startswith(("sk_", "rk_")):
            raise forms.ValidationError("Der Secret Key beginnt mit „sk_“ oder „rk_“ (nicht mit „pk_“ – das ist der öffentliche Schlüssel).")
        return value

    def clean_stripe_webhook_secret(self):
        value = (self.cleaned_data.get("stripe_webhook_secret") or "").strip()
        if value and not value.startswith("whsec_"):
            raise forms.ValidationError("Das Signaturgeheimnis beginnt mit „whsec_“.")
        return value

    def clean(self):
        data = super().clean()
        for name in SECRET_FIELDS:
            if data.get(f"clear_{name}"):
                data[name] = ""
            elif not data.get(name):
                data[name] = self._stored[name]
        price, refund = data.get("price"), data.get("refund_amount")
        if price is not None and refund is not None and refund > price:
            self.add_error("refund_amount", "Die Erstattung darf nicht höher als der Preis sein.")
        if data.get("payment_mode") == SiteSettings.PAYMENT_STRIPE:
            from django.conf import settings

            if not (data.get("stripe_secret_key") or settings.STRIPE_SECRET_KEY):
                self.add_error("stripe_secret_key", "Für den Stripe-Modus wird ein Secret Key benötigt.")
            if price is not None and Decimal("0") < price < Decimal("0.50"):
                self.add_error("price", "Stripe verlangt mindestens 0,50 €.")
        if data.get("email_mode") == SiteSettings.EMAIL_SMTP and not data.get("smtp_host"):
            self.add_error("smtp_host", "Für echten E-Mail-Versand wird ein SMTP-Server benötigt.")
        if data.get("max_examiners_per_purchase") == 0:
            self.add_error("max_examiners_per_purchase", "Mindestens 1.")
        return data

    def save(self, commit=True):
        instance = super().save(commit=False)
        for name in SECRET_FIELDS:
            setattr(instance, name, self.cleaned_data.get(name, ""))
        if commit:
            instance.save()
        return instance
