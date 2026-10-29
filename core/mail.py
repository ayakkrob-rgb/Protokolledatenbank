"""E-Mail-Versand mit den im Adminbereich hinterlegten SMTP-Daten.

Im Simulationsmodus werden E-Mails nicht verschickt, sondern nur im
Postausgang (Adminbereich → E-Mails) gespeichert.
"""
import logging

from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.template.loader import render_to_string

from .models import EmailLog, SiteSettings

logger = logging.getLogger(__name__)


def _connection(site):
    return get_connection(
        backend=settings.EMAIL_BACKEND,
        host=site.smtp_host,
        port=site.smtp_port,
        username=site.smtp_username or None,
        password=site.effective_smtp_password or None,
        use_tls=site.smtp_security == SiteSettings.SMTP_STARTTLS,
        use_ssl=site.smtp_security == SiteSettings.SMTP_SSL,
        timeout=20,
    )


def send_email(to, subject, body, kind="", site=None):
    site = site or SiteSettings.get()
    subject = f"[{site.site_name}] {subject}"
    log = EmailLog(to=to, subject=subject, body=body, kind=kind)
    if site.email_mode != SiteSettings.EMAIL_SMTP:
        log.status = EmailLog.STATUS_SIMULATED
        log.save()
        logger.info("E-Mail (simuliert) an %s: %s", to, subject)
        return log
    try:
        message = EmailMessage(
            subject=subject,
            body=body,
            from_email=site.sender,
            to=[to],
            reply_to=[site.contact_email] if site.contact_email else None,
            connection=_connection(site),
        )
        message.send(fail_silently=False)
        log.status = EmailLog.STATUS_SENT
    except Exception as exc:  # noqa: BLE001 – jeder Versandfehler soll protokolliert werden
        logger.exception("E-Mail an %s fehlgeschlagen", to)
        log.status = EmailLog.STATUS_FAILED
        log.error = str(exc)[:2000]
    log.save()
    return log


def send_template_email(to, subject, template, context, kind="", site=None):
    site = site or SiteSettings.get()
    context = {"site": site, **context}
    body = render_to_string(template, context).strip() + "\n"
    return send_email(to, subject, body, kind=kind, site=site)


def notify_admins(subject, template, context, kind="admin"):
    site = SiteSettings.get()
    if site.notify_email:
        send_template_email(site.notify_email, subject, template, context, kind=kind, site=site)
