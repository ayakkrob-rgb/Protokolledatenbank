from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.urls import reverse


def to_cents(amount):
    """Wandelt einen Euro-Betrag (Decimal/str/int) in ganze Cent um."""
    if amount is None:
        return 0
    value = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(value * 100)


def format_eur(cents):
    """2950 -> '29,50 €'"""
    if cents is None:
        return "–"
    cents = int(cents)
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    euros, rest = divmod(cents, 100)
    euro_str = f"{euros:,}".replace(",", ".")
    return f"{sign}{euro_str},{rest:02d} €"


def absolute_url(path_or_name, request=None, *args, **kwargs):
    """Erzeugt eine absolute URL – bevorzugt aus der laufenden Anfrage, sonst aus SITE_URL."""
    path = path_or_name if path_or_name.startswith("/") else reverse(path_or_name, args=args, kwargs=kwargs)
    if request is not None:
        return request.build_absolute_uri(path)
    return settings.SITE_URL + path


def client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")
