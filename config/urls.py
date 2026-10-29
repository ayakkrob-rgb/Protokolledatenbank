from django.contrib import admin
from django.urls import include, path

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
