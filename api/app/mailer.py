from __future__ import annotations

from email.message import EmailMessage
import os
import smtplib


def app_url() -> str:
    return os.getenv("APP_URL", "http://localhost:8080").rstrip("/")


def send_verification_email(email: str, display_name: str, token: str) -> str:
    link = f"{app_url()}/?verify_token={token}"
    return _send(
        email,
        "验证你的 OfferPilot 邮箱",
        f"{display_name}，你好：\n\n请在 24 小时内点击下面的链接完成邮箱验证：\n{link}\n\n如果不是你发起的注册，请忽略此邮件。",
    )


def send_password_reset_email(email: str, display_name: str, token: str) -> str:
    link = f"{app_url()}/?reset_token={token}"
    return _send(
        email,
        "重置你的 OfferPilot 密码",
        f"{display_name}，你好：\n\n请在 30 分钟内点击下面的链接重置密码：\n{link}\n\n如果不是你发起的操作，请忽略此邮件。",
    )


def _send(recipient: str, subject: str, body: str) -> str:
    host = os.getenv("SMTP_HOST")
    if not host:
        # Console mode is deliberately restricted to non-production environments.
        if os.getenv("APP_ENV", "development") == "production":
            raise RuntimeError("生产环境未配置 SMTP_HOST")
        return "console"

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = os.getenv("SMTP_FROM", "OfferPilot <no-reply@offerpilot.local>")
    message["To"] = recipient
    message.set_content(body)

    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
    with smtplib.SMTP(host, port, timeout=15) as client:
        if use_tls:
            client.starttls()
        if username:
            client.login(username, password or "")
        client.send_message(message)
    return "smtp"
