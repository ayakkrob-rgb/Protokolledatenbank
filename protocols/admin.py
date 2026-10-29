from django.contrib import admin

from .models import Exam, Examiner, Protocol, Subject


class SubjectInline(admin.TabularInline):
    model = Subject
    extra = 0


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "is_active", "sort_order"]
    inlines = [SubjectInline]


@admin.register(Examiner)
class ExaminerAdmin(admin.ModelAdmin):
    list_display = ["name", "exam", "subject", "is_active", "created_via_upload"]
    list_filter = ["exam", "is_active", "created_via_upload"]
    search_fields = ["name", "institute"]


@admin.register(Protocol)
class ProtocolAdmin(admin.ModelAdmin):
    list_display = ["id", "examiner", "exam_date", "status", "source", "uploaded_by", "created_at"]
    list_filter = ["status", "source", "examiner__exam"]
    search_fields = ["title", "content", "examiner__name"]
    raw_id_fields = ["examiner", "uploaded_by", "reviewed_by"]
