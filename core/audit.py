import logging

from .models import AuditLog

logger = logging.getLogger("protokolle.audit")


def audit(action, message, actor=None, level=AuditLog.LEVEL_INFO):
    """Schreibt einen Eintrag ins Logbuch (und ins Server-Log)."""
    if actor is not None and not getattr(actor, "is_authenticated", False):
        actor = None
    log_level = {"warning": logging.WARNING, "error": logging.ERROR}.get(level, logging.INFO)
    logger.log(log_level, "%s: %s", action, message)
    return AuditLog.objects.create(action=action, message=message, actor=actor, level=level)
