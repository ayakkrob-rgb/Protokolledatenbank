from django.urls import reverse

from accounts.models import User
from core.models import AuditLog, SiteSettings
from core.testing import BaseTestCase, make_paid_purchase, make_protocol
from payments.models import Purchase
from protocols.models import Examiner, Protocol


class AdminAccessTests(BaseTestCase):
    def admin_urls(self):
        purchase = make_paid_purchase(self.student, self.exam, self.examiners[:1])
        return [
            reverse("verwaltung:dashboard"),
            reverse("verwaltung:exams"),
            reverse("verwaltung:exam_create"),
            reverse("verwaltung:exam_edit", args=[self.exam.pk]),
            reverse("verwaltung:examiners"),
            reverse("verwaltung:examiners") + "?status=leer&pruefung=%d&q=Test" % self.exam.pk,
            reverse("verwaltung:examiner_create"),
            reverse("verwaltung:examiner_edit", args=[self.examiners[0].pk]),
            reverse("verwaltung:protocols"),
            reverse("verwaltung:protocols") + "?status=pending&herkunft=upload&q=Plexus",
            reverse("verwaltung:protocol_create"),
            reverse("verwaltung:protocol_edit", args=[self.protocols[0].pk]),
            reverse("verwaltung:moderation"),
            reverse("verwaltung:import"),
            reverse("verwaltung:users"),
            reverse("verwaltung:user_create"),
            reverse("verwaltung:user_detail", args=[self.student.pk]),
            reverse("verwaltung:purchases"),
            reverse("verwaltung:purchases") + "?erstattung=offen&q=P-0001",
            reverse("verwaltung:purchase_detail", args=[purchase.pk]),
            reverse("verwaltung:purchase_export"),
            reverse("verwaltung:settings"),
            reverse("verwaltung:emails"),
            reverse("verwaltung:audit"),
        ]

    def test_all_admin_pages_load(self):
        self.login(self.admin)
        for url in self.admin_urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_students_are_locked_out(self):
        self.login()
        for url in self.admin_urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(reverse("verwaltung:dashboard"))
        self.assertEqual(response.status_code, 302)


class AdminActionTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.login(self.admin)

    def test_create_exam_and_subject(self):
        response = self.client.post(
            reverse("verwaltung:exam_create"), {"code": "M4", "name": "Testprüfung", "sort_order": 5, "is_active": "on"}
        )
        exam = self.exam.__class__.objects.get(code="M4")
        self.assertRedirects(response, reverse("verwaltung:exam_edit", args=[exam.pk]))
        self.assertEqual(exam.slug, "m4")
        self.client.post(reverse("verwaltung:subject_add", args=[exam.pk]), {"name": "Innere", "sort_order": 0})
        self.assertEqual(exam.subjects.get().name, "Innere")

    def test_exam_with_examiners_cannot_be_deleted(self):
        self.client.post(reverse("verwaltung:exam_delete", args=[self.exam.pk]))
        self.assertTrue(self.exam.__class__.objects.filter(pk=self.exam.pk).exists())

    def test_examiner_duplicate_detection(self):
        response = self.client.post(
            reverse("verwaltung:examiner_create"), {"exam": self.exam.pk, "name": "Test 0", "is_active": "on"}
        )
        self.assertContains(response, "Zusammenführen")

    def test_merge_examiners(self):
        source, target = self.examiners[0], self.examiners[1]
        purchase = make_paid_purchase(self.student, self.exam, [source])
        response = self.client.post(reverse("verwaltung:examiner_merge", args=[source.pk]), {"target": target.pk})
        self.assertRedirects(response, reverse("verwaltung:examiner_edit", args=[target.pk]))
        self.assertFalse(Examiner.objects.filter(pk=source.pk).exists())
        self.assertEqual(target.protocols.count(), 2)
        self.assertEqual(list(purchase.examiners.all()), [target])

    def test_admin_creates_protocol(self):
        response = self.client.post(
            reverse("verwaltung:protocol_create"),
            {"examiner": self.examiners[0].pk, "content": "Neuer Text", "status": "published", "exam_date": "2024-02-02"},
        )
        protocol = Protocol.objects.get(content="Neuer Text")
        self.assertRedirects(response, reverse("verwaltung:protocol_edit", args=[protocol.pk]))
        self.assertEqual(protocol.source, Protocol.SOURCE_ADMIN)
        self.assertEqual(protocol.exam_period, "Frühjahr 2024")

    def test_bulk_publish_and_delete(self):
        pending = [make_protocol(self.examiners[0], status=Protocol.STATUS_PENDING) for _ in range(2)]
        self.client.post(reverse("verwaltung:protocol_bulk"), {"ids": [p.pk for p in pending], "action": "publish"})
        self.assertFalse(Protocol.objects.filter(status=Protocol.STATUS_PENDING).exists())
        self.client.post(reverse("verwaltung:protocol_bulk"), {"ids": [p.pk for p in pending], "action": "delete"})
        self.assertFalse(Protocol.objects.filter(pk__in=[p.pk for p in pending]).exists())

    def test_settings_keep_secrets_when_left_blank(self):
        site = SiteSettings.get()
        site.stripe_secret_key = "sk_test_geheim"
        site.save()
        response = self.client.get(reverse("verwaltung:settings"))
        self.assertNotContains(response, "sk_test_geheim")
        data = {
            field: value for field, value in self._settings_post_data(site).items()
        }
        data.update({"payment_mode": "stripe", "stripe_secret_key": "", "price": "25.00", "refund_amount": "24.00"})
        response = self.client.post(reverse("verwaltung:settings"), data)
        self.assertEqual(response.status_code, 302)
        site.refresh_from_db()
        self.assertEqual(site.stripe_secret_key, "sk_test_geheim")
        self.assertEqual(site.payment_mode, "stripe")
        self.assertEqual(str(site.price), "25.00")
        self.assertTrue(AuditLog.objects.filter(action="einstellungen.zahlungsmodus").exists())

    def test_settings_validation(self):
        data = self._settings_post_data(SiteSettings.get())
        data.update({"payment_mode": "stripe", "stripe_secret_key": "pk_test_falsch", "refund_amount": "40"})
        response = self.client.post(reverse("verwaltung:settings"), data)
        self.assertContains(response, "öffentliche Schlüssel")
        self.assertContains(response, "nicht höher als der Preis")

    def _settings_post_data(self, site):
        from verwaltung.forms import SettingsForm

        form = SettingsForm(instance=site)
        data = {}
        for name, field in form.fields.items():
            value = form.initial.get(name, field.initial)
            if isinstance(value, bool):
                if value:
                    data[name] = "on"
            elif value is not None:
                data[name] = value
        return data

    def test_grant_package_manually(self):
        self.client.post(
            reverse("verwaltung:user_detail", args=[self.student.pk]),
            {"action": "grant", "exam": self.exam.pk, "examiners": [self.examiners[0].pk], "amount": "0", "note": "Kulanz"},
        )
        purchase = Purchase.objects.get(user=self.student)
        self.assertTrue(purchase.is_paid)
        self.assertEqual(purchase.provider, Purchase.PROVIDER_MANUAL)

    def test_admin_cannot_demote_self(self):
        self.client.post(
            reverse("verwaltung:user_detail", args=[self.admin.pk]),
            {"action": "save", "name": "Admin", "email": self.admin.email, "is_active": "on", "email_verified": "on"},
        )
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_staff)

    def test_create_admin_account_sends_invitation(self):
        self.client.post(
            reverse("verwaltung:user_create"), {"name": "Neue Admin", "email": "neu@uni-beispiel.de", "is_staff": "on"}
        )
        user = User.objects.get(email="neu@uni-beispiel.de")
        self.assertTrue(user.is_staff)
        self.assertFalse(user.has_usable_password())

    def test_purchase_actions(self):
        purchase = Purchase.objects.create(
            user=self.student, email=self.student.email, exam=self.exam, amount_cents=3000,
            provider=Purchase.PROVIDER_SIMULATION,
        )
        purchase.examiners.set(self.examiners[:1])
        url = reverse("verwaltung:purchase_detail", args=[purchase.pk])
        self.client.post(url, {"action": "mark_paid"})
        purchase.refresh_from_db()
        self.assertTrue(purchase.is_paid)
        self.client.post(url, {"action": "revoke"})
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, Purchase.STATUS_REVOKED)
        self.client.post(url, {"action": "restore"})
        self.client.post(url, {"action": "refund_full"})
        purchase.refresh_from_db()
        self.assertEqual(purchase.refunded_cents, 3000)
        self.assertEqual(purchase.status, Purchase.STATUS_REVOKED)

    def test_revoke_simulated_packages(self):
        simulated = make_paid_purchase(self.student, self.exam, self.examiners[:1])
        real = make_paid_purchase(self.student, self.exam, self.examiners[1:2], provider=Purchase.PROVIDER_STRIPE)
        self.client.post(reverse("verwaltung:revoke_simulated"))
        simulated.refresh_from_db()
        real.refresh_from_db()
        self.assertEqual(simulated.status, Purchase.STATUS_REVOKED)
        self.assertEqual(real.status, Purchase.STATUS_PAID)

    def test_csv_export(self):
        make_paid_purchase(self.student, self.exam, self.examiners[:2])
        response = self.client.get(reverse("verwaltung:purchase_export"))
        content = response.content.decode("utf-8-sig")
        self.assertIn("Nummer;Erstellt", content)
        self.assertIn("student@uni-beispiel.de", content)
        self.assertIn("30,00", content)
