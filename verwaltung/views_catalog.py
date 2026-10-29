"""Verwaltung: Prüfungen, Fächer, Prüfer, Protokolle, Freigaben und Import."""
from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.decorators import staff_required
from core.audit import audit
from core.mail import send_template_email
from core.models import SiteSettings
from core.utils import absolute_url, format_eur
from payments.models import Purchase
from protocols import importer
from protocols.models import Exam, Examiner, Protocol, Subject
from protocols.services import attach_file, publish_protocols, reject_protocol

from .forms import ExamForm, ExaminerForm, ImportForm, MergeExaminerForm, ProtocolAdminForm, RejectForm, SubjectForm
from .helpers import int_or_none, paginate

# --- Prüfungen & Fächer ------------------------------------------------------------


@staff_required
def exam_list(request):
    exams = Exam.objects.annotate(
        subject_count=Count("subjects", distinct=True),
        examiner_count=Count("examiners", distinct=True),
        protocol_count=Count("examiners__protocols", distinct=True),
    ).order_by("sort_order", "code")
    return render(request, "verwaltung/exam_list.html", {"exams": exams, "site": SiteSettings.get()})


@staff_required
def exam_edit(request, pk=None):
    exam = get_object_or_404(Exam, pk=pk) if pk else None
    form = ExamForm(request.POST or None, instance=exam)
    if request.method == "POST" and form.is_valid():
        exam = form.save()
        audit("pruefung.gespeichert", f"Prüfung „{exam.name}“ gespeichert", actor=request.user)
        messages.success(request, f"„{exam.name}“ wurde gespeichert.")
        return redirect("verwaltung:exam_edit", pk=exam.pk)
    subjects = exam.subjects.annotate(examiner_count=Count("examiners")).order_by("sort_order", "name") if exam else []
    return render(
        request,
        "verwaltung/exam_form.html",
        {"form": form, "exam": exam, "subjects": subjects, "subject_form": SubjectForm()},
    )


@staff_required
@require_POST
def exam_delete(request, pk):
    exam = get_object_or_404(Exam, pk=pk)
    if exam.examiners.exists() or exam.purchases.exists():
        messages.error(
            request,
            "Diese Prüfung hat bereits Prüfer oder Käufe und kann nicht gelöscht werden. "
            "Setze sie stattdessen auf „inaktiv“.",
        )
        return redirect("verwaltung:exam_edit", pk=exam.pk)
    audit("pruefung.geloescht", f"Prüfung „{exam.name}“ gelöscht", actor=request.user)
    exam.delete()
    messages.success(request, "Die Prüfung wurde gelöscht.")
    return redirect("verwaltung:exams")


@staff_required
@require_POST
def subject_add(request, exam_pk):
    exam = get_object_or_404(Exam, pk=exam_pk)
    form = SubjectForm(request.POST)
    if form.is_valid():
        if exam.subjects.filter(name__iexact=form.cleaned_data["name"]).exists():
            messages.error(request, "Dieses Fach gibt es bereits.")
        else:
            subject = form.save(commit=False)
            subject.exam = exam
            subject.save()
            messages.success(request, f"Fach „{subject.name}“ hinzugefügt.")
    return redirect("verwaltung:exam_edit", pk=exam.pk)


@staff_required
@require_POST
def subject_update(request, pk):
    subject = get_object_or_404(Subject, pk=pk)
    if request.POST.get("action") == "delete":
        name = subject.name
        subject.delete()
        messages.success(request, f"Fach „{name}“ gelöscht. Die Prüfer bleiben erhalten (ohne Fach).")
    else:
        form = SubjectForm(request.POST, instance=subject)
        if form.is_valid():
            form.save()
            messages.success(request, "Fach gespeichert.")
        else:
            messages.error(request, "Fach konnte nicht gespeichert werden.")
    return redirect("verwaltung:exam_edit", pk=subject.exam_id)


# --- Prüfer ---------------------------------------------------------------------------


@staff_required
def examiner_list(request):
    qs = Examiner.objects.select_related("exam", "subject").annotate(
        published=Count("protocols", filter=Q(protocols__status=Protocol.STATUS_PUBLISHED), distinct=True),
        pending=Count("protocols", filter=Q(protocols__status=Protocol.STATUS_PENDING), distinct=True),
        buyers=Count("purchases", filter=Q(purchases__status=Purchase.STATUS_PAID), distinct=True),
    )
    q = request.GET.get("q", "").strip()
    exam_id = int_or_none(request.GET.get("pruefung"))
    state = request.GET.get("status", "")
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(institute__icontains=q) | Q(subject__name__icontains=q))
    if exam_id:
        qs = qs.filter(exam_id=exam_id)
    if state == "aktiv":
        qs = qs.filter(is_active=True)
    elif state == "inaktiv":
        qs = qs.filter(is_active=False)
    elif state == "neu":
        qs = qs.filter(created_via_upload=True)
    elif state == "leer":
        qs = qs.filter(published=0)
    qs = qs.order_by("exam__sort_order", "subject__name", "name")
    return render(
        request,
        "verwaltung/examiner_list.html",
        {"page": paginate(request, qs, 60), "q": q, "exam_id": exam_id, "state": state, "exams": Exam.objects.all()},
    )


@staff_required
def examiner_edit(request, pk=None):
    examiner = get_object_or_404(Examiner, pk=pk) if pk else None
    initial = {}
    if not examiner and request.GET.get("pruefung"):
        initial["exam"] = int_or_none(request.GET.get("pruefung"))
    form = ExaminerForm(request.POST or None, instance=examiner, initial=initial)
    if request.method == "POST" and form.is_valid():
        examiner = form.save()
        audit("pruefer.gespeichert", f"Prüfer „{examiner.name}“ ({examiner.exam.code}) gespeichert", actor=request.user)
        messages.success(request, f"„{examiner.name}“ wurde gespeichert.")
        return redirect("verwaltung:examiners")
    context = {"form": form, "examiner": examiner}
    if examiner:
        context["protocols"] = examiner.protocols.order_by("-exam_date", "-created_at")
        context["buyers"] = Purchase.objects.filter(examiners=examiner).select_related("user").order_by("-created_at")[:50]
        context["merge_form"] = MergeExaminerForm(source=examiner)
    return render(request, "verwaltung/examiner_form.html", context)


@staff_required
@require_POST
def examiner_delete(request, pk):
    examiner = get_object_or_404(Examiner, pk=pk)
    if examiner.protocols.exists() or examiner.purchases.exists():
        messages.error(
            request,
            "Dieser Prüfer hat Protokolle oder wurde bereits gekauft. Bitte „Zusammenführen“ oder auf „inaktiv“ setzen.",
        )
        return redirect("verwaltung:examiner_edit", pk=examiner.pk)
    audit("pruefer.geloescht", f"Prüfer „{examiner.name}“ ({examiner.exam.code}) gelöscht", actor=request.user)
    examiner.delete()
    messages.success(request, "Der Prüfer wurde gelöscht.")
    return redirect("verwaltung:examiners")


@staff_required
@require_POST
def examiner_merge(request, pk):
    source = get_object_or_404(Examiner, pk=pk)
    form = MergeExaminerForm(request.POST, source=source)
    if not form.is_valid():
        messages.error(request, "Bitte einen Ziel-Prüfer auswählen.")
        return redirect("verwaltung:examiner_edit", pk=source.pk)
    target = form.cleaned_data["target"]
    with transaction.atomic():
        moved = source.protocols.update(examiner=target)
        for purchase in Purchase.objects.filter(examiners=source):
            purchase.examiners.remove(source)
            purchase.examiners.add(target)
        if not target.subject and source.subject:
            target.subject = source.subject
        if not target.institute and source.institute:
            target.institute = source.institute
        target.is_active = target.is_active or source.is_active
        target.save()
        name = source.name
        source.delete()
    audit("pruefer.zusammengefuehrt", f"„{name}“ in „{target.name}“ zusammengeführt ({moved} Protokolle)", actor=request.user)
    messages.success(request, f"„{name}“ wurde mit „{target.name}“ zusammengeführt ({moved} Protokolle verschoben).")
    return redirect("verwaltung:examiner_edit", pk=target.pk)


# --- Protokolle ----------------------------------------------------------------------


@staff_required
def protocol_list(request):
    qs = Protocol.objects.select_related("examiner__exam", "uploaded_by")
    q = request.GET.get("q", "").strip()
    exam_id = int_or_none(request.GET.get("pruefung"))
    examiner_id = int_or_none(request.GET.get("pruefer"))
    status = request.GET.get("status", "")
    source = request.GET.get("herkunft", "")
    if q:
        qs = qs.filter(
            Q(title__icontains=q) | Q(content__icontains=q) | Q(examiner__name__icontains=q)
            | Q(uploaded_by__email__icontains=q) | Q(original_filename__icontains=q)
        )
    if exam_id:
        qs = qs.filter(examiner__exam_id=exam_id)
    if examiner_id:
        qs = qs.filter(examiner_id=examiner_id)
    if status:
        qs = qs.filter(status=status)
    if source:
        qs = qs.filter(source=source)
    qs = qs.order_by("-created_at")
    return render(
        request,
        "verwaltung/protocol_list.html",
        {
            "page": paginate(request, qs, 50),
            "q": q, "exam_id": exam_id, "examiner_id": examiner_id, "status": status, "source": source,
            "exams": Exam.objects.all(),
            "examiner": Examiner.objects.filter(pk=examiner_id).first() if examiner_id else None,
            "statuses": Protocol.STATUS_CHOICES,
            "sources": Protocol.SOURCE_CHOICES,
        },
    )


@staff_required
@require_POST
def protocol_bulk(request):
    ids = [int(i) for i in request.POST.getlist("ids") if i.isdigit()]
    action = request.POST.get("action")
    protocols = list(Protocol.objects.filter(pk__in=ids).select_related("examiner__exam", "uploaded_by"))
    if not protocols:
        messages.info(request, "Keine Protokolle ausgewählt.")
    elif action == "publish":
        pending = [p for p in protocols if p.status != Protocol.STATUS_PUBLISHED]
        results = publish_protocols(pending, actor=request.user)
        for protocol in pending:
            _notify_reviewed(request, protocol, approved=True)
        messages.success(request, f"{len(pending)} Protokoll(e) veröffentlicht. {_refund_summary(results)}")
    elif action == "pending":
        Protocol.objects.filter(pk__in=ids).update(status=Protocol.STATUS_PENDING)
        messages.success(request, f"{len(protocols)} Protokoll(e) auf „wartet auf Freigabe“ gesetzt.")
    elif action == "delete":
        for protocol in protocols:
            _delete_protocol(protocol, request.user)
        messages.success(request, f"{len(protocols)} Protokoll(e) gelöscht.")
    return redirect(request.POST.get("next") or "verwaltung:protocols")


def _refund_summary(results):
    done = [r for r in results if r.status == "refunded"]
    failed = [r for r in results if r.status == "failed"]
    manual = [r for r in results if r.status == "manual"]
    parts = []
    if done:
        parts.append(f"{len(done)} Erstattung(en) über insgesamt {format_eur(sum(r.amount_cents for r in done))} ausgelöst.")
    if manual:
        parts.append(f"{len(manual)} Erstattung(en) müssen manuell ausgezahlt werden.")
    if failed:
        parts.append(f"{len(failed)} Erstattung(en) fehlgeschlagen – siehe Zahlungen.")
    return " ".join(parts)


def _delete_protocol(protocol, actor):
    label = f"#{protocol.pk} {protocol.display_title} ({protocol.examiner.name})"
    if protocol.file:
        protocol.file.delete(save=False)
    protocol.delete()
    audit("protokoll.geloescht", f"Protokoll {label} gelöscht", actor=actor)


def _notify_reviewed(request, protocol, approved, reason=""):
    if not protocol.uploaded_by or protocol.source != Protocol.SOURCE_UPLOAD:
        return
    send_template_email(
        protocol.uploaded_by.email,
        "Dein Protokoll wurde freigegeben" if approved else "Dein Protokoll wurde nicht freigegeben",
        "emails/upload_reviewed.txt",
        {
            "protocol": protocol,
            "approved": approved,
            "reason": reason,
            "dashboard_url": absolute_url("core:dashboard", request),
        },
        kind="upload",
    )


@staff_required
def protocol_edit(request, pk=None):
    protocol = get_object_or_404(Protocol, pk=pk) if pk else None
    initial = {}
    if not protocol and request.GET.get("pruefer"):
        initial["examiner"] = int_or_none(request.GET.get("pruefer"))
    form = ProtocolAdminForm(request.POST or None, request.FILES or None, instance=protocol, initial=initial)
    if request.method == "POST" and form.is_valid():
        was_published = bool(protocol and protocol.status == Protocol.STATUS_PUBLISHED)
        obj = form.save(commit=False)
        if not pk:
            obj.source = Protocol.SOURCE_ADMIN
        if form.cleaned_data.get("remove_file") and obj.file:
            obj.file.delete(save=False)
            obj.file = ""
            obj.original_filename = ""
            obj.file_size = 0
        if form.cleaned_data.get("upload"):
            if obj.file:
                obj.file.delete(save=False)
            attach_file(obj, form.cleaned_data["upload"])
        if obj.status == Protocol.STATUS_PUBLISHED and not was_published:
            obj.status = Protocol.STATUS_PENDING if pk else obj.status
            obj.save()
            results = publish_protocols([obj], actor=request.user) if pk else []
            if pk:
                _notify_reviewed(request, obj, approved=True)
            summary = _refund_summary(results)
        else:
            obj.save()
            summary = ""
        audit("protokoll.gespeichert", f"Protokoll #{obj.pk} ({obj.examiner.name}) gespeichert", actor=request.user)
        messages.success(request, f"Das Protokoll wurde gespeichert. {summary}".strip())
        return redirect("verwaltung:protocol_edit", pk=obj.pk)
    refund = Purchase.objects.filter(refund_protocol=protocol).first() if protocol else None
    return render(
        request,
        "verwaltung/protocol_form.html",
        {"form": form, "protocol": protocol, "refund": refund, "reject_form": RejectForm()},
    )


@staff_required
@require_POST
def protocol_delete(request, pk):
    protocol = get_object_or_404(Protocol, pk=pk)
    _delete_protocol(protocol, request.user)
    messages.success(request, "Das Protokoll wurde gelöscht.")
    return redirect("verwaltung:protocols")


@staff_required
def moderation(request):
    pending = list(
        Protocol.objects.filter(status=Protocol.STATUS_PENDING)
        .select_related("examiner__exam", "examiner__subject", "uploaded_by")
        .order_by("created_at")
    )
    submissions = {}
    for protocol in pending:
        submissions.setdefault(protocol.submission_key or f"single-{protocol.pk}", []).append(protocol)
    return render(
        request,
        "verwaltung/moderation.html",
        {"submissions": list(submissions.values()), "reject_form": RejectForm(), "count": len(pending)},
    )


@staff_required
@require_POST
def protocol_approve(request, pk):
    protocol = get_object_or_404(Protocol, pk=pk)
    results = publish_protocols([protocol], actor=request.user)
    _notify_reviewed(request, protocol, approved=True)
    audit("protokoll.freigegeben", f"Protokoll #{protocol.pk} ({protocol.examiner.name}) freigegeben", actor=request.user)
    messages.success(request, f"Protokoll freigegeben. {_refund_summary(results)}".strip())
    return redirect(request.POST.get("next") or "verwaltung:moderation")


@staff_required
@require_POST
def protocol_reject(request, pk):
    protocol = get_object_or_404(Protocol, pk=pk)
    form = RejectForm(request.POST)
    reason = form.cleaned_data["reason"] if form.is_valid() else "Ohne Begründung"
    reject_protocol(protocol, reason, actor=request.user)
    _notify_reviewed(request, protocol, approved=False, reason=reason)
    messages.success(request, "Protokoll abgelehnt. Der Uploader wurde informiert.")
    return redirect(request.POST.get("next") or "verwaltung:moderation")


# --- Import -----------------------------------------------------------------------------


@staff_required
def import_view(request):
    form = ImportForm(request.POST or None, request.FILES or None)
    report = None
    if request.method == "POST" and form.is_valid():
        try:
            report = importer.import_zip(
                form.cleaned_data["archive"],
                site=SiteSettings.get(),
                create_exams=form.cleaned_data["create_exams"],
                status=form.cleaned_data["status"],
                actor=request.user,
                dry_run=form.cleaned_data["dry_run"],
            )
        except (ValueError, OSError) as exc:
            messages.error(request, f"Das Archiv konnte nicht gelesen werden: {exc}")
        except Exception as exc:  # noqa: BLE001 – z. B. beschädigte ZIP-Datei
            messages.error(request, f"Import fehlgeschlagen: {exc}")
        else:
            if form.cleaned_data["dry_run"]:
                messages.info(request, "Testlauf – es wurde nichts gespeichert.")
            else:
                messages.success(request, report.summary())
    return render(
        request,
        "verwaltung/import.html",
        {"form": form, "report": report, "exams": Exam.objects.prefetch_related("subjects")},
    )
