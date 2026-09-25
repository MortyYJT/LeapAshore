import pytest

from app.settings import validate_runtime_configuration
from app.agent_store.database import create_agent_engine, settings_from_env


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


def test_production_deepseek_requires_a_server_side_key(monkeypatch) -> None:
    values = {
        "APP_ENV": "production", "DATABASE_URL": "postgresql://example", "SMTP_HOST": "smtp.example.com",
        "SMTP_FROM": "no-reply@example.com", "APP_URL": "https://beta.example.com",
        "ADMIN_EMAILS": "owner@example.com", "CORS_ORIGINS": "https://beta.example.com", "LLM_PROVIDER": "deepseek",
        "TRUST_PROXY_HEADERS": "true", "EXPOSE_DEBUG_TOKENS": "false",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        validate_runtime_configuration()

    monkeypatch.setenv("DEEPSEEK_API_KEY", "server-only")
    validate_runtime_configuration()


def test_production_requires_the_configured_gateway_boundary(monkeypatch) -> None:
    values = {
        "APP_ENV": "production", "DATABASE_URL": "postgresql://example", "SMTP_HOST": "smtp.example.com",
        "SMTP_FROM": "no-reply@example.com", "APP_URL": "https://beta.example.com",
        "ADMIN_EMAILS": "owner@example.com", "CORS_ORIGINS": "https://beta.example.com",
        "LLM_PROVIDER": "deterministic", "TRUST_PROXY_HEADERS": "false",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(RuntimeError, match="TRUST_PROXY_HEADERS"):
        validate_runtime_configuration()


def test_production_rejects_exposed_debug_tokens(monkeypatch) -> None:
    values = {
        "APP_ENV": "production", "DATABASE_URL": "postgresql://example", "SMTP_HOST": "smtp.example.com",
        "SMTP_FROM": "no-reply@example.com", "APP_URL": "https://beta.example.com",
        "ADMIN_EMAILS": "owner@example.com", "CORS_ORIGINS": "https://beta.example.com",
        "LLM_PROVIDER": "deterministic", "TRUST_PROXY_HEADERS": "true", "EXPOSE_DEBUG_TOKENS": "true",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(RuntimeError, match="EXPOSE_DEBUG_TOKENS"):
        validate_runtime_configuration()


def test_mysql_agent_settings_do_not_require_or_log_a_url(monkeypatch) -> None:
    monkeypatch.delenv("MYSQL_AGENT_URL", raising=False)
    monkeypatch.setenv("MYSQL_AGENT_CONNECT_TIMEOUT", "4")
    monkeypatch.setenv("MYSQL_AGENT_POOL_SIZE", "7")
    settings = settings_from_env()
    assert settings.url == ""
    assert settings.connect_timeout_seconds == 4
    assert settings.pool_size == 7
    with pytest.raises(ValueError, match="MYSQL_AGENT_URL is required"):
        create_agent_engine(settings)


def test_mysql_agent_requires_asyncmy_dialect(monkeypatch) -> None:
    monkeypatch.setenv("MYSQL_AGENT_URL", "mysql://name:secret@localhost/db")
    with pytest.raises(ValueError, match=r"mysql\+asyncmy"):
        create_agent_engine(settings_from_env())
