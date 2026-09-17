"""Outbound mail for the gateway, and only for the gateway.

WHY THE GATEWAY SENDS AND THE TENANT DOES NOT. Odoo can mail a reset link itself, in one call
(`_action_reset_password`). Doing it that way needs an `ir_mail_server` row inside every CLIENT
database, and that row holds the ATHERA relay credential in a table any client administrator can
read — and then use to send mail that appears to come from us. Measured 2026-09-16: not one tenant
database has a mail server, so nothing was lost by taking the other road.

The credential therefore lives here, in our own service, and the tenant's Odoo returns a token
instead of sending anything.

WHAT THIS MODULE DELIBERATELY IS NOT. It is not a mail framework. No templates, no queue, no
retries, no HTML. One plain-text message, sent synchronously, with a hard timeout. A reset mail
that cannot be delivered within the timeout is a reset mail the visitor is already refreshing the
page over; queueing it would only move the failure somewhere nobody is looking.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

_logger = logging.getLogger("login_gateway.mailer")

#: Long enough for a STARTTLS handshake to a relay on the same host, short enough that a dead
#: relay cannot hold a request thread open while a person waits on a form.
SMTP_TIMEOUT = 10


class MailNotSent(Exception):
    """Delivery failed. Carries no address and no message body."""


def send_reset_mail(settings, to_address: str, reset_url: str, display_name: str = "") -> None:
    """Send one password-reset link.

    RAISES rather than returning False. The caller renders the same page either way — the visitor
    must not learn whether an address exists — so the only way the failure reaches anyone is the
    exception being logged here and at the call site. A silent `return False` in that position is
    how "nobody ever receives the email" becomes a report from a client six weeks later.
    """
    if not settings.reset_enabled:
        raise MailNotSent("reset is not configured")

    message = EmailMessage()
    message["Subject"] = "Atur ulang kata sandi ATHERA"
    message["From"] = settings.mail_from
    message["To"] = to_address
    # `Auto-Submitted` keeps well-behaved autoresponders from answering a transactional message,
    # which otherwise lands a vacation reply in whatever mailbox `mail_from` points at.
    message["Auto-Submitted"] = "auto-generated"
    greeting = f"Halo {display_name}," if display_name else "Halo,"
    message.set_content(
        f"""{greeting}

Ada permintaan untuk mengatur ulang kata sandi akun ATHERA Anda.
Buka tautan berikut untuk memilih kata sandi baru:

{reset_url}

Tautan ini berlaku singkat dan hanya bisa dipakai sekali. Ia juga langsung batal
begitu Anda berhasil masuk dengan kata sandi lama.

Jika Anda tidak meminta ini, abaikan email ini — kata sandi Anda tidak berubah
dan tidak ada yang perlu Anda lakukan.

— ATHERA Digital Solution
"""
    )

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT) as smtp:
            if settings.smtp_starttls:
                smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(message)
    except Exception as exc:  # noqa: BLE001
        # The recipient is not logged. An error line that quotes the address turns the log into
        # the account-enumeration oracle that every response in this flow is shaped to avoid.
        _logger.error("reset mail delivery failed: %s", exc.__class__.__name__)
        raise MailNotSent(exc.__class__.__name__) from None
