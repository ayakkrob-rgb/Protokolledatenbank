from django.contrib.auth.hashers import make_password
from django.urls import reverse
from django.utils import timezone

from core.mail import send_template_email
from core.utils import absolute_url

from .tokens import email_verification_token, encode_uid, password_reset_token


def verification_url(user, request=None):
    path = reverse(
        "accounts:verify",
        kwargs={"uidb64": encode_uid(user), "token": email_verification_token.make_token(user)},
    )
    return absolute_url(path, request)


def send_verification_email(user, request=None):
    url = verification_url(user, request)
    send_template_email(
        user.email,
        "Bitte bestätige deine E-Mail-Adresse",
        "emails/verify_email.txt",
        {"user": user, "url": url},
        kind="verification",
    )
    return url


def password_reset_url(user, request=None):
    path = reverse(
        "accounts:password_reset_confirm",
        kwargs={"uidb64": encode_uid(user), "token": password_reset_token.make_token(user)},
    )
    return absolute_url(path, request)


def send_password_reset_email(user, request=None):
    url = password_reset_url(user, request)
    send_template_email(
        user.email,
        "Passwort zurücksetzen",
        "emails/password_reset.txt",
        {"user": user, "url": url},
        kind="password_reset",
    )
    return url


def anonymize_user(user):
    """Löscht personenbezogene Daten, behält aber Käufe (Aufbewahrungspflicht) und Protokolle."""
    stamp = timezone.now().strftime("%Y%m%d%H%M%S")
    user.email = f"geloescht-{user.pk}-{stamp}@invalid.local"
    user.name = "Gelöschtes Konto"
    user.is_active = False
    user.is_staff = False
    user.is_superuser = False
    user.email_verified = False
    user.password = make_password(None)
    user.admin_note = ""
    user.save()
    return user
