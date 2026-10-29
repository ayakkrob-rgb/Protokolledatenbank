from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.models import SiteSettings
from protocols import importer
from protocols.models import Protocol


class Command(BaseCommand):
    help = (
        "Importiert vorhandene Protokolle aus einem Ordner oder ZIP-Archiv. "
        "Struktur: <Prüfung>/[<Fach>/]<Prüfer>/<Datei>"
    )

    def add_arguments(self, parser):
        parser.add_argument("pfad", help="Ordner oder .zip-Datei")
        parser.add_argument("--create-exams", action="store_true", help="Unbekannte Prüfungen automatisch anlegen")
        parser.add_argument("--pending", action="store_true", help="Als „wartet auf Freigabe“ importieren")
        parser.add_argument("--dry-run", action="store_true", help="Nur testen, nichts speichern")

    def handle(self, *args, **options):
        path = Path(options["pfad"]).expanduser()
        if not path.exists():
            raise CommandError(f"{path} existiert nicht.")
        kwargs = {
            "site": SiteSettings.get(),
            "create_exams": options["create_exams"],
            "status": Protocol.STATUS_PENDING if options["pending"] else Protocol.STATUS_PUBLISHED,
            "dry_run": options["dry_run"],
        }
        if path.is_file() and path.suffix.lower() == ".zip":
            report = importer.import_zip(str(path), **kwargs)
        elif path.is_dir():
            report = importer.import_directory(path, **kwargs)
        else:
            raise CommandError("Bitte einen Ordner oder eine .zip-Datei angeben.")

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Testlauf – es wurde nichts gespeichert."))
        self.stdout.write(self.style.SUCCESS(report.summary()))
        if report.created_exams:
            self.stdout.write("Neue Prüfungen: " + ", ".join(report.created_exams))
        if report.created_examiners:
            self.stdout.write("Neue Prüfer: " + ", ".join(report.created_examiners))
        for location, message in report.errors:
            self.stdout.write(self.style.ERROR(f"  {location}: {message}"))
