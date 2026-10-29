"""Hilfsfunktionen für die Tests."""
import datetime

from django.core.cache import cache
from django.core.files.base import ContentFile
from django.test import TestCase

from accounts.models import User
from core.models import SiteSettings
from core.pdf import render_text_pdf
from payments.models import Purchase
from protocols.models import Exam, Examiner, Protocol, Subject

LONG_TEXT = (
    "Prüfungsfragen: Plexus brachialis, Herzentwicklung, Leistenkanal und Histologie der Leber. "
    "Die Atmosphäre war freundlich, die Prüferin hat bei Unsicherheiten nachgeholfen. "
    "Wichtig war vor allem, die Strukturen am Präparat sicher zu zeigen und klinische Bezüge herzustellen."
)


class BaseTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.site = SiteSettings.get()
        self.exam = Exam.objects.create(code="M1", name="Physikum (M1)")
        self.subject = Subject.objects.create(exam=self.exam, name="Anatomie")
        self.examiners = [
            Examiner.objects.create(exam=self.exam, subject=self.subject, name=f"Prof. Dr. Test {i}") for i in range(5)
        ]
        self.protocols = [make_protocol(e) for e in self.examiners]
        self.student = make_user("student@uni-beispiel.de")
        self.admin = User.objects.create_superuser("admin@uni-beispiel.de", "Admin123!xy", name="Admin")

    def login(self, user=None):
        self.client.force_login(user or self.student)


def make_user(email, verified=True, password="SehrGeheim!42", **extra):
    return User.objects.create_user(email=email, password=password, name="Test Person", email_verified=verified, **extra)


def unique_text(seed):
    """Ein eigenständiger Protokolltext (für Upload-Tests – Kopien werden abgelehnt)."""
    topics = ["Niere", "Leber", "Herz", "Lunge", "Gehirn", "Milz", "Magen", "Haut", "Auge", "Ohr", "Knochen", "Muskel"]
    words = [f"{topics[(seed + i) % len(topics)]}{seed}x{i}" for i in range(40)]
    return f"Eigenes Protokoll Nummer {seed}: " + " ".join(words) + " – die Prüfung war fair und gut machbar."


def make_protocol(examiner, with_file=False, **extra):
    file_body = extra.pop("file_body", LONG_TEXT)
    protocol = Protocol(
        examiner=examiner,
        exam_date=extra.pop("exam_date", datetime.date(2025, 3, 12)),
        content=extra.pop("content", LONG_TEXT),
        status=extra.pop("status", Protocol.STATUS_PUBLISHED),
        source=extra.pop("source", Protocol.SOURCE_ADMIN),
        **extra,
    )
    if with_file:
        from protocols.services import attach_file

        pdf = render_text_pdf("Test", ["Meta"], file_body)
        attach_file(protocol, ContentFile(pdf, name="test.pdf"))
    protocol.save()
    return protocol


def make_paid_purchase(user, exam, examiners, provider=Purchase.PROVIDER_SIMULATION, amount=3000, **extra):
    from django.utils import timezone

    purchase = Purchase.objects.create(
        user=user,
        email=user.email,
        exam=exam,
        amount_cents=amount,
        provider=provider,
        status=Purchase.STATUS_PAID,
        paid_at=timezone.now(),
        **extra,
    )
    purchase.examiners.set(examiners)
    return purchase
