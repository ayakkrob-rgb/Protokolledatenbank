"""Import des Altbestands aus einer Ordnerstruktur oder einem ZIP-Archiv.

Erwartete Struktur (Groß-/Kleinschreibung egal):

    <Prüfung>/<Prüfer>/<Datei>
    <Prüfung>/<Fach>/<Prüfer>/<Datei>

Beispiel:  M1/Anatomie/Prof. Dr. Anna Beispiel/2023-08-24 Protokoll.pdf

* Prüfungen werden über Kürzel oder Name erkannt („M1“, „Physikum (M1)“).
* Fehlende Prüfer (und Fächer) werden automatisch angelegt.
* Ein Datum im Dateinamen (2023-08-24, 24.08.2023, Herbst 2023, WiSe 22/23 …) wird übernommen.
* .txt-Dateien werden als Protokolltext übernommen, alle anderen als Datei.
* Bereits importierte Dateien (gleicher Prüfer, Name und Größe) werden übersprungen.
"""
import datetime
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from django.core.files import File
from django.db import transaction
from django.utils.text import get_valid_filename

from core.audit import audit

from .models import Exam, Protocol, Subject
from .services import get_or_create_examiner

IGNORED_NAMES = {".ds_store", "thumbs.db", "desktop.ini", "__macosx"}
MAX_ZIP_FILES = 20000
MAX_ZIP_BYTES = 4 * 1024 * 1024 * 1024  # 4 GB entpackt


@dataclass
class ImportReport:
    imported: int = 0
    skipped: int = 0
    created_exams: list = field(default_factory=list)
    created_subjects: list = field(default_factory=list)
    created_examiners: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    skipped_files: list = field(default_factory=list)

    def summary(self):
        return (
            f"{self.imported} Protokolle importiert, {self.skipped} übersprungen, "
            f"{len(self.created_examiners)} Prüfer neu angelegt, {len(self.errors)} Fehler"
        )


def _norm(value):
    return re.sub(r"[^a-z0-9äöüß]+", " ", value.lower()).strip()


def match_exam(folder_name, exams):
    wanted = _norm(folder_name)
    tokens = set(wanted.split())
    for exam in exams:
        if wanted in {_norm(exam.code), _norm(exam.name), _norm(exam.slug)}:
            return exam
    for exam in exams:
        if _norm(exam.code) in tokens:
            return exam
    return None


_DATE_PATTERNS = [
    (re.compile(r"(?<!\d)(20\d{2}|19\d{2})[-_.](\d{1,2})[-_.](\d{1,2})(?!\d)"), ("y", "m", "d")),
    (re.compile(r"(?<!\d)(\d{1,2})\.(\d{1,2})\.(20\d{2}|19\d{2}|\d{2})(?!\d)"), ("d", "m", "y")),
]
_PERIOD_PATTERNS = [
    (re.compile(r"(frühjahr|fruehjahr|fj)\s*[-_ ]?\s*(\d{2,4})", re.I), "Frühjahr"),
    (re.compile(r"(herbst|hb)\s*[-_ ]?\s*(\d{2,4})", re.I), "Herbst"),
    (re.compile(r"(sose|ss|sommersemester)\s*[-_ ]?\s*(\d{2,4})", re.I), "SoSe"),
    (re.compile(r"(wise|ws|wintersemester)\s*[-_ ]?\s*(\d{2,4})(?:\s*[/-]\s*\d{2,4})?", re.I), "WiSe"),
]


def _year(value):
    year = int(value)
    return year + 2000 if year < 100 else year


def parse_date_info(filename):
    """Liefert (datum, zeitraum) aus einem Dateinamen."""
    stem = os.path.splitext(filename)[0]
    for pattern, order in _DATE_PATTERNS:
        match = pattern.search(stem)
        if match:
            parts = dict(zip(order, match.groups()))
            try:
                return datetime.date(_year(parts["y"]), int(parts["m"]), int(parts["d"])), ""
            except ValueError:
                continue
    for pattern, label in _PERIOD_PATTERNS:
        match = pattern.search(stem)
        if match:
            return None, f"{label} {_year(match.group(2))}"
    return None, ""


def _read_text(path):
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _visible(path):
    return not any(part.lower() in IGNORED_NAMES or part.startswith(".") for part in path.parts)


def _find_root(root, exams):
    """Steigt in einen einzelnen umschließenden Ordner ab (z. B. „Protokolle/M1/…“)."""
    current = root
    for _ in range(3):
        children = [c for c in current.iterdir() if _visible(c.relative_to(current))]
        dirs = [c for c in children if c.is_dir()]
        files = [c for c in children if c.is_file()]
        if len(dirs) == 1 and not files and match_exam(dirs[0].name, exams) is None:
            current = dirs[0]
        else:
            break
    return current


def import_directory(root, *, site, create_exams=False, status=Protocol.STATUS_PUBLISHED, actor=None, dry_run=False):
    root = Path(root)
    report = ImportReport()
    exams = list(Exam.objects.all())
    root = _find_root(root, exams)
    allowed_ext = set(site.extension_list) | {"txt"}

    for exam_dir in sorted(p for p in root.iterdir() if p.is_dir() and _visible(p.relative_to(root))):
        exam = match_exam(exam_dir.name, exams)
        if exam is None:
            if not create_exams:
                report.errors.append((exam_dir.name, "Keine passende Prüfung gefunden (Ordner übersprungen)."))
                continue
            code = exam_dir.name.strip()[:20]
            if not dry_run:
                exam = Exam.objects.create(code=code, name=exam_dir.name.strip()[:120])
            else:
                exam = Exam(code=code, name=exam_dir.name.strip())
            exams.append(exam)
            report.created_exams.append(exam.name)

        for file_path in sorted(p for p in exam_dir.rglob("*") if p.is_file()):
            rel = file_path.relative_to(exam_dir)
            if not _visible(rel):
                continue
            display = f"{exam_dir.name}/{rel.as_posix()}"
            parts = rel.parts
            if len(parts) == 2:
                subject_name, examiner_name = None, parts[0]
            elif len(parts) == 3:
                subject_name, examiner_name = parts[0], parts[1]
            else:
                report.errors.append((display, "Unerwartete Ordnertiefe – erwartet: Prüfung/[Fach/]Prüfer/Datei."))
                continue
            ext = file_path.suffix.lower().lstrip(".")
            if ext not in allowed_ext:
                report.errors.append((display, f"Dateityp .{ext} wird nicht importiert."))
                continue
            try:
                _import_file(
                    report, file_path, exam, subject_name, examiner_name, status, actor, dry_run
                )
            except Exception as exc:  # noqa: BLE001 – Import soll bei Einzelfehlern weiterlaufen
                report.errors.append((display, str(exc)))

    if not dry_run:
        audit("import.abgeschlossen", report.summary(), actor=actor)
    return report


def _import_file(report, file_path, exam, subject_name, examiner_name, status, actor, dry_run):
    subject = None
    if subject_name:
        subject = Subject.objects.filter(exam=exam, name__iexact=subject_name.strip()).first() if exam.pk else None
        if subject is None:
            if not dry_run:
                subject = Subject.objects.create(exam=exam, name=subject_name.strip()[:120])
            if subject_name.strip() not in report.created_subjects:
                report.created_subjects.append(subject_name.strip())

    if dry_run:
        from .services import find_examiner

        if not exam.pk or find_examiner(exam, examiner_name) is None:
            label = f"{examiner_name} ({exam.code})"
            if label not in report.created_examiners:
                report.created_examiners.append(label)
        report.imported += 1
        return

    with transaction.atomic():
        examiner, created = get_or_create_examiner(exam, examiner_name, subject=subject)
        if created:
            report.created_examiners.append(f"{examiner.name} ({exam.code})")
        elif subject and examiner.subject_id is None:
            examiner.subject = subject
            examiner.save(update_fields=["subject"])

        filename = get_valid_filename(file_path.name)[:255]
        size = file_path.stat().st_size
        if Protocol.objects.filter(examiner=examiner, original_filename=filename, file_size=size).exists():
            report.skipped += 1
            report.skipped_files.append(file_path.name)
            return

        exam_date, period = parse_date_info(file_path.name)
        protocol = Protocol(
            examiner=examiner,
            exam_date=exam_date,
            exam_period=period,
            status=status,
            source=Protocol.SOURCE_IMPORT,
            original_filename=filename,
            file_size=size,
        )
        if file_path.suffix.lower() == ".txt":
            protocol.content = _read_text(file_path)
            protocol.title = os.path.splitext(file_path.name)[0][:200]
        else:
            with file_path.open("rb") as handle:
                protocol.file.save(filename, File(handle), save=False)
        protocol.save()
        report.imported += 1


def _zip_member_name(info):
    name = info.filename
    if not info.flag_bits & 0x800:
        # Ältere ZIP-Programme (z. B. Windows-Explorer) speichern Namen nicht als UTF-8.
        raw = name.encode("cp437", errors="replace")
        for encoding in ("utf-8", "cp850"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
    return name


def extract_zip(zip_source, target_dir):
    target = Path(target_dir).resolve()
    with zipfile.ZipFile(zip_source) as archive:
        members = archive.infolist()
        if len(members) > MAX_ZIP_FILES:
            raise ValueError(f"Das Archiv enthält zu viele Dateien (max. {MAX_ZIP_FILES}).")
        if sum(m.file_size for m in members) > MAX_ZIP_BYTES:
            raise ValueError("Das Archiv ist entpackt zu groß.")
        for info in members:
            if info.is_dir():
                continue
            name = _zip_member_name(info).replace("\\", "/")
            destination = (target / name).resolve()
            if target not in destination.parents:
                continue  # Pfade außerhalb des Zielordners ignorieren
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as src, destination.open("wb") as dst:
                shutil.copyfileobj(src, dst)


def import_zip(zip_source, **kwargs):
    with tempfile.TemporaryDirectory(prefix="protokoll-import-") as tmp:
        extract_zip(zip_source, tmp)
        return import_directory(tmp, **kwargs)
