from functools import wraps

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect


def verified_required(view):
    """Nur für angemeldete Nutzer mit bestätigter E-Mail-Adresse."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not user.email_verified and not user.is_staff:
            messages.warning(request, "Bitte bestätige zuerst deine E-Mail-Adresse.")
            return redirect("accounts:resend_verification")
        return view(request, *args, **kwargs)

    return wrapper


def staff_required(view):
    """Nur für Admins (Zugang zur Verwaltung)."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not request.user.is_staff:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper
