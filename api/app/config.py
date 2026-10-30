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

    # --- Advisor conversations (openspec/changes/advisor-persistence) ---
    # The checkpointer's own psycopg pool, beside SQLAlchemy's (5 + 10 overflow). The saver runs one
    # statement at a time under its lock, so a second connection is only a spare (D3).
    checkpoint_pool_size: int = 2
    # A conversation untouched for this many days is deleted, in every mode: the page keeps its
    # conversation ids in memory only, so an idle thread is one nobody can reach any more (D7).
    advisor_thread_retention_days: int = 90

    # --- Collection queue (openspec/changes/collect-queue) ---
    # Celery's broker: Redis database 1, so its keys never share a keyspace with the advisor's counters.
    celery_broker_url: str = "redis://localhost:56379/1"
    # Model prices in CNY per million tokens, used to cost every extraction against the budget:
    # DeepSeek's peak price (api-docs.deepseek.com/zh-cn/quick_start/pricing, read 2026-10-30), so the
    # recorded spend is an upper bound (off-peak is half).
    collect_price_cache_hit: float = 0.04
    collect_price_cache_miss: float = 2.0
    collect_price_output: float = 8.0
    # The beat's re-collection: pages not fetched for this many days, at most this many a day, under
    # this daily model spend (Beijing day).
    collect_recollect_days: int = 30
    collect_recollect_per_day: int = 200
    collect_daily_budget_cny: float = 1.0
    # Discovery keeps at most this many program pages per school (the agents' brief stopped at ~60).
    collect_programs_per_school: int = 60
    # Rendering needs Node and Chrome (scripts/render-page.cjs); the production image has neither, so
    # pages that need it are deferred there and collected on a machine that can render.
    collect_can_render: bool = True

    # --- Hybrid retrieval (openspec/changes/hybrid-retrieval) ---
    # How the advisor orders the rows inside the named schools: `rules` (the P0 #4 name patterns),
    # `fts`, `vector` or `hybrid` (RRF of the two). `hybrid` without a question vector ranks by full text.
    advisor_retrieval: str = "hybrid"
    # SiliconFlow's OpenAI-compatible embeddings. An empty key turns the vector half off: nothing is
    # embedded and no question text is sent anywhere.
    embed_base_url: str = "https://api.siliconflow.cn/v1"
    embed_model: str = "BAAI/bge-m3"
    embed_api_key: str = ""
    # A question waits at most this long for its vector, then is ranked by full text.
    embed_timeout_seconds: float = 3.0
    embed_batch_size: int = 32
    # The hourly beat backfill embeds at most this many programs per run (the first fill is the CLI).
    embed_backfill_per_run: int = 2000
    # CNY per million input tokens: siliconflow.cn/pricing lists BAAI/bge-m3 as 免费 (read 2026-10-30;
    # Pro/BAAI/bge-m3 is ¥0.07). Recorded spend is tokens x this.
    embed_price_cny_per_mtok: float = 0.0

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
