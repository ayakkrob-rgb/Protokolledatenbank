from django.contrib import admin
from django.contrib.auth.views import redirect_to_login
from django.urls import include, path, reverse


def _admin_login(request, extra_context=None):
    """Der Expertenmodus nutzt die normale Anmeldung (mit Schutz gegen das Durchprobieren von Passwörtern)."""
    return redirect_to_login(request.GET.get("next", "/expertenmodus/"), reverse("accounts:login"))


admin.site.login = _admin_login

admin.site.site_header = "Protokolldatenbank – Expertenmodus"
admin.site.site_title = "Expertenmodus"
admin.site.index_title = "Rohdaten"

urlpatterns = [
    path("", include("core.urls")),
    path("konto/", include("accounts.urls")),
    path("", include("protocols.urls")),
    path("zahlung/", include("payments.urls")),
    path("verwaltung/", include("verwaltung.urls")),
    path("expertenmodus/", admin.site.urls),
]

handler404 = "core.views.error_404"
handler403 = "core.views.error_403"
handler500 = "core.views.error_500"
