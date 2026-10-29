import hashlib
import hmac
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock
from urllib.parse import parse_qs

import stripe
from django.urls import reverse

from core.models import EmailLog, SiteSettings
from core.testing import LONG_TEXT, BaseTestCase, make_paid_purchase
from protocols.models import Protocol
from protocols.services import create_submission, publish_protocols

from . import services, stripe_gateway
from .models import Purchase, StripeEvent


def submit_upload(user, exam, examiner, site):
    protocols, _ = create_submission(
        user=user, exam=exam, exam_date=None, grade="",
        sections=[{"examiner": examiner, "content": LONG_TEXT}], site=site,
    )
    if protocols[0].status == Protocol.STATUS_PUBLISHED:
        return publish_protocols(protocols)
    return []


class SimulatedPurchaseTests(BaseTestCase):
    def order_url(self, *examiners):
        return reverse("payments:order", args=[self.exam.slug]) + "?" + "&".join(f"pruefer={e.pk}" for e in examiners)

    def test_full_simulated_purchase(self):
        self.login()
        response = self.client.get(self.order_url(*self.examiners[:3]))
        self.assertContains(response, "30,00 €")
        post = {"examiners": [e.pk for e in self.examiners[:3]], "action": "buy", "terms": "1", "consent": "1"}
        response = self.client.post(reverse("payments:order", args=[self.exam.slug]), post)
        purchase = Purchase.objects.get(user=self.student)
        self.assertRedirects(response, reverse("payments:simulate", args=[purchase.pk]))
        self.assertEqual(purchase.status, Purchase.STATUS_PENDING)
        self.assertEqual(purchase.provider, Purchase.PROVIDER_SIMULATION)

        response = self.client.post(reverse("payments:simulate", args=[purchase.pk]), {"action": "pay"})
        self.assertRedirects(response, reverse("payments:success", args=[purchase.pk]))
        purchase.refresh_from_db()
        self.assertTrue(purchase.is_paid)
        self.assertTrue(EmailLog.objects.filter(kind="purchase", to=self.student.email).exists())
        self.assertEqual(self.client.get(self.protocols[0].get_absolute_url()).status_code, 200)

    def test_consent_is_required(self):
        self.login()
        post = {"examiners": [self.examiners[0].pk], "action": "buy", "terms": "1"}
        response = self.client.post(reverse("payments:order", args=[self.exam.slug]), post)
        self.assertContains(response, "Widerrufsrecht")
        self.assertFalse(Purchase.objects.exists())

    def test_max_examiners(self):
        self.login()
        response = self.client.get(self.order_url(*self.examiners[:5]))
        self.assertRedirects(response, self.exam.get_absolute_url())
        self.assertFalse(Purchase.objects.exists())

    def test_cannot_buy_already_unlocked_examiner(self):
        make_paid_purchase(self.student, self.exam, self.examiners[:1])
        self.login()
        response = self.client.get(self.order_url(self.examiners[0]))
        self.assertRedirects(response, self.exam.get_absolute_url())

    def test_examiner_without_protocols_cannot_be_bought(self):
        from protocols.models import Examiner

        empty = Examiner.objects.create(exam=self.exam, name="Dr. Leer")
        self.login()
        response = self.client.get(self.order_url(empty))
        self.assertRedirects(response, self.exam.get_absolute_url())

    def test_add_examiners_to_existing_package_for_free(self):
        purchase = make_paid_purchase(self.student, self.exam, self.examiners[:2])
        self.login()
        response = self.client.post(
            reverse("payments:order", args=[self.exam.slug]),
            {"examiners": [self.examiners[2].pk, self.examiners[3].pk], "action": "add"},
        )
        self.assertRedirects(response, self.exam.get_absolute_url())
        self.assertEqual(purchase.examiners.count(), 4)
        self.assertEqual(Purchase.objects.count(), 1)
        # Paket voll – kein weiteres Hinzufügen
        self.assertIsNone(services.package_with_free_slots(self.student, self.exam, self.site))

    def test_cancel_simulation(self):
        self.login()
        purchase = services.create_purchase(self.student, self.exam, self.examiners[:1], self.site)
        self.client.post(reverse("payments:simulate", args=[purchase.pk]), {"action": "cancel"})
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, Purchase.STATUS_CANCELLED)

    def test_simulation_page_not_available_for_stripe_purchases(self):
        self.login()
        purchase = Purchase.objects.create(
            user=self.student, email=self.student.email, exam=self.exam, amount_cents=3000, provider=Purchase.PROVIDER_STRIPE
        )
        response = self.client.post(reverse("payments:simulate", args=[purchase.pk]), {"action": "pay"})
        self.assertEqual(response.status_code, 404)
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, Purchase.STATUS_PENDING)

    def test_foreign_purchase_is_hidden(self):
        from core.testing import make_user

        other = make_user("other@uni-beispiel.de")
        purchase = make_paid_purchase(other, self.exam, self.examiners[:1])
        self.login()
        self.assertEqual(self.client.get(reverse("payments:success", args=[purchase.pk])).status_code, 404)

    def test_exam_price_override(self):
        from decimal import Decimal

        self.exam.price_override = Decimal("25.00")
        self.exam.save()
        purchase = services.create_purchase(self.student, self.exam, self.examiners[:1], self.site)
        self.assertEqual(purchase.amount_cents, 2500)

    def test_access_duration(self):
        self.site.access_duration_days = 30
        self.site.save()
        purchase = services.create_purchase(self.student, self.exam, self.examiners[:1], self.site)
        services.mark_paid(purchase)
        purchase.refresh_from_db()
        self.assertIsNotNone(purchase.expires_at)


class RefundTests(BaseTestCase):
    def test_upload_refunds_simulated_purchase_once(self):
        purchase = make_paid_purchase(self.student, self.exam, self.examiners[:2])
        results = submit_upload(self.student, self.exam, self.examiners[2], self.site)
        self.assertEqual(results[0].status, "refunded")
        purchase.refresh_from_db()
        self.assertEqual(purchase.refund_status, Purchase.REFUND_DONE)
        self.assertEqual(purchase.refunded_cents, 2900)
        self.assertTrue(EmailLog.objects.filter(kind="refund").exists())
        # Zweiter Upload: keine weitere Erstattung
        results = submit_upload(self.student, self.exam, self.examiners[3], self.site)
        self.assertEqual(results[0].status, "none")
        purchase.refresh_from_db()
        self.assertEqual(purchase.refunded_cents, 2900)

    def test_multi_section_upload_refunds_only_one_purchase(self):
        first = make_paid_purchase(self.student, self.exam, self.examiners[:2])
        second = make_paid_purchase(self.student, self.exam, self.examiners[2:4])
        protocols, _ = create_submission(
            user=self.student, exam=self.exam, exam_date=None, grade="",
            sections=[{"examiner": e, "content": LONG_TEXT} for e in self.examiners[:3]], site=self.site,
        )
        publish_protocols(protocols)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.refund_status, Purchase.REFUND_DONE)
        self.assertEqual(second.refund_status, Purchase.REFUND_NONE)

    def test_no_refund_for_other_exam(self):
        from protocols.models import Exam, Examiner

        m3 = Exam.objects.create(code="M3", name="M3")
        m3_examiner = Examiner.objects.create(exam=m3, name="Dr. M3")
        purchase = make_paid_purchase(self.student, self.exam, self.examiners[:1])
        results = submit_upload(self.student, m3, m3_examiner, self.site)
        self.assertEqual(results[0].status, "none")
        purchase.refresh_from_db()
        self.assertEqual(purchase.refund_status, Purchase.REFUND_NONE)

    def test_moderation_refunds_on_approval_only(self):
        self.site.require_upload_approval = True
        self.site.save()
        purchase = make_paid_purchase(self.student, self.exam, self.examiners[:1])
        submit_upload(self.student, self.exam, self.examiners[1], self.site)
        purchase.refresh_from_db()
        self.assertEqual(purchase.refund_status, Purchase.REFUND_NONE)

        protocol = Protocol.objects.get(uploaded_by=self.student)
        self.login(self.admin)
        self.client.post(reverse("verwaltung:protocol_approve", args=[protocol.pk]))
        purchase.refresh_from_db()
        protocol.refresh_from_db()
        self.assertEqual(protocol.status, Protocol.STATUS_PUBLISHED)
        self.assertEqual(purchase.refund_status, Purchase.REFUND_DONE)
        # Zweite Freigabe derselben Einsendung: keine zweite Erstattung
        self.client.post(reverse("verwaltung:protocol_approve", args=[protocol.pk]))
        purchase.refresh_from_db()
        self.assertEqual(purchase.refunded_cents, 2900)

    def test_rejected_upload_is_not_refunded(self):
        self.site.require_upload_approval = True
        self.site.save()
        purchase = make_paid_purchase(self.student, self.exam, self.examiners[:1])
        submit_upload(self.student, self.exam, self.examiners[1], self.site)
        protocol = Protocol.objects.get(uploaded_by=self.student)
        self.login(self.admin)
        self.client.post(reverse("verwaltung:protocol_reject", args=[protocol.pk]), {"reason": "Zu kurz"})
        purchase.refresh_from_db()
        protocol.refresh_from_db()
        self.assertEqual(protocol.status, Protocol.STATUS_REJECTED)
        self.assertEqual(purchase.refund_status, Purchase.REFUND_NONE)
        self.assertTrue(EmailLog.objects.filter(kind="upload", body__contains="Zu kurz").exists())

    def test_manual_purchase_needs_manual_payout(self):
        purchase = make_paid_purchase(self.student, self.exam, self.examiners[:1], provider=Purchase.PROVIDER_MANUAL)
        results = submit_upload(self.student, self.exam, self.examiners[1], self.site)
        self.assertEqual(results[0].status, "manual")
        purchase.refresh_from_db()
        self.assertEqual(purchase.refund_status, Purchase.REFUND_MANUAL_PENDING)
        services.mark_manual_refund_done(purchase, self.admin)
        purchase.refresh_from_db()
        self.assertEqual(purchase.refund_status, Purchase.REFUND_DONE)
        self.assertEqual(purchase.refunded_cents, 2900)

    def test_free_package_is_never_refunded(self):
        make_paid_purchase(self.student, self.exam, self.examiners[:1], provider=Purchase.PROVIDER_MANUAL, amount=0)
        results = submit_upload(self.student, self.exam, self.examiners[1], self.site)
        self.assertEqual(results[0].status, "none")


class StripeMockTests(BaseTestCase):
    """Stripe-Modus mit gemockter API."""

    def setUp(self):
        super().setUp()
        self.site.payment_mode = SiteSettings.PAYMENT_STRIPE
        self.site.stripe_secret_key = "sk_test_123"
        self.site.stripe_webhook_secret = "whsec_test"
        self.site.save()

    def test_checkout_redirects_to_stripe(self):
        self.login()
        session = mock.Mock(id="cs_test_1", url="https://checkout.stripe.com/c/pay/cs_test_1")
        with mock.patch.object(stripe_gateway, "create_checkout_session", return_value=session) as create:
            response = self.client.post(
                reverse("payments:order", args=[self.exam.slug]),
                {"examiners": [self.examiners[0].pk], "action": "buy", "terms": "1", "consent": "1"},
            )
        self.assertEqual(response["Location"], "https://checkout.stripe.com/c/pay/cs_test_1")
        purchase = Purchase.objects.get()
        self.assertEqual(purchase.provider, Purchase.PROVIDER_STRIPE)
        self.assertEqual(purchase.stripe_session_id, "cs_test_1")
        success_url = create.call_args[0][1]
        self.assertTrue(success_url.endswith("?session_id={CHECKOUT_SESSION_ID}"))

    def test_return_from_stripe_marks_paid(self):
        purchase = services.create_purchase(self.student, self.exam, self.examiners[:1], self.site)
        session = mock.Mock(
            id="cs_test_1", client_reference_id=str(purchase.pk), metadata={}, payment_status="paid",
            payment_intent="pi_123", amount_total=3000,
        )
        self.login()
        with mock.patch.object(stripe_gateway, "retrieve_checkout_session", return_value=session):
            response = self.client.get(reverse("payments:stripe_return") + "?session_id=cs_test_1")
        self.assertRedirects(response, reverse("payments:success", args=[purchase.pk]))
        purchase.refresh_from_db()
        self.assertTrue(purchase.is_paid)
        self.assertEqual(purchase.stripe_payment_intent, "pi_123")

    def test_unpaid_return_keeps_pending(self):
        purchase = services.create_purchase(self.student, self.exam, self.examiners[:1], self.site)
        session = mock.Mock(id="cs_1", client_reference_id=str(purchase.pk), metadata={}, payment_status="unpaid",
                            payment_intent="pi_1", amount_total=3000)
        self.login()
        with mock.patch.object(stripe_gateway, "retrieve_checkout_session", return_value=session):
            self.client.get(reverse("payments:stripe_return") + "?session_id=cs_1")
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, Purchase.STATUS_PENDING)

    def signed(self, event, secret="whsec_test"):
        payload = json.dumps(event)
        timestamp = int(time.time())
        signature = hmac.new(secret.encode(), f"{timestamp}.{payload}".encode(), hashlib.sha256).hexdigest()
        return payload, f"t={timestamp},v1={signature}"

    def post_webhook(self, event, secret="whsec_test"):
        payload, header = self.signed(event, secret)
        return self.client.post(
            reverse("payments:stripe_webhook"), payload, content_type="application/json", HTTP_STRIPE_SIGNATURE=header
        )

    def test_webhook_marks_paid_and_is_idempotent(self):
        purchase = services.create_purchase(self.student, self.exam, self.examiners[:1], self.site)
        event = {
            "id": "evt_1",
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_1", "client_reference_id": str(purchase.pk), "payment_status": "paid",
                                "payment_intent": "pi_777", "amount_total": 3000}},
        }
        response = self.post_webhook(event)
        self.assertEqual(response.status_code, 200)
        purchase.refresh_from_db()
        self.assertTrue(purchase.is_paid)
        self.assertEqual(purchase.stripe_payment_intent, "pi_777")
        self.assertEqual(self.post_webhook(event).json()["result"], "duplicate")
        self.assertEqual(StripeEvent.objects.count(), 1)
        self.assertEqual(EmailLog.objects.filter(kind="purchase").count(), 1)

    def test_webhook_rejects_bad_signature(self):
        purchase = services.create_purchase(self.student, self.exam, self.examiners[:1], self.site)
        event = {"id": "evt_2", "type": "checkout.session.completed",
                 "data": {"object": {"client_reference_id": str(purchase.pk), "payment_status": "paid"}}}
        response = self.post_webhook(event, secret="whsec_falsch")
        self.assertEqual(response.status_code, 400)
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, Purchase.STATUS_PENDING)

    def test_webhook_expired_session_cancels(self):
        purchase = services.create_purchase(self.student, self.exam, self.examiners[:1], self.site)
        event = {"id": "evt_3", "type": "checkout.session.expired",
                 "data": {"object": {"id": "cs_x", "client_reference_id": str(purchase.pk)}}}
        self.post_webhook(event)
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, Purchase.STATUS_CANCELLED)

    def test_refund_via_stripe(self):
        purchase = make_paid_purchase(
            self.student, self.exam, self.examiners[:1], provider=Purchase.PROVIDER_STRIPE, stripe_payment_intent="pi_9"
        )
        refund = mock.Mock(id="re_1", status="succeeded")
        with mock.patch.object(services, "_stripe_refunded_total", return_value=0), \
                mock.patch.object(stripe_gateway, "create_refund", return_value=refund) as create:
            results = submit_upload(self.student, self.exam, self.examiners[1], self.site)
        self.assertEqual(results[0].status, "refunded")
        self.assertEqual(create.call_args[0][:2], ("pi_9", 2900))
        purchase.refresh_from_db()
        self.assertEqual(purchase.stripe_refund_id, "re_1")
        self.assertEqual(purchase.refunded_cents, 2900)

    def test_failed_refund_is_reported_and_can_be_retried(self):
        purchase = make_paid_purchase(
            self.student, self.exam, self.examiners[:1], provider=Purchase.PROVIDER_STRIPE, stripe_payment_intent="pi_9"
        )
        self.site.notify_email = "fachschaft@uni-beispiel.de"
        self.site.save()
        error = stripe.InvalidRequestError("Charge already refunded", param=None)
        with mock.patch.object(services, "_stripe_refunded_total", return_value=0), \
                mock.patch.object(stripe_gateway, "create_refund", side_effect=error):
            results = submit_upload(self.student, self.exam, self.examiners[1], self.site)
        self.assertEqual(results[0].status, "failed")
        purchase.refresh_from_db()
        self.assertEqual(purchase.refund_status, Purchase.REFUND_FAILED)
        self.assertTrue(EmailLog.objects.filter(to="fachschaft@uni-beispiel.de", kind="admin").exists())

        # Retry durch Admin
        self.login(self.admin)
        with mock.patch.object(services, "_stripe_refunded_total", return_value=0), \
                mock.patch.object(stripe_gateway, "create_refund", return_value=mock.Mock(id="re_2", status="pending")):
            self.client.post(reverse("verwaltung:purchase_detail", args=[purchase.pk]), {"action": "refund"})
        purchase.refresh_from_db()
        self.assertEqual(purchase.refund_status, Purchase.REFUND_DONE)
        self.assertEqual(purchase.stripe_refund_id, "re_2")

    def test_refund_already_done_at_stripe_is_not_repeated(self):
        purchase = make_paid_purchase(
            self.student, self.exam, self.examiners[:1], provider=Purchase.PROVIDER_STRIPE, stripe_payment_intent="pi_9"
        )
        with mock.patch.object(services, "_stripe_refunded_total", return_value=2900), \
                mock.patch.object(stripe_gateway, "create_refund") as create:
            services.refund_purchase(purchase, 2900)
        create.assert_not_called()
        purchase.refresh_from_db()
        self.assertEqual(purchase.refund_status, Purchase.REFUND_DONE)


class _FakeStripe(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, *args):
        pass

    def _send(self, body):
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = parse_qs(self.rfile.read(length).decode())
        _FakeStripe.requests.append(("POST", self.path, body, dict(self.headers)))
        if self.path == "/v1/checkout/sessions":
            self._send({"id": "cs_test_fake", "object": "checkout.session", "url": "https://checkout.stripe.com/c/pay/cs_test_fake"})
        elif self.path == "/v1/refunds":
            self._send({"id": "re_fake", "object": "refund", "status": "succeeded", "amount": int(body["amount"][0])})

    def do_GET(self):
        _FakeStripe.requests.append(("GET", self.path, {}, dict(self.headers)))
        if self.path.startswith("/v1/checkout/sessions/"):
            self._send({"id": "cs_test_fake", "object": "checkout.session", "payment_status": "paid",
                        "client_reference_id": "1", "payment_intent": "pi_fake", "amount_total": 3000})
        elif self.path.startswith("/v1/refunds"):
            self._send({"object": "list", "data": [], "has_more": False, "url": "/v1/refunds"})
        elif self.path == "/v1/balance":
            self._send({"object": "balance", "livemode": False, "available": [{"amount": 0, "currency": "eur"}], "pending": []})


class StripeSdkIntegrationTests(BaseTestCase):
    """Prüft die echten Aufrufe des Stripe-SDK gegen einen lokalen Fake-Server."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = HTTPServer(("127.0.0.1", 0), _FakeStripe)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        _FakeStripe.requests.clear()
        self.site.payment_mode = SiteSettings.PAYMENT_STRIPE
        self.site.stripe_secret_key = "sk_test_fake"
        self.site.save()
        base = self.base

        def client(site=None):
            return stripe.StripeClient("sk_test_fake", base_addresses={"api": base}, max_network_retries=0)

        patcher = mock.patch.object(stripe_gateway, "_client", side_effect=client)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_checkout_session_parameters(self):
        purchase = services.create_purchase(self.student, self.exam, self.examiners[:2], self.site)
        session = stripe_gateway.create_checkout_session(purchase, "https://x/ok?session_id={CHECKOUT_SESSION_ID}", "https://x/abbruch")
        self.assertEqual(session.url, "https://checkout.stripe.com/c/pay/cs_test_fake")
        method, path, body, headers = _FakeStripe.requests[-1]
        self.assertEqual(path, "/v1/checkout/sessions")
        self.assertEqual(body["mode"], ["payment"])
        self.assertEqual(body["line_items[0][price_data][unit_amount]"], ["3000"])
        self.assertEqual(body["line_items[0][price_data][currency]"], ["eur"])
        self.assertEqual(body["client_reference_id"], [str(purchase.pk)])
        self.assertEqual(body["customer_email"], [self.student.email])
        self.assertEqual(body["success_url"], ["https://x/ok?session_id={CHECKOUT_SESSION_ID}"])
        self.assertEqual(headers.get("Authorization"), "Bearer sk_test_fake")

    def test_retrieve_and_sync(self):
        purchase = services.create_purchase(self.student, self.exam, self.examiners[:1], self.site)
        session = stripe_gateway.retrieve_checkout_session("cs_test_fake")
        session_dict = {"id": session.id, "client_reference_id": str(purchase.pk), "payment_status": session.payment_status,
                        "payment_intent": session.payment_intent, "amount_total": session.amount_total}
        services.sync_checkout_session(session_dict)
        purchase.refresh_from_db()
        self.assertTrue(purchase.is_paid)
        self.assertEqual(purchase.stripe_payment_intent, "pi_fake")

    def test_refund_request(self):
        purchase = make_paid_purchase(
            self.student, self.exam, self.examiners[:1], provider=Purchase.PROVIDER_STRIPE, stripe_payment_intent="pi_fake"
        )
        result = services.refund_purchase(purchase, 2900, reason="Upload")
        self.assertEqual(result.status, "refunded")
        method, path, body, headers = _FakeStripe.requests[-1]
        self.assertEqual(path, "/v1/refunds")
        self.assertEqual(body["payment_intent"], ["pi_fake"])
        self.assertEqual(body["amount"], ["2900"])
        self.assertIn("Idempotency-Key", headers)

    def test_connection_test(self):
        info = stripe_gateway.test_connection()
        self.assertFalse(info["livemode"])
        self.assertEqual(info["currencies"], ["eur"])
