"""Delivering the login code (openspec/changes/archive/2026-10-30-account-login, D2 and D12).

Two backends, chosen by `MAIL_BACKEND`:

- `smtp` sends through any SMTP server (QQ Mail, Gmail or Tencent Cloud SES) with the standard
  library's `smtplib` over implicit TLS, so no dependency is added.
- `log` writes the code to the application log and appends it to `MAIL_LOG_PATH`. That is how local
  runs and the browser walkthrough read a code. It refuses to run in production, independently of the
  startup check in `app.config.check_settings`, so a misconfigured server fails a login instead of
  writing working codes into a log file.
"""

import logging
import smtplib
from datetime import UTC, datetime
from email.message import EmailMessage

from app.config import settings

logger = logging.getLogger(__name__)

SUBJECT = "鱼跃彼岸登录验证码"


class MailError(Exception):
    """The code could not be delivered."""


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
