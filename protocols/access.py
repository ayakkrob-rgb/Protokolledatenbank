"""Wer darf was sehen? Zentrale Zugriffsregeln für Protokolle."""
from payments.models import Purchase

from .models import Examiner, Protocol


def active_purchases(user):
    if not user.is_authenticated:
        return Purchase.objects.none()
    return Purchase.objects.active().filter(user=user)


def unlocked_examiner_ids(user):
    """IDs aller Prüfer, deren Protokolle der Nutzer über ein aktives Paket sehen darf."""
    if not user.is_authenticated:
        return set()
    return set(
        Examiner.objects.filter(purchases__in=active_purchases(user)).values_list("id", flat=True).distinct()
    )


def can_access_examiner(user, examiner):
    if not user.is_authenticated:
        return False
    if user.is_staff:
        return True
    return active_purchases(user).filter(examiners=examiner).exists()


def can_access_protocol(user, protocol):
    if not user.is_authenticated:
        return False
    if user.is_staff:
        return True
    if protocol.uploaded_by_id == user.id:
        return True
    if protocol.status != Protocol.STATUS_PUBLISHED:
        return False
    return active_purchases(user).filter(examiners=protocol.examiner_id).exists()
