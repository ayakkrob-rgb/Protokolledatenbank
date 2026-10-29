import hashlib
import io
import logging
import os
import re
import uuid

from django.db import transaction
from django.utils import timezone
from django.utils.text import get_valid_filename, slugify

from core.audit import audit
from core.pdf import render_text_pdf, stamp_pdf

from .models import Examiner, Protocol, normalize_person_name

logger = logging.getLogger(__name__)

MAGIC_BYTES = {
    "pdf": (b"%PDF",),
    "png": (b"\x89PNG",),
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
    "docx": (b"PK\x03\x04",),
    "odt": (b"PK\x03\x04",),
    "doc": (b"\xd0\xcf\x11\xe0",),
    "rtf": (b"{\\rtf",),
}

CONTENT_TYPES = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
}


def validate_upload_file(uploaded, site, enforce_size=True):
    """Gibt eine Fehlermeldung zurück oder ``None``, wenn die Datei in Ordnung ist."""
    ext = os.path.splitext(uploaded.name)[1].lower().lstrip(".")
    allowed = site.extension_list
    if ext not in allowed:
        return f"Dateityp „.{ext or '?'}“ ist nicht erlaubt. Erlaubt: {', '.join(allowed)}."
    if enforce_size and uploaded.size > site.max_upload_mb * 1024 * 1024:
        return f"Die Datei ist zu groß (maximal {site.max_upload_mb} MB)."
    if uploaded.size == 0:
        return "Die Datei ist leer."
    signatures = MAGIC_BYTES.get(ext)
    if signatures:
        head = uploaded.read(8)
        uploaded.seek(0)
        if not any(head.startswith(sig) for sig in signatures):
            return f"Die Datei scheint keine gültige .{ext}-Datei zu sein."
    return None


def file_sha256(uploaded):
    digest = hashlib.sha256()
    for chunk in uploaded.chunks():
        digest.update(chunk)
    uploaded.seek(0)
    return digest.hexdigest()


def extract_text(uploaded, max_pages=40, max_chars=200_000):
    """Liest (bestmöglich) den Text aus PDF- und TXT-Dateien – für Suche und Kopie-Erkennung."""
    ext = os.path.splitext(uploaded.name)[1].lower()
    try:
        uploaded.seek(0)
        data = uploaded.read()
        uploaded.seek(0)
        if ext == ".txt":
            for encoding in ("utf-8-sig", "cp1252"):
                try:
                    return data.decode(encoding)[:max_chars]
                except UnicodeDecodeError:
                    continue
            return ""
        if ext == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            parts = []
            for page in reader.pages[:max_pages]:
                parts.append(page.extract_text() or "")
                if sum(len(p) for p in parts) > max_chars:
                    break
            return "\n".join(parts)[:max_chars]
    except Exception:  # noqa: BLE001 – beschädigte Dateien sollen den Upload nicht verhindern
        logger.info("Text konnte nicht aus %s gelesen werden", uploaded.name)
    return ""


def attach_file(protocol, uploaded, filename=None):
    name = filename or uploaded.name
    protocol.original_filename = get_valid_filename(os.path.basename(name))[:255] or "protokoll"
    protocol.file_size = uploaded.size
    protocol.file_sha256 = file_sha256(uploaded)
    protocol.file_text = extract_text(uploaded)
    protocol.file.save(protocol.original_filename, uploaded, save=False)


_WORD_RE = re.compile(r"[a-zäöüß0-9]+")


def _shingles(text, size=5):
    words = _WORD_RE.findall((text or "").lower())
    return {" ".join(words[i:i + size]) for i in range(max(0, len(words) - size + 1))}


def find_copied_protocol(text, threshold=0.75):
    """Findet ein vorhandenes Protokoll (aus allen Prüfungen), das (fast) wortgleich ist.

    Verglichen werden Folgen von je fünf Wörtern in beide Richtungen, damit auch eine Kopie
    mit ein paar ergänzten Sätzen oder ein heruntergeladenes (gekennzeichnetes) PDF erkannt wird.
    """
    new = _shingles(text)
    if len(new) < 10:
        return None
    candidates = Protocol.objects.values_list("pk", "content", "file_text")
    for pk, content, file_text in candidates.iterator():
        for existing_text in (content, file_text):
            existing = _shingles(existing_text)
            if len(existing) < 10:
                continue
            common = len(new & existing)
            if common / len(new) >= threshold or common / len(existing) >= threshold:
                return pk
    return None


def find_examiner(exam, name):
    key = normalize_person_name(name)
    if not key:
        return None
    return exam.examiners.filter(name_key=key).order_by("-is_active", "pk").first()


def get_or_create_examiner(exam, name, subject=None, via_upload=False, active=True):
    existing = find_examiner(exam, name)
    if existing:
        return existing, False
    examiner = Examiner.objects.create(
        exam=exam, name=name.strip(), subject=subject, created_via_upload=via_upload, is_active=active
    )
    return examiner, True


def create_submission(*, user, exam, exam_date, grade, sections, site, source=Protocol.SOURCE_UPLOAD):
    """Legt ein oder mehrere Protokolle (je Prüfer eins) aus einem Upload an.

    ``sections`` ist eine Liste von Dicts mit ``examiner`` (oder ``None``),
    ``new_name``, ``subject``, ``content`` und ``file``.
    """
    needs_review = site.require_upload_approval and not (user and user.is_staff)
    status = Protocol.STATUS_PENDING if needs_review else Protocol.STATUS_PUBLISHED
    key = uuid.uuid4().hex
    protocols, new_examiners = [], []
    with transaction.atomic():
        for section in sections:
            examiner = section.get("examiner")
            if examiner is None:
                examiner, created = get_or_create_examiner(
                    exam, section["new_name"], subject=section.get("subject"), via_upload=True, active=not needs_review
                )
                if created:
                    new_examiners.append(examiner)
            protocol = Protocol(
                examiner=examiner,
                exam_date=exam_date,
                grade=grade or "",
                content=(section.get("content") or "").strip(),
                status=status,
                source=source,
                uploaded_by=user,
                submission_key=key,
            )
            if section.get("file"):
                attach_file(protocol, section["file"])
            protocol.save()
            protocols.append(protocol)
    names = ", ".join(p.examiner.name for p in protocols)
    audit(
        "protokoll.hochgeladen",
        f"{len(protocols)} Protokoll(e) für {exam.code} ({names}) von {user.email if user else 'unbekannt'}"
        + (f"; neue Prüfer: {', '.join(e.name for e in new_examiners)}" if new_examiners else ""),
        actor=user,
    )
    return protocols, new_examiners


def publish_protocols(protocols, actor=None):
    """Veröffentlicht Protokolle und löst ggf. die Erstattung für den Uploader aus.

    Gibt die Liste der Erstattungsergebnisse zurück (siehe payments.services).
    """
    from payments.services import reward_uploads

    now = timezone.now()
    published = []
    for protocol in protocols:
        if protocol.status == Protocol.STATUS_PUBLISHED and protocol.reviewed_at:
            published.append(protocol)
            continue
        protocol.status = Protocol.STATUS_PUBLISHED
        protocol.rejection_reason = ""
        if actor is not None:
            protocol.reviewed_by = actor
            protocol.reviewed_at = now
        protocol.published_at = protocol.published_at or now
        protocol.save()
        examiner = protocol.examiner
        if not examiner.is_active and examiner.created_via_upload:
            examiner.is_active = True
            examiner.save(update_fields=["is_active"])
        published.append(protocol)
    return reward_uploads(published, actor=actor)


def reject_protocol(protocol, reason, actor=None):
    protocol.status = Protocol.STATUS_REJECTED
    protocol.rejection_reason = reason
    protocol.reviewed_by = actor
    protocol.reviewed_at = timezone.now()
    protocol.save()
    audit("protokoll.abgelehnt", f"Protokoll #{protocol.pk} ({protocol.examiner}) abgelehnt: {reason}", actor=actor)


# --- Download ------------------------------------------------------------------


def download_basename(protocol):
    parts = [protocol.examiner.exam.code, protocol.examiner.name]
    if protocol.exam_date:
        parts.append(protocol.exam_date.isoformat())
    elif protocol.exam_period:
        parts.append(protocol.exam_period)
    parts.append(f"nr{protocol.pk}")
    return slugify(" ".join(parts)) or f"protokoll-{protocol.pk}"


def watermark_text(user, site):
    return (
        f"Persönliche Kopie für {user.email} · {site.organization_name} · "
        f"{timezone.localdate():%d.%m.%Y} · Weitergabe nicht gestattet"
    )


def build_file_download(protocol, user, site):
    """Liefert (Daten, Dateiname, Content-Type) für die hochgeladene Datei."""
    ext = protocol.file_extension
    with protocol.file.open("rb") as handle:
        data = handle.read()
    if ext == "pdf" and site.watermark_downloads:
        data = stamp_pdf(data, watermark_text(user, site), diagonal_text=user.email)
    content_type = CONTENT_TYPES.get(ext, "application/octet-stream")
    return data, f"{download_basename(protocol)}.{ext or 'bin'}", content_type


def build_text_pdf(protocol, user, site):
    """Erzeugt aus dem Protokolltext ein PDF."""
    examiner = protocol.examiner
    meta = [
        f"Prüfung: {examiner.exam.name}",
        f"Prüfer: {examiner.name}" + (f" ({examiner.subject.name})" if examiner.subject else ""),
        f"Datum: {protocol.date_label}" + (f" · Note: {protocol.grade}" if protocol.grade else ""),
    ]
    footer = watermark_text(user, site) if site.watermark_downloads else f"{site.site_name} · {site.organization_name}"
    data = render_text_pdf(
        protocol.display_title,
        meta,
        protocol.content,
        footer_text=footer,
        diagonal_text=user.email if site.watermark_downloads else "",
    )
    return data, f"{download_basename(protocol)}.pdf", "application/pdf"
