from django.core.paginator import Paginator
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme


def paginate(request, queryset, per_page=40):
    paginator = Paginator(queryset, per_page)
    return paginator.get_page(request.GET.get("seite"))


def int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def redirect_next(request, default):
    """Leitet auf ``next`` weiter – aber nur auf Adressen dieser Webseite."""
    target = request.POST.get("next") or request.GET.get("next")
    if target and url_has_allowed_host_and_scheme(target, {request.get_host()}, request.is_secure()):
        return redirect(target)
    return redirect(default)


def csv_safe(value):
    """Verhindert, dass Tabellenprogramme Zellinhalte als Formel ausführen."""
    text = "" if value is None else str(value)
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text
