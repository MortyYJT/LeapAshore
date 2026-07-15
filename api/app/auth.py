from __future__ import annotations

from hashlib import scrypt, sha256
import hmac
import os
import secrets

from .models import DemoUser


TERMS_VERSION = "2026-07-15"


class InvalidCredentialsError(ValueError):
    pass


class AccountExistsError(ValueError):
    pass


class EmailNotVerifiedError(ValueError):
    pass


class AccountSuspendedError(ValueError):
    pass


class InvalidAuthTokenError(ValueError):
    pass


def normalize_email(email: str) -> str:
    return email.strip().lower()


def user_id_for_email(email: str) -> str:
    return f"usr_{sha256(email.encode()).hexdigest()[:16]}"


def role_for_email(email: str) -> str:
    admins = {item.strip().lower() for item in os.getenv("ADMIN_EMAILS", "").split(",") if item.strip()}
    return "admin" if email in admins else "user"


def token_hash(token: str) -> str:
    return sha256(token.encode()).hexdigest()


def new_auth_token() -> str:
    return secrets.token_urlsafe(32)


def ensure_login_allowed(user: DemoUser) -> None:
    if user.status != "active":
        raise AccountSuspendedError("账户已停用，请联系管理员")
    if not user.email_verified:
        raise EmailNotVerifiedError("请先完成邮箱验证")


def session_hours() -> int:
    return max(1, int(os.getenv("SESSION_TTL_HOURS", "168")))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        salt_hex, digest_hex = encoded.split("$", 1)
        candidate = scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(candidate.hex(), digest_hex)
    except (ValueError, TypeError):
        return False
