import datetime
import os
import secrets

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import User
from core.demo_data import EXAMS
from core.models import SiteSettings
from core.pdf import render_text_pdf
from payments.models import Purchase
from payments.services import mark_paid
from protocols.models import Exam, Examiner, Protocol, Subject
from protocols.services import attach_file


class Command(BaseCommand):
    help = "Legt Beispieldaten an: M1, M2, M3 mit Testprüfern und je zwei Protokollen (nur, solange es noch keine Prüfungen gibt)."

    def add_arguments(self, parser):
        parser.add_argument("--ohne-nutzer", action="store_true", help="Keine Demo-Konten anlegen.")
        parser.add_argument(
            "--force", action="store_true", help="Auch anlegen, wenn es schon Prüfungen gibt (fehlende Teile ergänzen)."
        )

    @transaction.atomic
    def handle(self, *args, **options):
        site = SiteSettings.get()
        if Exam.objects.exists() and not options["force"]:
            # Wichtig für Docker (DEMO_DATA=1): gelöschte Beispieldaten sollen beim Neustart nicht wiederkommen.
            self.stdout.write("Es gibt bereits Prüfungen – Beispieldaten werden nicht angelegt.")
            return
        created_protocols = 0
        for exam_index, data in enumerate(EXAMS):
            exam, _ = Exam.objects.get_or_create(
                code=data["code"],
                defaults={"name": data["name"], "description": data["description"], "sort_order": exam_index},
            )
            subjects = {}
            for subject_index, name in enumerate(data["subjects"]):
                subjects[name], _ = Subject.objects.get_or_create(
                    exam=exam, name=name, defaults={"sort_order": subject_index}
                )
            for examiner_data in data["examiners"]:
                examiner, _ = Examiner.objects.get_or_create(
                    exam=exam,
                    name=examiner_data["name"],
                    defaults={
                        "subject": subjects.get(examiner_data["subject"]),
                        "institute": examiner_data["institute"],
                        "description": examiner_data["description"],
                    },
                )
                if examiner.protocols.exists():
                    continue
                for index, (day, grade, text) in enumerate(examiner_data["protocols"]):
                    exam_date = datetime.date.fromisoformat(day)
                    protocol = Protocol(
                        examiner=examiner,
                        exam_date=exam_date,
                        grade=grade,
                        status=Protocol.STATUS_PUBLISHED,
                        source=Protocol.SOURCE_DEMO,
                    )
                    if index == 0:
                        protocol.content = text
                    else:
                        # Zweites Protokoll als PDF-Datei – so sieht man beide Varianten.
                        pdf = render_text_pdf(
                            f"Gedächtnisprotokoll {exam.code} – {examiner.name}",
                            [f"Prüfung am {exam_date:%d.%m.%Y}", f"Note: {grade}"],
                            text,
                            footer_text="Beispielprotokoll – frei erfunden",
                        )
                        filename = f"protokoll-{exam.code.lower()}-{examiner.pk}-{day}.pdf"
                        attach_file(protocol, ContentFile(pdf, name=filename))
                    protocol.save()
                    created_protocols += 1

        self.stdout.write(self.style.SUCCESS(f"Beispieldaten bereit ({created_protocols} Protokolle neu angelegt)."))

        if options["ohne_nutzer"]:
            return
        self._demo_users(site)

    def _password(self, fixed):
        # Feste, bekannte Passwörter nur bei der lokalen Entwicklung – im Betrieb zufällig.
        return fixed if settings.DEBUG else secrets.token_urlsafe(12)

    def _demo_users(self, site):
        if not User.objects.filter(is_staff=True).exists():
            admin_email = os.environ.get("ADMIN_EMAIL", "admin@uni-beispiel.de").lower()
            admin_password = os.environ.get("ADMIN_PASSWORD") or self._password("Admin123!")
            User.objects.create_superuser(email=admin_email, password=admin_password, name="Fachschaft Admin")
            self.stdout.write(f"Admin-Konto: {admin_email} / {admin_password}")

        if not site.is_simulation:
            self.stdout.write("Zahlungsmodus ist nicht „Simulation“ – kein Demo-Konto für Studierende angelegt.")
            return
        student_email = "student@uni-beispiel.de"
        if not User.objects.filter(email=student_email).exists():
            student_password = self._password("Student123!")
            student = User.objects.create_user(
                email=student_email, password=student_password, name="Erika Studentin", email_verified=True
            )
            m1 = Exam.objects.filter(code="M1").first()
            if m1:
                purchase = Purchase.objects.create(
                    user=student,
                    email=student.email,
                    exam=m1,
                    amount_cents=m1.price_cents(SiteSettings.get()),
                    provider=Purchase.PROVIDER_SIMULATION,
                )
                purchase.examiners.set(m1.examiners.filter(name__in=["Prof. Dr. Anna Beispiel", "Prof. Dr. Max Mustermann"]))
                mark_paid(purchase, note="Demo-Daten")
            self.stdout.write(
                f"Demo-Studentin: {student_email} / {student_password} (hat ein Test-Paket für M1 mit 2 Prüfern)"
            )
