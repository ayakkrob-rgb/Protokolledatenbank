import io

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from core.models import SiteSettings
from core.pdf import render_text_pdf, stamp_pdf, wrap_text
from core.utils import format_eur, to_cents
from protocols.models import Exam, Examiner, Protocol


class UtilTests(TestCase):
    def test_money(self):
        self.assertEqual(format_eur(3000), "30,00 €")
        self.assertEqual(format_eur(123456), "1.234,56 €")
        self.assertEqual(format_eur(-2900), "-29,00 €")
        self.assertEqual(to_cents("29.99"), 2999)

    def test_domains(self):
        site = SiteSettings.get()
        site.allowed_email_domains = "uni-musterstadt.de\n@stud.andere-uni.de"
        self.assertTrue(site.email_domain_allowed("a@uni-musterstadt.de"))
        self.assertTrue(site.email_domain_allowed("a@stud.uni-musterstadt.de"))
        self.assertTrue(site.email_domain_allowed("a@stud.andere-uni.de"))
        self.assertFalse(site.email_domain_allowed("a@andere-uni.de"))
        self.assertFalse(site.email_domain_allowed("a@xuni-musterstadt.de"))
        site.allowed_email_domains = ""
        self.assertTrue(site.email_domain_allowed("a@gmail.com"))


class PdfTests(TestCase):
    def test_wrap_text(self):
        lines = wrap_text("Wort " * 100, 10, 200)
        self.assertGreater(len(lines), 5)
        self.assertTrue(all(len(line) < 60 for line in lines))

    def test_multi_page_pdf_with_umlauts(self):
        from pypdf import PdfReader

        data = render_text_pdf("Prüfung α", ["Meta"], "Größere Übung mit ß und €.\n" * 200, footer_text="Fußzeile")
        reader = PdfReader(io.BytesIO(data))
        self.assertGreater(len(reader.pages), 2)
        text = reader.pages[0].extract_text()
        self.assertIn("Größere Übung mit ß und €", text)
        self.assertIn("Prüfung alpha", text)

    def test_stamp_keeps_broken_files(self):
        self.assertEqual(stamp_pdf(b"kein pdf", "x"), b"kein pdf")


class PageTests(TestCase):
    def test_public_pages(self):
        for name in ["core:home", "core:faq", "core:imprint", "core:privacy", "core:terms", "protocols:exam_list"]:
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertIn("Content-Security-Policy", response)

    def test_simulation_banner(self):
        self.assertContains(self.client.get("/"), "Testbetrieb")
        site = SiteSettings.get()
        site.payment_mode = SiteSettings.PAYMENT_STRIPE
        site.save()
        self.assertNotContains(self.client.get("/"), "Testbetrieb")

    def test_404_page(self):
        response = self.client.get("/gibt-es-nicht/")
        self.assertEqual(response.status_code, 404)


class SeedTests(TestCase):
    def test_seed_demo_is_idempotent(self):
        call_command("seed_demo", verbosity=0, stdout=io.StringIO())
        call_command("seed_demo", verbosity=0, stdout=io.StringIO())
        self.assertEqual(Exam.objects.count(), 3)
        for exam in Exam.objects.all():
            with self.subTest(exam=exam.code):
                count = Examiner.objects.filter(exam=exam).count()
                self.assertTrue(3 <= count <= 4)
        self.assertEqual(Protocol.objects.count(), Examiner.objects.count() * 2)
        self.assertTrue(Protocol.objects.exclude(file="").exists())
        self.assertTrue(Protocol.objects.exclude(file_text="").exists())

    def test_seed_does_not_return_after_deletion(self):
        call_command("seed_demo", verbosity=0, stdout=io.StringIO())
        Exam.objects.filter(code="M2").update(is_active=False)
        Protocol.objects.all().delete()
        call_command("seed_demo", verbosity=0, stdout=io.StringIO())
        self.assertFalse(Protocol.objects.exists())

    def test_no_demo_student_in_stripe_mode(self):
        from accounts.models import User

        site = SiteSettings.get()
        site.payment_mode = SiteSettings.PAYMENT_STRIPE
        site.save()
        call_command("seed_demo", verbosity=0, stdout=io.StringIO())
        self.assertFalse(User.objects.filter(email="student@uni-beispiel.de").exists())
        admin = User.objects.get(is_staff=True)
        self.assertFalse(admin.check_password("Admin123!"))  # kein bekanntes Passwort außerhalb von DEBUG
