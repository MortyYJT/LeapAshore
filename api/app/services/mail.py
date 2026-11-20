"""Delivering the login code (openspec/changes/archive/2026-10-30-account-login, D2 and D12).

Two backends, chosen by `MAIL_BACKEND`:

- `smtp` sends through any SMTP server (QQ Mail, Gmail or Tencent Cloud SES) with the standard
  library's `smtplib` over implicit TLS, so no dependency is added.
- `log` writes the code to the application log and appends it to `MAIL_LOG_PATH`. That is how local
  runs and the browser walkthrough read a code. It refuses to run in production, independently of the
  startup check in `app.config.check_settings`, so a misconfigured server fails a login instead of
  writing working codes into a log file.

Deadline reminders (`docs/product/PRD-multi-device.md`, 3.4) go out through the same two backends by
`send_reminder`. Its failures come in two kinds, because a reminder must not be mailed twice:
`MailError` when the message certainly did not go out (no connection, login refused, recipient or
content refused), which the caller may retry, and `MailUncertain` when the connection broke after the
message was handed over, which it must not. Nothing about a reminder is logged except its reference:
no address, and never the body, which carries the unsubscribe link.
"""

import logging
import smtplib
from dataclasses import dataclass
from datetime import UTC, datetime
from email import policy
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from app.config import settings

logger = logging.getLogger(__name__)

SUBJECT = "鱼跃彼岸登录验证码"


class MailError(Exception):
    """The message was not delivered."""


class MailUncertain(MailError):
    """The server stopped answering after the message was handed over: it may have gone out."""


@dataclass(frozen=True)
class ReminderMessage:
    to: str
    subject: str
    text: str
    html: str
    # The one-click target of the `List-Unsubscribe` header (RFC 8058), and the page the body links.
    unsubscribe_url: str
    unsubscribe_page: str
    # The `reminder_emails` id: what the logs and the local outbox call this message.
    reference: str


def _body(code: str) -> str:
    minutes = settings.auth_code_ttl_seconds // 60
    return (
        f"你的鱼跃彼岸登录验证码是：{code}\n\n"
        f"{minutes} 分钟内有效，只能使用一次。如果不是你本人操作，忽略这封邮件即可。\n"
    )


def _send_smtp(email: str, code: str) -> None:
    message = EmailMessage()
    message["From"] = settings.mail_from
    message["To"] = email
    message["Subject"] = SUBJECT
    message.set_content(_body(code))
    try:
        with smtplib.SMTP_SSL(
            settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds
        ) as server:
            server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        # The address and the exception class only: the message can echo credentials back.
        logger.error("login code mail to %s failed: %s", email, type(exc).__name__)
        raise MailError("send failed") from exc


def _send_log(email: str, code: str) -> None:
    if settings.is_production:
        raise MailError("the log mail backend is disabled in production")
    logger.warning("login code for %s: %s (MAIL_BACKEND=log, not mailed)", email, code)
    path = settings.mail_log_path
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now(UTC).isoformat()} {email} {code}\n")


def send_login_code(email: str, code: str) -> None:
    """Deliver `code` to `email`, or raise `MailError`."""
    if settings.mail_backend == "smtp":
        _send_smtp(email, code)
    elif settings.mail_backend == "log":
        _send_log(email, code)
    else:
        raise MailError(f"unknown MAIL_BACKEND {settings.mail_backend!r}")


# Replies that say the server took nothing: the sender, every recipient or the content was refused.
_REFUSED = (
    smtplib.SMTPRecipientsRefused,
    smtplib.SMTPSenderRefused,
    smtplib.SMTPDataError,
    smtplib.SMTPHeloError,
    smtplib.SMTPNotSupportedError,
)


def reminder_mime(message: ReminderMessage) -> EmailMessage:
    """The reminder as a MIME message: a text part, an HTML alternative, the unsubscribe headers."""
    # Headers are not folded: a folded `List-Unsubscribe` URL is one some receivers fail to read.
    mime = EmailMessage(policy=policy.SMTP.clone(max_line_length=998))
    mime["From"] = settings.mail_from or "reminders@localhost"
    mime["To"] = message.to
    mime["Subject"] = message.subject
    mime["List-Unsubscribe"] = f"<{message.unsubscribe_url}>"
    mime["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    mime["Auto-Submitted"] = "auto-generated"
    mime["Date"] = formatdate()
    mime["Message-ID"] = make_msgid(domain=str(mime["From"]).rpartition("@")[2].strip("> ") or "localhost")
    mime.set_content(message.text, cte="base64")
    mime.add_alternative(message.html, subtype="html", cte="base64")
    return mime


def _send_reminder_smtp(message: ReminderMessage) -> None:
    try:
        mime = reminder_mime(message)
    except Exception as exc:  # noqa: BLE001 - nothing has been connected to yet, so nothing went out
        logger.error("reminder mail %s not sent, could not be built: %s", message.reference, type(exc).__name__)
        raise MailError("could not be built") from exc
    try:
        server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds)
    except (smtplib.SMTPException, OSError) as exc:
        logger.error("reminder mail %s not sent, connect: %s", message.reference, type(exc).__name__)
        raise MailError("connect failed") from exc
    try:
        try:
            server.login(settings.smtp_user, settings.smtp_password)
        except (smtplib.SMTPException, OSError) as exc:
            logger.error("reminder mail %s not sent, login: %s", message.reference, type(exc).__name__)
            raise MailError("login failed") from exc
        try:
            server.send_message(mime)
        except _REFUSED as exc:
            logger.error("reminder mail %s refused: %s", message.reference, type(exc).__name__)
            raise MailError("refused") from exc
        except (smtplib.SMTPException, OSError) as exc:
            logger.error("reminder mail %s may or may not have gone out: %s", message.reference, type(exc).__name__)
            raise MailUncertain("no answer after the message was handed over") from exc
    finally:
        try:
            server.quit()
        except (smtplib.SMTPException, OSError):
            server.close()


def _write_reminder(message: ReminderMessage) -> None:
    """The `log` backend: the whole message goes to a file under `var/`, and only its name to the log."""
    if settings.is_production:
        raise MailError("the log mail backend is disabled in production")
    try:
        raw = reminder_mime(message).as_bytes()
    except Exception as exc:  # noqa: BLE001 - the same answer the SMTP backend gives
        raise MailError("could not be built") from exc
    folder = settings.mail_log_path.parent / "reminders"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{message.reference}.eml").write_bytes(raw)
    logger.warning("reminder mail %s written to var/reminders (MAIL_BACKEND=log, not mailed)", message.reference)


def send_reminder(message: ReminderMessage) -> None:
    """Deliver one reminder email, or raise `MailError` (not sent) or `MailUncertain` (may be sent)."""
    if settings.mail_backend == "smtp":
        _send_reminder_smtp(message)
    elif settings.mail_backend == "log":
        _write_reminder(message)
    else:
        raise MailError(f"unknown MAIL_BACKEND {settings.mail_backend!r}")
