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
    # Output caps per model call (openspec/changes/advisor-limits, D5). Sent as `max_tokens` in the
    # request body, because DeepSeek ignores the `max_completion_tokens` field LangChain uses.
    chat_max_tokens: int = 1500
    intent_max_tokens: int = 200
    # The requirement extractor (`app.collect.extract`) returns every field with its quote in one call.
    extract_max_tokens: int = 4000

    # --- Advisor limits (openspec/changes/advisor-limits) ---
    # The window store; also the Celery broker once P1 adds the queue. Local compose maps it to 56379.
    redis_url: str = "redis://localhost:56379/0"
    limits_key_prefix: str = "leapashore:"
    # Sliding windows, "requests/seconds" separated by commas. Subject = the account in login mode,
    # the anonymous cookie's id otherwise; IP = `app.net.client_ip`.
    advisor_subject_limits: str = "10/60,60/3600"
    advisor_ip_limits: str = "30/60,200/3600"
    # Daily token caps (Beijing day), counted from the model's reported usage. 0 refuses every turn.
    advisor_daily_tokens_per_subject: int = 200_000
    advisor_daily_tokens_per_ip: int = 600_000
    advisor_daily_tokens_site: int = 2_000_000
    # Held on the three day counters while a turn runs, so turns admitted together see each other;
    # given back when the turn ends, leaving the counters at the reported usage (D4).
    advisor_turn_token_reserve: int = 8_000

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
    # Peers whose right-most X-Forwarded-For entry is the client's address: IPs, CIDRs or hostnames,
    # comma-separated. Production lists the `caddy` service, which overwrites the header; any other
    # peer is counted as itself, so a client cannot forge an address (`app.net`).
    trusted_proxies: str = ""
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
    """Refuse a configuration that would put login codes only in a log in production, or limits that
    do not parse.

    Called at startup. Login mode in production with the `log` backend means nobody can ever log in,
    and the codes sit in the server log; with `smtp` and a missing credential the first send fails.
    Both are configuration mistakes, so the process stops with the reason instead of serving.
    """
    from app.limits import parse_windows

    parse_windows(config.advisor_subject_limits)
    parse_windows(config.advisor_ip_limits)
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
