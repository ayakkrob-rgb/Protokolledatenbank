import re

from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import EmailLog, SiteSettings

from .models import User


class RegistrationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.site = SiteSettings.get()

    def register(self, email, password="SehrGeheim!42"):
        return self.client.post(
            reverse("accounts:register"),
            {"name": "Erika Test", "email": email, "password1": password, "password2": password, "accept_terms": "on"},
        )

    def test_only_university_domains(self):
        response = self.register("erika@gmail.com")
        self.assertContains(response, "studentische E-Mail-Adresse")
        self.assertFalse(User.objects.exists())

    def test_subdomains_are_allowed(self):
        response = self.register("erika@stud.uni-beispiel.de")
        self.assertRedirects(response, reverse("accounts:register_done"))
        self.assertTrue(User.objects.filter(email="erika@stud.uni-beispiel.de").exists())

    def test_lookalike_domain_is_rejected(self):
        self.register("erika@fake-uni-beispiel.de")
        self.assertFalse(User.objects.exists())

    def test_verification_flow(self):
        self.register("Erika@Uni-Beispiel.de")
        user = User.objects.get()
        self.assertEqual(user.email, "erika@uni-beispiel.de")
        self.assertFalse(user.email_verified)

        log = EmailLog.objects.get(kind="verification")
        self.assertEqual(log.status, EmailLog.STATUS_SIMULATED)
        link = re.search(r"https?://\S+", log.body).group(0)

        # Ohne Bestätigung keine Anmeldung
        response = self.client.post(
            reverse("accounts:login"), {"email": "erika@uni-beispiel.de", "password": "SehrGeheim!42"}
        )
        self.assertContains(response, "noch nicht bestätigt")
        self.assertNotIn("_auth_user_id", self.client.session)

        path = link.split("testserver", 1)[-1]
        response = self.client.get(path)
        self.assertRedirects(response, reverse("core:dashboard"))
        user.refresh_from_db()
        self.assertTrue(user.email_verified)
        # Link ist danach verbraucht
        self.client.logout()
        response = self.client.get(path)
        self.assertRedirects(response, reverse("accounts:login"))

    @override_settings(DEBUG=True)
    def test_simulated_link_is_shown_in_development(self):
        self.register("erika@uni-beispiel.de")
        response = self.client.get(reverse("accounts:register_done"))
        self.assertContains(response, "/konto/bestaetigen/")

    def test_simulated_links_are_never_shown_in_production(self):
        self.register("erika@uni-beispiel.de")
        response = self.client.get(reverse("accounts:register_done"))
        self.assertNotContains(response, "/konto/bestaetigen/")
        self.assertContains(response, "Postausgang")
        # Passwort-Link eines fremden Kontos darf nicht auf der Seite landen
        User.objects.create_superuser("chef@uni-beispiel.de", "Geheim!12345", name="Chef")
        response = self.client.post(reverse("accounts:password_reset"), {"email": "chef@uni-beispiel.de"})
        self.assertNotContains(response, "/konto/passwort-neu/")
        response = self.client.post(reverse("accounts:resend_verification"), {"email": "erika@uni-beispiel.de"})
        response = self.client.get(reverse("accounts:register_done"))
        self.assertNotContains(response, "/konto/bestaetigen/")

    def test_real_mail_mode_sends_via_smtp_backend(self):
        self.site.email_mode = SiteSettings.EMAIL_SMTP
        self.site.smtp_host = "smtp.example.org"
        self.site.save()
        self.register("erika@uni-beispiel.de")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("bestätige", mail.outbox[0].body)
        response = self.client.get(reverse("accounts:register_done"))
        self.assertNotContains(response, "/konto/bestaetigen/")

    def test_registration_can_be_closed(self):
        self.site.registration_open = False
        self.site.save()
        response = self.register("erika@uni-beispiel.de")
        self.assertContains(response, "geschlossen")
        self.assertFalse(User.objects.exists())

    def test_invalid_token(self):
        user = User.objects.create_user("a@uni-beispiel.de", "SehrGeheim!42", name="A")
        from .tokens import encode_uid

        response = self.client.get(reverse("accounts:verify", args=[encode_uid(user), "falsch-123"]))
        self.assertEqual(response.status_code, 400)


class LoginAndPasswordTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            "max@uni-beispiel.de", "SehrGeheim!42", name="Max", email_verified=True
        )

    def test_login_is_case_insensitive(self):
        response = self.client.post(reverse("accounts:login"), {"email": "MAX@uni-beispiel.de", "password": "SehrGeheim!42"})
        self.assertRedirects(response, reverse("core:dashboard"))

    def test_wrong_password(self):
        response = self.client.post(reverse("accounts:login"), {"email": "max@uni-beispiel.de", "password": "falsch"})
        self.assertContains(response, "falsch")

    def test_rate_limit(self):
        for _ in range(10):
            self.client.post(reverse("accounts:login"), {"email": "max@uni-beispiel.de", "password": "falsch"})
        response = self.client.post(reverse("accounts:login"), {"email": "max@uni-beispiel.de", "password": "SehrGeheim!42"})
        self.assertContains(response, "Zu viele Anmeldeversuche")

    def test_forwarded_header_cannot_bypass_rate_limit(self):
        for i in range(11):
            response = self.client.post(
                reverse("accounts:login"),
                {"email": "max@uni-beispiel.de", "password": "falsch"},
                HTTP_X_FORWARDED_FOR=f"10.0.0.{i}",
            )
        self.assertContains(response, "Zu viele Anmeldeversuche")

    @override_settings(BEHIND_PROXY=True)
    def test_client_ip_behind_proxy_uses_last_entry(self):
        from django.test import RequestFactory

        from core.utils import client_ip

        request = RequestFactory().get("/", HTTP_X_FORWARDED_FOR="1.2.3.4, 203.0.113.9", REMOTE_ADDR="127.0.0.1")
        self.assertEqual(client_ip(request), "203.0.113.9")
        with self.settings(BEHIND_PROXY=False):
            self.assertEqual(client_ip(request), "127.0.0.1")

    def test_admin_login_uses_protected_login(self):
        response = self.client.get("/expertenmodus/login/?next=/expertenmodus/")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(reverse("accounts:login")))

    def test_blocked_user_cannot_login(self):
        self.user.is_active = False
        self.user.save()
        response = self.client.post(reverse("accounts:login"), {"email": "max@uni-beispiel.de", "password": "SehrGeheim!42"})
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(response.status_code, 200)

    def test_password_reset(self):
        self.client.post(reverse("accounts:password_reset"), {"email": "max@uni-beispiel.de"})
        log = EmailLog.objects.get(kind="password_reset")
        path = re.search(r"https?://testserver(\S+)", log.body).group(1)
        response = self.client.post(path, {"new_password1": "NochGeheimer!77", "new_password2": "NochGeheimer!77"})
        self.assertRedirects(response, reverse("accounts:login"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NochGeheimer!77"))

    def test_password_reset_does_not_reveal_accounts(self):
        response = self.client.post(reverse("accounts:password_reset"), {"email": "niemand@uni-beispiel.de"})
        self.assertContains(response, "Falls es zu")
        self.assertFalse(EmailLog.objects.exists())

    def test_delete_account_anonymizes(self):
        self.client.force_login(self.user)
        self.client.post(reverse("accounts:account"), {"action": "delete", "password": "SehrGeheim!42"})
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertTrue(self.user.email.endswith("@invalid.local"))
        self.assertEqual(self.user.name, "Gelöschtes Konto")

    def test_unverified_user_is_sent_to_verification(self):
        user = User.objects.create_user("neu@uni-beispiel.de", "SehrGeheim!42", name="Neu")
        self.client.force_login(user)
        response = self.client.get(reverse("core:dashboard"))
        self.assertRedirects(response, reverse("accounts:resend_verification"))
