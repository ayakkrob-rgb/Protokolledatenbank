from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("registrieren/", views.register, name="register"),
    path("registrieren/fast-geschafft/", views.register_done, name="register_done"),
    path("bestaetigen/<uidb64>/<token>/", views.verify, name="verify"),
    path("bestaetigung-erneut-senden/", views.resend_verification, name="resend_verification"),
    path("anmelden/", views.login_view, name="login"),
    path("abmelden/", views.logout_view, name="logout"),
    path("passwort-vergessen/", views.password_reset, name="password_reset"),
    path("passwort-neu/<uidb64>/<token>/", views.password_reset_confirm, name="password_reset_confirm"),
    path("", views.account, name="account"),
]
