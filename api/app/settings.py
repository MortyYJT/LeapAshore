import os


def validate_runtime_configuration() -> None:
    if os.getenv("APP_ENV", "development") != "production":
        return
    required = ["DATABASE_URL", "SMTP_HOST", "SMTP_FROM", "APP_URL", "ADMIN_EMAILS"]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"生产环境缺少必要配置：{', '.join(missing)}")
    if not os.environ["APP_URL"].startswith("https://"):
        raise RuntimeError("生产环境 APP_URL 必须使用 HTTPS")
    cors = os.getenv("CORS_ORIGINS", "")
    if "localhost" in cors or "*" in cors:
        raise RuntimeError("生产环境 CORS_ORIGINS 不能使用 localhost 或通配符")
    if os.getenv("LLM_PROVIDER", "deterministic").lower() == "deepseek" and not os.getenv("DEEPSEEK_API_KEY"):
        raise RuntimeError("生产环境启用 DeepSeek 时必须配置服务端 DEEPSEEK_API_KEY")
