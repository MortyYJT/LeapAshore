from unittest.mock import MagicMock, patch

from app.mailer import send_password_reset_email, send_verification_email


def test_verification_email_uses_public_app_url_and_authenticated_smtp(monkeypatch) -> None:
    monkeypatch.setenv("APP_URL", "https://beta.offerpilot.example")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USERNAME", "mailer")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("SMTP_FROM", "OfferPilot <no-reply@example.com>")
    monkeypatch.setenv("SMTP_USE_TLS", "true")
    smtp = MagicMock()
    with patch("app.mailer.smtplib.SMTP", return_value=smtp):
        smtp.__enter__.return_value = smtp
        assert send_verification_email("user@example.com", "Test User", "verification-token") == "smtp"

    smtp.starttls.assert_called_once_with()
    smtp.login.assert_called_once_with("mailer", "secret")
    message = smtp.send_message.call_args.args[0]
    assert message["To"] == "user@example.com"
    assert "https://beta.offerpilot.example/?verify_token=verification-token" in message.get_content()


def test_password_reset_email_supports_private_smtp_without_tls(monkeypatch) -> None:
    monkeypatch.setenv("APP_URL", "http://localhost:8080")
    monkeypatch.setenv("SMTP_HOST", "mailpit")
    monkeypatch.setenv("SMTP_PORT", "1025")
    monkeypatch.delenv("SMTP_USERNAME", raising=False)
    monkeypatch.setenv("SMTP_USE_TLS", "false")
    smtp = MagicMock()
    with patch("app.mailer.smtplib.SMTP", return_value=smtp):
        smtp.__enter__.return_value = smtp
        assert send_password_reset_email("user@example.com", "Test User", "reset-token") == "smtp"

    smtp.starttls.assert_not_called()
    smtp.login.assert_not_called()
    assert "?reset_token=reset-token" in smtp.send_message.call_args.args[0].get_content()
