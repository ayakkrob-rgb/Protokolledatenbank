from django import forms
from django.forms import BaseFormSet, formset_factory
from django.utils import timezone

from .models import Examiner, Protocol, Subject
from core.audit import audit
from core.models import AuditLog

from .services import extract_text, file_sha256, find_copied_protocol, find_examiner, validate_upload_file

NEW_EXAMINER = "new"


def examiner_choices(exam, allow_new=True, include_inactive=False):
    examiners = exam.examiners.select_related("subject").order_by("subject__sort_order", "subject__name", "name")
    if not include_inactive:
        examiners = examiners.filter(is_active=True)
    groups, ungrouped = {}, []
    for examiner in examiners:
        if examiner.subject:
            groups.setdefault(examiner.subject.name, []).append((str(examiner.pk), examiner.name))
        else:
            ungrouped.append((str(examiner.pk), examiner.name))
    choices = [("", "– Prüfer auswählen –")]
    choices += [(name, items) for name, items in groups.items()]
    if ungrouped:
        choices.append(("Weitere Prüfer", ungrouped))
    if allow_new:
        choices.append((NEW_EXAMINER, "+ Neuer Prüfer (nicht in der Liste)"))
    return choices


class UploadMetaForm(forms.Form):
    exam_date = forms.DateField(
        label="Datum deiner Prüfung", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
    )
    grade = forms.CharField(
        label="Note (optional)", max_length=20, required=False, widget=forms.TextInput(attrs={"placeholder": "z. B. 2"})
    )
    confirm_own = forms.BooleanField(label="Ich habe dieses Protokoll selbst nach meiner Prüfung verfasst.")
    confirm_rights = forms.BooleanField(
        label=(
            "Das Protokoll enthält keine Namen von Mitprüflingen oder andere personenbezogene Daten, und ich erlaube "
            "der Fachschaft, es in der Protokolldatenbank zu veröffentlichen."
        )
    )

    def clean_exam_date(self):
        value = self.cleaned_data["exam_date"]
        if value > timezone.localdate():
            raise forms.ValidationError("Das Prüfungsdatum darf nicht in der Zukunft liegen.")
        return value


class ProtocolSectionForm(forms.Form):
    examiner = forms.ChoiceField(label="Prüfer", required=True)
    new_name = forms.CharField(
        label="Name des neuen Prüfers",
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "z. B. Prof. Dr. Erika Musterfrau"}),
    )
    new_subject = forms.ModelChoiceField(
        label="Fach", queryset=Subject.objects.none(), required=False, empty_label="– Fach (optional) –"
    )
    content = forms.CharField(
        label="Protokoll",
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 10,
                "placeholder": "Welche Fragen wurden gestellt? Wie lief die Prüfung ab? Tipps für die Vorbereitung …",
            }
        ),
    )
    file = forms.FileField(label="Datei (optional)", required=False)

    def __init__(self, *args, exam=None, site=None, **kwargs):
        self.exam = exam
        self.site = site
        super().__init__(*args, **kwargs)
        self.fields["examiner"].choices = examiner_choices(exam, allow_new=site.allow_new_examiners)
        self.fields["new_subject"].queryset = exam.subjects.all()
        self.fields["examiner"].widget.attrs["data-examiner-select"] = ""
        self.fields["content"].widget.attrs["data-min-length"] = site.min_text_length
        self.fields["file"].widget.attrs["accept"] = ",".join(f".{e}" for e in site.extension_list)
        self.fields["file"].help_text = (
            f"Erlaubt: {', '.join(site.extension_list)} · max. {site.max_upload_mb} MB"
        )

    def clean(self):
        data = super().clean()
        choice = data.get("examiner")
        data["examiner_obj"] = None
        if choice == NEW_EXAMINER:
            if not self.site.allow_new_examiners:
                self.add_error("examiner", "Bitte wähle einen vorhandenen Prüfer aus.")
            name = " ".join((data.get("new_name") or "").split())
            if len(name) < 3:
                self.add_error("new_name", "Bitte gib den Namen des Prüfers an.")
            else:
                data["new_name"] = name
                data["examiner_obj"] = find_examiner(self.exam, name)
        elif choice:
            examiner = Examiner.objects.filter(pk=choice, exam=self.exam).first() if choice.isdigit() else None
            if examiner is None:
                self.add_error("examiner", "Bitte wähle einen Prüfer aus der Liste.")
            data["examiner_obj"] = examiner

        upload = data.get("file")
        content = (data.get("content") or "").strip()
        if upload:
            error = validate_upload_file(upload, self.site)
            if error:
                self.add_error("file", error)
        elif len(content) < self.site.min_text_length:
            self.add_error(
                "content",
                f"Bitte schreibe dein Protokoll etwas ausführlicher (mindestens {self.site.min_text_length} Zeichen) "
                f"oder lade eine Datei hoch.",
            )
        if not self.errors:
            self._check_for_copies(upload, content)
        return data

    def _check_for_copies(self, upload, content):
        """Lehnt Uploads ab, die nur ein bereits vorhandenes Protokoll wiederholen."""
        duplicate = None
        if upload:
            digest = file_sha256(upload)
            duplicate = Protocol.objects.filter(file_sha256=digest).values_list("pk", flat=True).first()
        if duplicate is None:
            text = content + "\n" + (extract_text(upload) if upload else "")
            duplicate = find_copied_protocol(text)
        if duplicate is not None:
            audit(
                "upload.kopie_erkannt",
                f"Upload für {self.exam.code} abgelehnt: stimmt mit Protokoll #{duplicate} überein.",
                level=AuditLog.LEVEL_WARNING,
            )
            raise forms.ValidationError(
                "Dieses Protokoll stimmt weitgehend mit einem bereits vorhandenen Protokoll überein. "
                "Bitte lade nur dein eigenes Gedächtnisprotokoll hoch."
            )

    @property
    def examiner_key(self):
        data = getattr(self, "cleaned_data", {})
        if data.get("examiner_obj"):
            return f"id:{data['examiner_obj'].pk}"
        if data.get("new_name"):
            return f"new:{data['new_name'].lower()}"
        return None


class BaseSectionFormSet(BaseFormSet):
    def clean(self):
        if any(self.errors):
            return
        seen = set()
        for form in self.forms:
            key = form.examiner_key
            if key and key in seen:
                raise forms.ValidationError("Jeder Prüfer darf pro Upload nur einmal vorkommen.")
            seen.add(key)


def section_formset(max_sections):
    return formset_factory(
        ProtocolSectionForm,
        formset=BaseSectionFormSet,
        extra=0,
        min_num=1,
        max_num=max_sections,
        absolute_max=max_sections,
        validate_min=True,
        validate_max=True,
    )
