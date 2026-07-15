import pytest

from app.settings import validate_runtime_configuration


def test_production_configuration_fails_closed_without_critical_services(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    for name in ["DATABASE_URL", "SMTP_HOST", "SMTP_FROM", "APP_URL", "ADMIN_EMAILS"]:
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(RuntimeError, match="生产环境缺少必要配置"):
        validate_runtime_configuration()


def test_production_configuration_requires_https_and_restricted_cors(monkeypatch) -> None:
    values = {
        "APP_ENV": "production",
        "DATABASE_URL": "postgresql://example",
        "SMTP_HOST": "smtp.example.com",
        "SMTP_FROM": "no-reply@example.com",
        "APP_URL": "http://beta.example.com",
        "ADMIN_EMAILS": "owner@example.com",
        "CORS_ORIGINS": "http://localhost:3000",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(RuntimeError, match="HTTPS"):
        validate_runtime_configuration()

    monkeypatch.setenv("APP_URL", "https://beta.example.com")
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        validate_runtime_configuration()
