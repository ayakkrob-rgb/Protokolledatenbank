from django.urls import path

from . import views

app_name = "protocols"

urlpatterns = [
    path("pruefungen/", views.exam_list, name="exam_list"),
    path("pruefungen/<slug:slug>/", views.exam_detail, name="exam_detail"),
    path("pruefer/<int:pk>/", views.examiner_detail, name="examiner_detail"),
    path("protokolle/<int:pk>/", views.protocol_detail, name="protocol_detail"),
    path("protokolle/<int:pk>/datei/", views.protocol_file, name="protocol_file"),
    path("protokolle/<int:pk>/pdf/", views.protocol_text_pdf, name="protocol_text_pdf"),
    path("hochladen/", views.upload_start, name="upload_start"),
    path("hochladen/danke/<str:key>/", views.upload_done, name="upload_done"),
    path("hochladen/<slug:slug>/", views.upload, name="upload"),
]
