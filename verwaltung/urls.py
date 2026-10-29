from django.urls import path

from . import views, views_catalog, views_people

app_name = "verwaltung"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    # Prüfungen & Fächer
    path("pruefungen/", views_catalog.exam_list, name="exams"),
    path("pruefungen/neu/", views_catalog.exam_edit, name="exam_create"),
    path("pruefungen/<int:pk>/", views_catalog.exam_edit, name="exam_edit"),
    path("pruefungen/<int:pk>/loeschen/", views_catalog.exam_delete, name="exam_delete"),
    path("pruefungen/<int:exam_pk>/faecher/neu/", views_catalog.subject_add, name="subject_add"),
    path("faecher/<int:pk>/", views_catalog.subject_update, name="subject_update"),
    # Prüfer
    path("pruefer/", views_catalog.examiner_list, name="examiners"),
    path("pruefer/neu/", views_catalog.examiner_edit, name="examiner_create"),
    path("pruefer/<int:pk>/", views_catalog.examiner_edit, name="examiner_edit"),
    path("pruefer/<int:pk>/loeschen/", views_catalog.examiner_delete, name="examiner_delete"),
    path("pruefer/<int:pk>/zusammenfuehren/", views_catalog.examiner_merge, name="examiner_merge"),
    # Protokolle
    path("protokolle/", views_catalog.protocol_list, name="protocols"),
    path("protokolle/neu/", views_catalog.protocol_edit, name="protocol_create"),
    path("protokolle/aktion/", views_catalog.protocol_bulk, name="protocol_bulk"),
    path("protokolle/<int:pk>/", views_catalog.protocol_edit, name="protocol_edit"),
    path("protokolle/<int:pk>/loeschen/", views_catalog.protocol_delete, name="protocol_delete"),
    path("protokolle/<int:pk>/freigeben/", views_catalog.protocol_approve, name="protocol_approve"),
    path("protokolle/<int:pk>/ablehnen/", views_catalog.protocol_reject, name="protocol_reject"),
    path("freigaben/", views_catalog.moderation, name="moderation"),
    path("import/", views_catalog.import_view, name="import"),
    # Nutzer
    path("nutzer/", views_people.user_list, name="users"),
    path("nutzer/neu/", views_people.user_create, name="user_create"),
    path("nutzer/<int:pk>/", views_people.user_detail, name="user_detail"),
    # Zahlungen
    path("zahlungen/", views_people.purchase_list, name="purchases"),
    path("zahlungen/export.csv", views_people.purchase_export, name="purchase_export"),
    path("zahlungen/simulierte-sperren/", views_people.revoke_simulated, name="revoke_simulated"),
    path("zahlungen/<int:pk>/", views_people.purchase_detail, name="purchase_detail"),
    # System
    path("einstellungen/", views.site_settings, name="settings"),
    path("einstellungen/test-email/", views.settings_test_email, name="settings_test_email"),
    path("einstellungen/test-stripe/", views.settings_test_stripe, name="settings_test_stripe"),
    path("emails/", views.email_list, name="emails"),
    path("emails/<int:pk>/", views.email_detail, name="email_detail"),
    path("logbuch/", views.audit_list, name="audit"),
]
