from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("bestellen/<slug:slug>/", views.order, name="order"),
    path("<int:pk>/simulation/", views.simulate, name="simulate"),
    path("stripe/zurueck/", views.stripe_return, name="stripe_return"),
    path("stripe/webhook/", views.stripe_webhook, name="stripe_webhook"),
    path("<int:pk>/erfolgreich/", views.success, name="success"),
    path("<int:pk>/abgebrochen/", views.cancel, name="cancel"),
    path("<int:pk>/fortsetzen/", views.resume, name="resume"),
    path("<int:pk>/verwerfen/", views.discard, name="discard"),
    path("<int:pk>/erweitern/", views.extend, name="extend"),
]
