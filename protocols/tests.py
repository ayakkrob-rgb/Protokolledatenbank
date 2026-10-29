import io
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from core.pdf import render_text_pdf
from core.testing import LONG_TEXT, BaseTestCase, make_paid_purchase, make_protocol, make_user
from payments.models import Purchase

from .importer import import_zip, parse_date_info
from .models import Examiner, Protocol, normalize_person_name


class NameNormalizationTests(BaseTestCase):
    def test_titles_and_case_are_ignored(self):
        self.assertEqual(normalize_person_name("Prof. Dr. med. Anna  Müller"), "anna müller")
        self.assertEqual(normalize_person_name("anna müller"), "anna müller")
        self.assertEqual(normalize_person_name("PD Dr. rer. nat. Anna Müller"), "anna müller")


class AccessTests(BaseTestCase):
    def test_catalog_requires_login(self):
        response = self.client.get(self.exam.get_absolute_url())
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])

    def test_locked_protocol_redirects_to_examiner(self):
        self.login()
        protocol = self.protocols[0]
        response = self.client.get(protocol.get_absolute_url())
        self.assertRedirects(response, protocol.examiner.get_absolute_url())
        self.assertEqual(self.client.get(reverse("protocols:protocol_text_pdf", args=[protocol.pk])).status_code, 404)

    def test_purchased_examiner_is_readable(self):
        make_paid_purchase(self.student, self.exam, self.examiners[:2])
        self.login()
        response = self.client.get(self.protocols[0].get_absolute_url())
        self.assertContains(response, "Plexus brachialis")
        # anderer Prüfer bleibt gesperrt
        response = self.client.get(self.protocols[3].get_absolute_url())
        self.assertEqual(response.status_code, 302)

    def test_revoked_or_expired_purchase_gives_no_access(self):
        from django.utils import timezone

        purchase = make_paid_purchase(self.student, self.exam, self.examiners[:1])
        purchase.status = Purchase.STATUS_REVOKED
        purchase.save()
        self.login()
        self.assertEqual(self.client.get(self.protocols[0].get_absolute_url()).status_code, 302)
        purchase.status = Purchase.STATUS_PAID
        purchase.expires_at = timezone.now() - timezone.timedelta(days=1)
        purchase.save()
        self.assertEqual(self.client.get(self.protocols[0].get_absolute_url()).status_code, 302)

    def test_pending_protocols_are_hidden_even_with_purchase(self):
        pending = make_protocol(self.examiners[0], status=Protocol.STATUS_PENDING)
        make_paid_purchase(self.student, self.exam, self.examiners[:1])
        self.login()
        self.assertEqual(self.client.get(pending.get_absolute_url()).status_code, 404)

    def test_pdf_download_is_watermarked(self):
        from pypdf import PdfReader

        protocol = make_protocol(self.examiners[0], with_file=True)
        make_paid_purchase(self.student, self.exam, self.examiners[:1])
        self.login()
        response = self.client.get(reverse("protocols:protocol_file", args=[protocol.pk]))
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("attachment", response["Content-Disposition"])
        text = PdfReader(io.BytesIO(response.content)).pages[0].extract_text()
        self.assertIn("student@uni-beispiel.de", text)
        protocol.refresh_from_db()
        self.assertEqual(protocol.download_count, 1)

    def test_text_protocol_as_pdf(self):
        make_paid_purchase(self.student, self.exam, self.examiners[:1])
        self.login()
        response = self.client.get(reverse("protocols:protocol_text_pdf", args=[self.protocols[0].pk]))
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_inline_view_only_for_safe_types(self):
        protocol = make_protocol(self.examiners[0], with_file=True)
        self.login(self.admin)
        response = self.client.get(reverse("protocols:protocol_file", args=[protocol.pk]) + "?ansehen=1")
        self.assertTrue(response["Content-Disposition"].startswith("inline"))

    def test_staff_sees_everything(self):
        self.login(self.admin)
        self.assertEqual(self.client.get(self.protocols[4].get_absolute_url()).status_code, 200)


class UploadTests(BaseTestCase):
    def upload_data(self, sections, **extra):
        data = {
            "exam_date": "2025-08-26",
            "grade": "2",
            "confirm_own": "on",
            "confirm_rights": "on",
            "s-TOTAL_FORMS": str(len(sections)),
            "s-INITIAL_FORMS": "0",
            "s-MIN_NUM_FORMS": "1",
            "s-MAX_NUM_FORMS": "4",
        }
        for index, section in enumerate(sections):
            for key, value in section.items():
                data[f"s-{index}-{key}"] = value
        data.update(extra)
        return data

    def test_upload_with_existing_and_new_examiner(self):
        self.login()
        pdf = render_text_pdf("Upload", [], LONG_TEXT)
        data = self.upload_data(
            [
                {"examiner": str(self.examiners[0].pk), "content": LONG_TEXT},
                {"examiner": "new", "new_name": "Dr. Neu Prüfer", "new_subject": str(self.subject.pk),
                 "file": SimpleUploadedFile("protokoll.pdf", pdf, content_type="application/pdf")},
            ]
        )
        response = self.client.post(reverse("protocols:upload", args=[self.exam.slug]), data)
        self.assertEqual(response.status_code, 302, response.content.decode()[:3000] if response.status_code != 302 else "")
        new_examiner = Examiner.objects.get(name="Dr. Neu Prüfer")
        self.assertTrue(new_examiner.created_via_upload)
        self.assertEqual(new_examiner.subject, self.subject)
        uploads = Protocol.objects.filter(uploaded_by=self.student)
        self.assertEqual(uploads.count(), 2)
        self.assertTrue(all(p.status == Protocol.STATUS_PUBLISHED for p in uploads))
        self.assertEqual(len({p.submission_key for p in uploads}), 1)
        self.assertTrue(uploads.get(examiner=new_examiner).file)

    def test_existing_examiner_is_reused_despite_other_spelling(self):
        self.login()
        data = self.upload_data([{"examiner": "new", "new_name": "test 1", "content": LONG_TEXT}])
        self.client.post(reverse("protocols:upload", args=[self.exam.slug]), data)
        self.assertEqual(Examiner.objects.filter(name_key="test 1").count(), 1)
        self.assertEqual(self.examiners[1].protocols.filter(uploaded_by=self.student).count(), 1)

    def test_too_short_text_is_rejected(self):
        self.login()
        data = self.upload_data([{"examiner": str(self.examiners[0].pk), "content": "Zu kurz"}])
        response = self.client.post(reverse("protocols:upload", args=[self.exam.slug]), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ausführlicher")
        self.assertFalse(Protocol.objects.filter(uploaded_by=self.student).exists())

    def test_fake_pdf_is_rejected(self):
        self.login()
        data = self.upload_data(
            [{"examiner": str(self.examiners[0].pk), "file": SimpleUploadedFile("x.pdf", b"<html>nope</html>")}]
        )
        response = self.client.post(reverse("protocols:upload", args=[self.exam.slug]), data)
        self.assertContains(response, "keine gültige .pdf-Datei")

    def test_disallowed_extension(self):
        self.login()
        data = self.upload_data(
            [{"examiner": str(self.examiners[0].pk), "file": SimpleUploadedFile("x.exe", b"MZ....")}]
        )
        response = self.client.post(reverse("protocols:upload", args=[self.exam.slug]), data)
        self.assertContains(response, "nicht erlaubt")

    def test_duplicate_examiner_in_one_upload(self):
        self.login()
        section = {"examiner": str(self.examiners[0].pk), "content": LONG_TEXT}
        response = self.client.post(reverse("protocols:upload", args=[self.exam.slug]), self.upload_data([section, section]))
        self.assertContains(response, "nur einmal")

    def test_future_date_rejected(self):
        self.login()
        data = self.upload_data([{"examiner": str(self.examiners[0].pk), "content": LONG_TEXT}], exam_date="2999-01-01")
        response = self.client.post(reverse("protocols:upload", args=[self.exam.slug]), data)
        self.assertContains(response, "Zukunft")

    def test_new_examiners_can_be_disabled(self):
        self.site.allow_new_examiners = False
        self.site.save()
        self.login()
        data = self.upload_data([{"examiner": "new", "new_name": "Dr. Unbekannt", "content": LONG_TEXT}])
        response = self.client.post(reverse("protocols:upload", args=[self.exam.slug]), data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Examiner.objects.filter(name="Dr. Unbekannt").exists())

    def test_moderation_mode(self):
        self.site.require_upload_approval = True
        self.site.save()
        self.login()
        data = self.upload_data([{"examiner": "new", "new_name": "Dr. Moderiert", "content": LONG_TEXT}])
        self.client.post(reverse("protocols:upload", args=[self.exam.slug]), data)
        protocol = Protocol.objects.get(uploaded_by=self.student)
        self.assertEqual(protocol.status, Protocol.STATUS_PENDING)
        self.assertFalse(protocol.examiner.is_active)
        # Uploader sieht das eigene Protokoll, andere nicht
        self.assertEqual(self.client.get(protocol.get_absolute_url()).status_code, 200)
        other = make_user("other@uni-beispiel.de")
        self.client.force_login(other)
        self.assertEqual(self.client.get(protocol.get_absolute_url()).status_code, 404)


class ImporterTests(BaseTestCase):
    def test_parse_date_info(self):
        self.assertEqual(str(parse_date_info("2023-08-24 Protokoll.pdf")[0]), "2023-08-24")
        self.assertEqual(str(parse_date_info("Protokoll 24.08.2023.pdf")[0]), "2023-08-24")
        self.assertEqual(parse_date_info("Herbst 2019.docx"), (None, "Herbst 2019"))
        self.assertEqual(parse_date_info("WiSe 22-23 Prüfung.pdf"), (None, "WiSe 2022"))
        self.assertEqual(parse_date_info("protokoll.pdf"), (None, ""))

    def build_zip(self):
        buffer = io.BytesIO()
        pdf = render_text_pdf("Alt", [], LONG_TEXT)
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("Archiv/M1/Anatomie/Prof. Dr. Alt Bestand/2019-03-01 Protokoll.pdf", pdf)
            archive.writestr("Archiv/M1/Biochemie/Dr. Neu Import/Herbst 2020.txt", LONG_TEXT.encode("cp1252"))
            archive.writestr("Archiv/M1/Prof. Dr. Test 0/protokoll.pdf", pdf)
            archive.writestr("Archiv/M9/Irgendwer/x.pdf", pdf)
            archive.writestr("Archiv/M1/Anatomie/Prof. Dr. Alt Bestand/virus.exe", b"MZ")
            archive.writestr("../ausbruch.pdf", pdf)
            archive.writestr("__MACOSX/._x", b"")
        buffer.seek(0)
        return buffer

    def test_zip_import(self):
        report = import_zip(self.build_zip(), site=self.site, actor=self.admin)
        self.assertEqual(report.imported, 3)
        self.assertTrue(Examiner.objects.filter(name="Prof. Dr. Alt Bestand", subject__name="Anatomie").exists())
        imported_txt = Protocol.objects.get(examiner__name="Dr. Neu Import")
        self.assertIn("Plexus", imported_txt.content)
        self.assertEqual(imported_txt.exam_period, "Herbst 2020")
        self.assertEqual(Protocol.objects.get(examiner__name="Prof. Dr. Alt Bestand").exam_date.isoformat(), "2019-03-01")
        self.assertEqual(self.examiners[0].protocols.count(), 2)  # vorhandener Prüfer wiederverwendet
        self.assertEqual(len(report.errors), 2)  # M9 unbekannt, .exe nicht erlaubt
        # Zweiter Lauf: nichts doppelt
        report = import_zip(self.build_zip(), site=self.site)
        self.assertEqual(report.imported, 0)
        self.assertEqual(report.skipped, 3)

    def test_dry_run_saves_nothing(self):
        before = Protocol.objects.count()
        report = import_zip(self.build_zip(), site=self.site, dry_run=True)
        self.assertEqual(report.imported, 3)
        self.assertEqual(Protocol.objects.count(), before)

    def test_admin_upload_view(self):
        self.login(self.admin)
        response = self.client.post(
            reverse("verwaltung:import"),
            {"archive": SimpleUploadedFile("a.zip", self.build_zip().read()), "status": "published"},
        )
        self.assertContains(response, "3 Protokolle importiert")
