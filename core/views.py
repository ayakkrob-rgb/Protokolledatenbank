from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import redirect, render

from payments.models import Purchase
from payments.services import free_slots
from protocols.models import Exam, Examiner, Protocol

from .models import SiteSettings


def home(request):
    site = SiteSettings.get()
    exams = Exam.objects.filter(is_active=True).annotate(
        examiner_count=Count("examiners", filter=Q(examiners__is_active=True), distinct=True),
        protocol_count=Count(
            "examiners__protocols", filter=Q(examiners__protocols__status=Protocol.STATUS_PUBLISHED), distinct=True
        ),
    ).order_by("sort_order", "code")
    stats = {
        "protocols": Protocol.objects.published().count(),
        "examiners": Examiner.objects.filter(is_active=True, exam__is_active=True).count(),
    }
    return render(
        request,
        "core/home.html",
        {
            "exams": exams,
            "stats": stats,
            "price": site.price,
            "refund": site.refund_amount,
        },
    )


@login_required
def dashboard(request):
    user = request.user
    if not user.email_verified and not user.is_staff:
        return redirect("accounts:resend_verification")
    site = SiteSettings.get()
    purchases = (
        Purchase.objects.filter(user=user)
        .exclude(status=Purchase.STATUS_CANCELLED)
        .select_related("exam")
        .prefetch_related("examiners")
        .order_by("-created_at")
    )
    packages = []
    for purchase in purchases:
        packages.append(
            {
                "purchase": purchase,
                "examiners": list(purchase.examiners.all()),
                "free_slots": free_slots(purchase, site) if purchase.is_active else 0,
            }
        )
    uploads = (
        Protocol.objects.filter(uploaded_by=user)
        .select_related("examiner__exam")
        .order_by("-created_at")
    )
    refundable_exams = {
        p["purchase"].exam_id
        for p in packages
        if p["purchase"].status == Purchase.STATUS_PAID and p["purchase"].refund_status == Purchase.REFUND_NONE
        and p["purchase"].amount_cents > 0
    }
    return render(
        request,
        "core/dashboard.html",
        {
            "packages": packages,
            "uploads": uploads,
            "refundable_exams": Exam.objects.filter(pk__in=refundable_exams),
            "exams": Exam.objects.filter(is_active=True),
        },
    )


def faq(request):
    return render(request, "core/faq.html")


def legal(request, page):
    site = SiteSettings.get()
    pages = {
        "impressum": ("Impressum", site.imprint_text),
        "datenschutz": ("Datenschutzerklärung", site.privacy_text),
        "nutzungsbedingungen": ("Nutzungsbedingungen", site.terms_text),
    }
    title, text = pages[page]
    return render(request, "core/legal.html", {"title": title, "text": text})


def error_404(request, exception=None):
    return render(request, "errors/404.html", status=404)


def error_403(request, exception=None):
    return render(request, "errors/403.html", status=403)


def error_500(request):
    return render(request, "errors/500.html", status=500)
