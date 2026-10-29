from .models import SiteSettings


def site(request):
    settings_obj = SiteSettings.get()
    context = {"site": settings_obj}
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated and user.is_staff and request.path.startswith("/verwaltung"):
        from payments.models import Purchase
        from protocols.models import Protocol

        context["admin_badges"] = {
            "pending_protocols": Protocol.objects.filter(status=Protocol.STATUS_PENDING).count(),
            "refund_issues": Purchase.objects.filter(
                refund_status__in=[Purchase.REFUND_FAILED, Purchase.REFUND_MANUAL_PENDING, Purchase.REFUND_PROCESSING]
            ).count(),
        }
    return context
