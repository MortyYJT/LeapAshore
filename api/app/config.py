from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Runtime configuration. Values come from the environment or from api/.env."""

    database_url: str = "postgresql+psycopg://offerpilot:offerpilot@localhost:55432/offerpilot"

    # Where uploaded files live. Derived from this file's own location rather than the process cwd,
    # because `make api-test`, `make api-dev` and a script run from the repository root have three
    # different working directories, and a cwd-relative default would scatter the files across all
    # three. Only a path relative to this root is ever stored in the database; see
    # `app.services.documents`.
    document_storage_root: Path = Path(__file__).resolve().parent.parent / "var" / "documents"

    # The advisor's chat model, spoken to over the OpenAI protocol. An empty key leaves the rest of
    # the API working and makes the advisor answer that it is not configured, instead of failing at
    # import time.
    chat_base_url: str = "https://api.siliconflow.cn/v1"
    chat_model: str = "deepseek-ai/DeepSeek-V4-Flash"
    chat_api_key: str = ""
    # Upper bound on model calls in one ReAct loop; counting steps is what stops a tool loop.
    max_agent_steps: int = 6

    # --- Accounts (openspec/changes/account-login) ---
    # Login mode. Off keeps the anonymous-cookie behaviour, which is what production runs until
    # MortyYJT has a verified SES sender and SMTP credentials; `make api-dev-bg` turns it on locally.
    auth_enabled: bool = False
    # `production` arms the guard in `check_settings`: login mode there must have a real mail backend.
    app_env: str = "development"
    # `log` writes the code to the log and to `mail_log_path` only; `smtp` sends it.
    mail_backend: str = "log"
    mail_log_path: Path = Path(__file__).resolve().parent.parent / "var" / "mail.log"
    mail_from: str = ""
    # Tencent Cloud SES: smtp.qcloudmail.com (Hong Kong) or gz-smtp.qcloudmail.com (Guangzhou), 465 SSL.
    smtp_host: str = "smtp.qcloudmail.com"
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_timeout_seconds: float = 15.0
    # Read the client IP from the right-most X-Forwarded-For entry. Only true behind Caddy, which
    # overwrites the header; anywhere else a client could forge it.
    trust_forwarded_for: bool = False
    auth_code_ttl_seconds: int = 600
    auth_code_resend_seconds: int = 60
    auth_code_max_attempts: int = 5
    auth_codes_per_email_per_day: int = 10
    auth_codes_per_ip_per_day: int = 30
    auth_session_days: int = 30
    anonymous_retention_days: int = 90

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() == "production"


def check_settings(config: "Settings") -> None:
    """Refuse a configuration that would put login codes only in a log in production.

    Called at startup. Login mode in production with the `log` backend means nobody can ever log in,
    and the codes sit in the server log; with `smtp` and a missing credential the first send fails.
    Both are configuration mistakes, so the process stops with the reason instead of serving.
    """
    if not (config.is_production and config.auth_enabled):
        return
    missing = []
    if config.mail_backend != "smtp":
        missing.append("MAIL_BACKEND=smtp")
    for name in ("smtp_host", "smtp_user", "smtp_password", "mail_from"):
        if not str(getattr(config, name)).strip():
            missing.append(name.upper())
    if missing:
        raise RuntimeError(
            "AUTH_ENABLED=true in production needs a real mail backend; missing: " + ", ".join(missing)
        )


settings = Settings()
