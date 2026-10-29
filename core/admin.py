from django.contrib import admin

from .models import AuditLog, EmailLog, SiteSettings


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not SiteSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(EmailLog)
class EmailLogAdmin(admin.ModelAdmin):
    list_display = ["created_at", "to", "subject", "kind", "status"]
    list_filter = ["status", "kind"]
    search_fields = ["to", "subject"]


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["created_at", "action", "level", "actor", "message"]
    list_filter = ["level", "action"]
    search_fields = ["message", "action"]
