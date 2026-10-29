"""Dünne Schicht um die Stripe-API. Alle Stripe-Aufrufe laufen hierüber."""
import json

import stripe

from core.models import SiteSettings


class StripeNotConfigured(Exception):
    pass


def _client(site=None):
    site = site or SiteSettings.get()
    key = site.effective_stripe_secret_key
    if not key:
        raise StripeNotConfigured("Es ist kein Stripe Secret Key hinterlegt (Verwaltung → Einstellungen → Zahlungen).")
    return stripe.StripeClient(key, max_network_retries=2)


def create_checkout_session(purchase, success_url, cancel_url, site=None):
    examiners = ", ".join(e.name for e in purchase.examiners.all())
    metadata = {
        "purchase_id": str(purchase.pk),
        "purchase_number": purchase.number,
        "exam": purchase.exam.code,
        "user_email": purchase.email,
    }
    params = {
        "mode": "payment",
        "line_items": [
            {
                "quantity": 1,
                "price_data": {
                    "currency": purchase.currency,
                    "unit_amount": purchase.amount_cents,
                    "product_data": {
                        "name": f"Protokollzugang {purchase.exam.name}",
                        "description": f"Prüfer: {examiners}"[:500] if examiners else "Protokollzugang",
                    },
                },
            }
        ],
        "customer_email": purchase.email,
        "client_reference_id": str(purchase.pk),
        "metadata": metadata,
        "payment_intent_data": {"metadata": metadata, "description": f"{purchase.number} {purchase.exam.code}"},
        "success_url": success_url,
        "cancel_url": cancel_url,
        "locale": "de",
    }
    return _client(site).v1.checkout.sessions.create(params=params)


def retrieve_checkout_session(session_id, site=None):
    return _client(site).v1.checkout.sessions.retrieve(session_id)


def create_refund(payment_intent, amount_cents, idempotency_key, metadata=None, site=None):
    params = {"payment_intent": payment_intent, "amount": amount_cents, "metadata": metadata or {}}
    return _client(site).v1.refunds.create(params=params, options={"idempotency_key": idempotency_key})


def test_connection(site=None):
    """Prüft den Schlüssel, indem der Kontostand abgefragt wird."""
    balance = _client(site).v1.balance.retrieve()
    available = getattr(balance, "available", None) or []
    return {"livemode": bool(getattr(balance, "livemode", False)), "currencies": [a.currency for a in available]}


def parse_webhook(payload, signature_header, site=None):
    """Prüft die Signatur eines Webhooks und gibt das Ereignis als dict zurück."""
    site = site or SiteSettings.get()
    secret = site.effective_stripe_webhook_secret
    if not secret:
        raise StripeNotConfigured("Kein Webhook-Signaturgeheimnis hinterlegt.")
    stripe.WebhookSignature.verify_header(payload, signature_header, secret, tolerance=300)
    return json.loads(payload)


def object_id(value):
    """Stripe liefert verknüpfte Objekte je nach Aufruf als ID oder als Objekt."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("id", "")
    return getattr(value, "id", "") or ""
