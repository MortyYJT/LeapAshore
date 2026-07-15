import os


os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("AUTH_RATE_LIMIT_PER_MINUTE", "1000")
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "1000")
os.environ.setdefault("ADMIN_EMAILS", "admin@offerpilot.cn")
