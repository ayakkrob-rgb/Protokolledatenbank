from django.contrib import messages
from django.db.models import Count, F, Max, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import content_disposition_header

from accounts.decorators import verified_required
from core.mail import notify_admins, send_template_email
from core.models import SiteSettings
from core.utils import absolute_url, format_eur, to_cents
from payments.models import Purchase
from payments.services import eligible_purchase, examiners_for_catalog, free_slots, package_with_free_slots

from . import services
from .access import can_access_examiner, can_access_protocol, unlocked_examiner_ids
from .forms import UploadMetaForm, section_formset
from .models import Exam, Examiner, Protocol

INLINE_TYPES = {"application/pdf", "image/png", "image/jpeg"}


def exam_list(request):
    exams = (
        Exam.objects.filter(is_active=True)
        .annotate(
            examiner_count=Count("examiners", filter=Q(examiners__is_active=True), distinct=True),
            protocol_count=Count(
                "examiners__protocols",
                filter=Q(examiners__protocols__status=Protocol.STATUS_PUBLISHED),
                distinct=True,
            ),
        )
        .order_by("sort_order", "code")
    )
    return render(request, "protocols/exam_list.html", {"exams": exams})


@verified_required
def exam_detail(request, slug):
    exam = get_object_or_404(Exam, slug=slug, is_active=True)
    site = SiteSettings.get()
    examiners = examiners_for_catalog(exam).annotate(
        latest=Max("protocols__exam_date", filter=Q(protocols__status=Protocol.STATUS_PUBLISHED))
    )
    unlocked = unlocked_examiner_ids(request.user)
    groups, ungrouped = {}, []
    for examiner in examiners:
        if examiner.subject:
            groups.setdefault(examiner.subject.name, []).append(examiner)
        else:
            ungrouped.append(examiner)
    grouped = list(groups.items())
    if ungrouped:
        grouped.append(("Weitere Prüfer" if grouped else "Prüfer", ungrouped))

    package = package_with_free_slots(request.user, exam, site)
    packages = (
        Purchase.objects.active().filter(user=request.user, exam=exam).prefetch_related("examiners")
    )
    return render(
        request,
        "protocols/exam_detail.html",
        {
            "exam": exam,
            "grouped": grouped,
            "examiner_total": len(examiners),
            "unlocked": unlocked,
            "unlocked_here": [e for e in examiners if e.pk in unlocked],
            "max_examiners": exam.max_examiners(site),
            "price_cents": exam.price_cents(site),
            "refund_cents": exam.refund_cents(site),
            "package": package,
            "package_slots": free_slots(package, site) if package else 0,
            "packages": packages,
            "is_staff": request.user.is_staff,
            "preselected": {int(i) for i in request.GET.getlist("auswahl") if i.isdigit()},
        },
    )


@verified_required
def examiner_detail(request, pk):
    examiner = get_object_or_404(Examiner.objects.select_related("exam", "subject"), pk=pk)
    has_access = can_access_examiner(request.user, examiner)
    if not (examiner.is_active and examiner.exam.is_active) and not has_access:
        raise Http404
    protocols = examiner.protocols.filter(
        Q(status=Protocol.STATUS_PUBLISHED) | Q(uploaded_by=request.user)
    ).order_by(F("exam_date").desc(nulls_last=True), "-created_at")
    site = SiteSettings.get()
    return render(
        request,
        "protocols/examiner_detail.html",
        {
            "examiner": examiner,
            "exam": examiner.exam,
            "protocols": protocols,
            "has_access": has_access,
            "price_cents": examiner.exam.price_cents(site),
            "max_examiners": examiner.exam.max_examiners(site),
            "package": package_with_free_slots(request.user, examiner.exam, site),
        },
    )


def _protocol_or_redirect(request, pk):
    protocol = get_object_or_404(Protocol.objects.select_related("examiner__exam", "examiner__subject"), pk=pk)
    if not can_access_protocol(request.user, protocol):
        return protocol, False
    return protocol, True


@verified_required
def protocol_detail(request, pk):
    protocol, allowed = _protocol_or_redirect(request, pk)
    if not allowed:
        if protocol.status != Protocol.STATUS_PUBLISHED:
            raise Http404
        messages.info(request, "Schalte diesen Prüfer frei, um seine Protokolle zu lesen.")
        return redirect(protocol.examiner.get_absolute_url())
    Protocol.objects.filter(pk=protocol.pk).update(view_count=F("view_count") + 1)
    siblings = (
        protocol.examiner.protocols.filter(status=Protocol.STATUS_PUBLISHED)
        .exclude(pk=protocol.pk)
        .order_by(F("exam_date").desc(nulls_last=True))[:10]
    )
    return render(request, "protocols/protocol_detail.html", {"protocol": protocol, "siblings": siblings})


def _send_bytes(data, filename, content_type, inline):
    inline = inline and content_type in INLINE_TYPES
    response = HttpResponse(data, content_type=content_type)
    response["Content-Disposition"] = content_disposition_header(not inline, filename)
    response["Cache-Control"] = "private, no-store"
    return response


@verified_required
def protocol_file(request, pk):
    protocol, allowed = _protocol_or_redirect(request, pk)
    if not allowed or not protocol.file:
        raise Http404
    inline = request.GET.get("ansehen") == "1"
    try:
        data, filename, content_type = services.build_file_download(protocol, request.user, SiteSettings.get())
    except FileNotFoundError:
        raise Http404("Datei nicht gefunden")
    if not inline:
        Protocol.objects.filter(pk=protocol.pk).update(download_count=F("download_count") + 1)
    return _send_bytes(data, filename, content_type, inline)


@verified_required
def protocol_text_pdf(request, pk):
    protocol, allowed = _protocol_or_redirect(request, pk)
    if not allowed or not protocol.content.strip():
        raise Http404
    data, filename, content_type = services.build_text_pdf(protocol, request.user, SiteSettings.get())
    Protocol.objects.filter(pk=protocol.pk).update(download_count=F("download_count") + 1)
    return _send_bytes(data, filename, content_type, request.GET.get("ansehen") == "1")


@verified_required
def upload_start(request):
    exams = Exam.objects.filter(is_active=True)
    if exams.count() == 1:
        return redirect("protocols:upload", slug=exams.first().slug)
    site = SiteSettings.get()
    eligible = {
        p.exam_id: p
        for p in Purchase.objects.filter(
            user=request.user, status=Purchase.STATUS_PAID, refund_status=Purchase.REFUND_NONE, amount_cents__gt=0
        )
    }
    return render(
        request,
        "protocols/upload_start.html",
        {"exams": exams, "eligible": eligible, "refund_label": format_eur(to_cents(site.refund_amount))},
    )


@verified_required
def upload(request, slug):
    exam = get_object_or_404(Exam, slug=slug, is_active=True)
    site = SiteSettings.get()
    max_sections = exam.max_examiners(site)
    FormSet = section_formset(max_sections)
    form_kwargs = {"exam": exam, "site": site}
    if request.method == "POST":
        meta_form = UploadMetaForm(request.POST)
        formset = FormSet(request.POST, request.FILES, prefix="s", form_kwargs=form_kwargs)
        if meta_form.is_valid() and formset.is_valid():
            sections = [
                {
                    "examiner": form.cleaned_data["examiner_obj"],
                    "new_name": form.cleaned_data.get("new_name"),
                    "subject": form.cleaned_data.get("new_subject"),
                    "content": form.cleaned_data.get("content"),
                    "file": form.cleaned_data.get("file"),
                }
                for form in formset.forms
            ]
            protocols, new_examiners = services.create_submission(
                user=request.user,
                exam=exam,
                exam_date=meta_form.cleaned_data["exam_date"],
                grade=meta_form.cleaned_data.get("grade"),
                sections=sections,
                site=site,
            )
            if protocols[0].status == Protocol.STATUS_PUBLISHED:
                services.publish_protocols(protocols)
            _notify_upload(request, protocols, new_examiners, site)
            return redirect("protocols:upload_done", key=protocols[0].submission_key)
        messages.error(request, "Bitte prüfe die markierten Felder.")
    else:
        meta_form = UploadMetaForm()
        formset = FormSet(prefix="s", form_kwargs=form_kwargs)
    return render(
        request,
        "protocols/upload.html",
        {
            "exam": exam,
            "meta_form": meta_form,
            "formset": formset,
            "max_sections": max_sections,
            "eligible": eligible_purchase(request.user, exam),
            "refund_cents": exam.refund_cents(site),
        },
    )


def _notify_upload(request, protocols, new_examiners, site):
    pending = protocols[0].status == Protocol.STATUS_PENDING
    send_template_email(
        request.user.email,
        "Danke für dein Protokoll!",
        "emails/upload_received.txt",
        {"protocols": protocols, "pending": pending, "user": request.user},
        kind="upload",
    )
    notify_admins(
        "Neues Protokoll hochgeladen" + (" – Freigabe nötig" if pending else ""),
        "emails/admin_new_upload.txt",
        {
            "protocols": protocols,
            "new_examiners": new_examiners,
            "pending": pending,
            "user": request.user,
            "url": absolute_url("verwaltung:moderation" if pending else "verwaltung:protocols", request),
        },
    )


@verified_required
def upload_done(request, key):
    protocols = list(
        Protocol.objects.filter(submission_key=key, uploaded_by=request.user).select_related("examiner__exam").order_by("pk")
    )
    if not protocols:
        raise Http404
    refund = Purchase.objects.filter(refund_protocol__submission_key=key).first()
    return render(
        request,
        "protocols/upload_done.html",
        {
            "protocols": protocols,
            "exam": protocols[0].examiner.exam,
            "pending": protocols[0].status == Protocol.STATUS_PENDING,
            "refund": refund,
        },
    )
