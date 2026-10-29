from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("mein-bereich/", views.dashboard, name="dashboard"),
    path("faq/", views.faq, name="faq"),
    path("impressum/", views.legal, {"page": "impressum"}, name="imprint"),
    path("datenschutz/", views.legal, {"page": "datenschutz"}, name="privacy"),
    path("nutzungsbedingungen/", views.legal, {"page": "nutzungsbedingungen"}, name="terms"),
]
