from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.audit import audit
from core.models import SiteSettings
from core.ratelimit import allow, reset
from core.utils import client_ip

from .forms import DeleteAccountForm, EmailForm, LoginForm, ProfileForm, RegistrationForm
from .models import User
from .services import anonymize_user, send_password_reset_email, send_verification_email
from .tokens import email_verification_token, password_reset_token, user_from_uid

SIMULATED_LINK_SESSION_KEY = "simulated_mail_link"


def _show_links_on_page(site):
    """Links aus E-Mails dürfen nur bei der lokalen Entwicklung (DEBUG) direkt angezeigt werden.

    Im Betrieb würde das jedem erlauben, fremde Konten zu bestätigen oder Passwörter
    zurückzusetzen. Im E-Mail-Simulationsmodus findet ein Admin die Links im Postausgang.
    """
    return settings.DEBUG and site.email_mode == SiteSettings.EMAIL_SIMULATION


def _remember_simulated_link(request, site, url):
    if _show_links_on_page(site):
        request.session[SIMULATED_LINK_SESSION_KEY] = url


def register(request):
    if request.user.is_authenticated:
        return redirect("core:dashboard")
    site = SiteSettings.get()
    if not site.registration_open:
        return render(request, "accounts/registration_closed.html")
    form = RegistrationForm(request.POST or None, site=site)
    if request.method == "POST":
        if not allow(f"register:{client_ip(request)}", 10, 3600):
            messages.error(request, "Zu viele Registrierungen von deinem Anschluss. Bitte versuche es später erneut.")
        elif form.is_valid():
            user = User.objects.create_user(
                email=form.cleaned_data["email"],
                password=form.cleaned_data["password1"],
                name=form.cleaned_data["name"].strip(),
            )
            url = send_verification_email(user, request)
            _remember_simulated_link(request, site, url)
            request.session["pending_verification_email"] = user.email
            audit("konto.registriert", f"Neues Konto: {user.email}")
            return redirect("accounts:register_done")
    return render(request, "accounts/register.html", {"form": form})


def register_done(request):
    site = SiteSettings.get()
    return render(
        request,
        "accounts/register_done.html",
        {
            "email": request.session.get("pending_verification_email"),
            "simulated_link": request.session.pop(SIMULATED_LINK_SESSION_KEY, None),
            "email_simulated": site.email_mode == SiteSettings.EMAIL_SIMULATION,
        },
    )


def verify(request, uidb64, token):
    user = user_from_uid(uidb64)
    if user is not None and user.email_verified:
        messages.info(request, "Deine E-Mail-Adresse ist bereits bestätigt. Du kannst dich anmelden.")
        return redirect("core:dashboard" if request.user.is_authenticated else "accounts:login")
    if user is None or not email_verification_token.check_token(user, token):
        return render(request, "accounts/verify_failed.html", status=400)
    user.mark_verified()
    audit("konto.bestaetigt", f"E-Mail bestätigt: {user.email}")
    if user.is_active:
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, f"Willkommen, {user.first_name}! Deine E-Mail-Adresse ist bestätigt.")
        return redirect("core:dashboard")
    messages.success(request, "Deine E-Mail-Adresse ist bestätigt.")
    return redirect("accounts:login")


def resend_verification(request):
    site = SiteSettings.get()
    initial = {"email": request.session.get("pending_verification_email", "")}
    if request.user.is_authenticated:
        initial["email"] = request.user.email
    form = EmailForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"].lower()
        if allow(f"resend:{email}", 5, 3600) and allow(f"resend-ip:{client_ip(request)}", 20, 3600):
            user = User.objects.filter(email__iexact=email, is_active=True, email_verified=False).first()
            if user:
                url = send_verification_email(user, request)
                _remember_simulated_link(request, site, url)
        request.session["pending_verification_email"] = email
        return redirect("accounts:register_done")
    return render(request, "accounts/resend_verification.html", {"form": form})


def login_view(request):
    if request.user.is_authenticated:
        return redirect("core:dashboard")
    form = LoginForm(request.POST or None)
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    unverified_email = None
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"].lower()
        ip = client_ip(request)
        if not allow(f"login-ip:{ip}", 30, 900) or not allow(f"login:{email}", 10, 900):
            form.add_error(None, "Zu viele Anmeldeversuche. Bitte warte 15 Minuten und versuche es erneut.")
        else:
            user = authenticate(request, username=email, password=form.cleaned_data["password"])
            if user is None:
                form.add_error(None, "E-Mail-Adresse oder Passwort ist falsch.")
            elif not user.email_verified and not user.is_staff:
                unverified_email = user.email
                request.session["pending_verification_email"] = user.email
            else:
                reset(f"login:{email}")
                login(request, user)
                if next_url and url_has_allowed_host_and_scheme(next_url, {request.get_host()}, request.is_secure()):
                    return redirect(next_url)
                return redirect("verwaltung:dashboard" if user.is_staff else "core:dashboard")
    return render(
        request, "accounts/login.html", {"form": form, "next": next_url, "unverified_email": unverified_email}
    )


@require_POST
def logout_view(request):
    logout(request)
    messages.info(request, "Du wurdest abgemeldet.")
    return redirect("core:home")


def password_reset(request):
    site = SiteSettings.get()
    form = EmailForm(request.POST or None)
    simulated_link = None
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"].lower()
        if allow(f"pwreset:{email}", 5, 3600) and allow(f"pwreset-ip:{client_ip(request)}", 20, 3600):
            user = User.objects.filter(email__iexact=email, is_active=True).first()
            if user:
                url = send_password_reset_email(user, request)
                if _show_links_on_page(site):
                    simulated_link = url
        return render(
            request, "accounts/password_reset_sent.html", {"email": email, "simulated_link": simulated_link}
        )
    return render(request, "accounts/password_reset.html", {"form": form})


def password_reset_confirm(request, uidb64, token):
    user = user_from_uid(uidb64)
    if user is None or not password_reset_token.check_token(user, token):
        return render(request, "accounts/password_reset_invalid.html", status=400)
    form = SetPasswordForm(user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        if not user.email_verified:
            # Wer den Link aus der E-Mail öffnen konnte, besitzt die Adresse.
            user.mark_verified()
        audit("konto.passwort_zurueckgesetzt", f"Passwort zurückgesetzt: {user.email}")
        messages.success(request, "Dein Passwort wurde geändert. Du kannst dich jetzt anmelden.")
        return redirect("accounts:login")
    return render(request, "accounts/password_reset_confirm.html", {"form": form})


@login_required
def account(request):
    profile_form = ProfileForm(instance=request.user)
    password_form = PasswordChangeForm(request.user)
    delete_form = DeleteAccountForm(user=request.user)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "profile":
            profile_form = ProfileForm(request.POST, instance=request.user)
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, "Dein Name wurde gespeichert.")
                return redirect("accounts:account")
        elif action == "password":
            password_form = PasswordChangeForm(request.user, request.POST)
            if password_form.is_valid():
                password_form.save()
                update_session_auth_hash(request, password_form.user)
                messages.success(request, "Dein Passwort wurde geändert.")
                return redirect("accounts:account")
        elif action == "delete":
            delete_form = DeleteAccountForm(request.POST, user=request.user)
            if delete_form.is_valid():
                user = request.user
                old_email = user.email
                logout(request)
                anonymize_user(user)
                audit("konto.geloescht", f"Konto gelöscht (anonymisiert): {old_email}")
                messages.success(request, "Dein Konto wurde gelöscht.")
                return redirect("core:home")
    return render(
        request,
        "accounts/account.html",
        {"profile_form": profile_form, "password_form": password_form, "delete_form": delete_form},
    )
