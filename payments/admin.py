from django.contrib import admin

from .models import Purchase, StripeEvent


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ["id", "email", "exam", "amount_cents", "provider", "status", "refund_status", "created_at"]
    list_filter = ["status", "refund_status", "provider", "exam"]
    search_fields = ["email", "stripe_session_id", "stripe_payment_intent"]
    filter_horizontal = ["examiners"]
    raw_id_fields = ["user", "refund_protocol"]


@admin.register(StripeEvent)
class StripeEventAdmin(admin.ModelAdmin):
    list_display = ["event_id", "event_type", "received_at"]
    search_fields = ["event_id", "event_type"]
