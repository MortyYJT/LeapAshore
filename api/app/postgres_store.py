from __future__ import annotations

from datetime import UTC, datetime, timedelta
import secrets
from threading import Lock
from typing import Any, TypeVar

from pydantic import BaseModel

from .models import (
    AgentRunAudit,
    AgentRecommendationResponse,
    ApplicationTask,
    AdvisorThread,
    ApplicantProfile,
    DemoUser,
    FeedbackItem,
    RecommendationRunSummary,
)
from .auth import (
    AccountExistsError,
    InvalidAuthTokenError,
    InvalidCredentialsError,
    TERMS_VERSION,
    ensure_login_allowed,
    hash_password,
    new_auth_token,
    normalize_email,
    role_for_email,
    session_hours,
    token_hash,
    user_id_for_email,
    verify_password,
)


ModelT = TypeVar("ModelT", bound=BaseModel)


class PostgresStore:
    """Production adapter using PostgreSQL JSONB for versionable product entities."""

    def __init__(self, database_url: str) -> None:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as error:  # pragma: no cover - only reachable in a misconfigured deployment
            raise RuntimeError("DATABASE_URL requires the psycopg dependency") from error
        self._lock = Lock()
        self._connection = psycopg.connect(database_url, autocommit=True, row_factory=dict_row)
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL, password_hash TEXT NOT NULL,
                    email_verified_at TIMESTAMPTZ, role TEXT NOT NULL DEFAULT 'user', status TEXT NOT NULL DEFAULT 'active',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), last_login_at TIMESTAMPTZ,
                    terms_accepted_at TIMESTAMPTZ, terms_version TEXT
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), expires_at TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
                CREATE TABLE IF NOT EXISTS entities (
                    user_id TEXT NOT NULL REFERENCES users(id), kind TEXT NOT NULL, entity_id TEXT NOT NULL,
                    payload JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL,
                    PRIMARY KEY (user_id, kind, entity_id)
                );
                CREATE INDEX IF NOT EXISTS idx_entities_user_kind_updated
                    ON entities(user_id, kind, updated_at DESC);
                CREATE TABLE IF NOT EXISTS auth_tokens (
                    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), purpose TEXT NOT NULL,
                    expires_at TIMESTAMPTZ NOT NULL, used_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_auth_tokens_user_purpose
                    ON auth_tokens(user_id, purpose, expires_at DESC);
                CREATE TABLE IF NOT EXISTS feedback (
                    feedback_id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL
                );
                ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMPTZ;
                ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'user';
                ALTER TABLE users ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active';
                ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
                ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ;
                ALTER TABLE users ADD COLUMN IF NOT EXISTS terms_accepted_at TIMESTAMPTZ;
                ALTER TABLE users ADD COLUMN IF NOT EXISTS terms_version TEXT;
                ALTER TABLE sessions ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
                """
            )

    def register(self, email: str, password: str, display_name: str) -> tuple[DemoUser, str]:
        normalized = normalize_email(email)
        now = datetime.now(UTC)
        user = DemoUser(
            id=user_id_for_email(normalized), email=normalized, display_name=display_name.strip(),
            role=role_for_email(normalized), email_verified=False, status="active", created_at=now,
            terms_accepted_at=now, terms_version=TERMS_VERSION,
        )
        raw_token = new_auth_token()
        with self._lock, self._connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM users WHERE email = %s", (normalized,))
            if cursor.fetchone():
                raise AccountExistsError("该邮箱已注册")
            cursor.execute(
                """INSERT INTO users
                (id, email, display_name, password_hash, email_verified_at, role, status, created_at,
                 terms_accepted_at, terms_version)
                VALUES (%s, %s, %s, %s, NULL, %s, 'active', %s, %s, %s)""",
                (user.id, user.email, user.display_name, hash_password(password), user.role, now, now, TERMS_VERSION),
            )
            self._save_auth_token(cursor, user.id, "verify_email", raw_token, now + timedelta(hours=24))
        return user, raw_token

    def verify_email(self, token: str) -> DemoUser:
        with self._lock, self._connection.cursor() as cursor:
            user_id = self._consume_auth_token(cursor, token, "verify_email")
            cursor.execute("UPDATE users SET email_verified_at = NOW() WHERE id = %s RETURNING *", (user_id,))
            row = cursor.fetchone()
        return postgres_user(row)

    def create_email_verification(self, email: str) -> tuple[DemoUser, str] | None:
        with self._lock, self._connection.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE email = %s", (normalize_email(email),))
            row = cursor.fetchone()
            if not row or row["email_verified_at"]:
                return None
            raw_token = new_auth_token()
            self._save_auth_token(cursor, row["id"], "verify_email", raw_token, datetime.now(UTC) + timedelta(hours=24))
        return postgres_user(row), raw_token

    def login(self, email: str, password: str) -> tuple[str, DemoUser]:
        normalized = normalize_email(email)
        token = f"op_{secrets.token_urlsafe(32)}"
        with self._lock, self._connection.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE email = %s", (normalized,))
            existing = cursor.fetchone()
            if not existing or not verify_password(password, existing["password_hash"]):
                raise InvalidCredentialsError("邮箱或密码不正确")
            user = postgres_user(existing)
            ensure_login_allowed(user)
            now = datetime.now(UTC)
            cursor.execute(
                "INSERT INTO sessions (token, user_id, expires_at) VALUES (%s, %s, %s)",
                (token_hash(token), user.id, now + timedelta(hours=session_hours())),
            )
            cursor.execute("UPDATE users SET last_login_at = %s WHERE id = %s", (now, user.id))
            user = user.model_copy(update={"last_login_at": now})
        return token, user

    def logout(self, token: str) -> None:
        with self._lock, self._connection.cursor() as cursor:
            cursor.execute("DELETE FROM sessions WHERE token = %s", (token_hash(token),))

    def create_password_reset(self, email: str) -> tuple[DemoUser, str] | None:
        with self._lock, self._connection.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE email = %s", (normalize_email(email),))
            row = cursor.fetchone()
            if not row:
                return None
            raw_token = new_auth_token()
            self._save_auth_token(cursor, row["id"], "reset_password", raw_token, datetime.now(UTC) + timedelta(minutes=30))
        return postgres_user(row), raw_token

    def reset_password(self, token: str, password: str) -> None:
        with self._lock, self._connection.cursor() as cursor:
            user_id = self._consume_auth_token(cursor, token, "reset_password")
            cursor.execute("UPDATE users SET password_hash = %s WHERE id = %s", (hash_password(password), user_id))
            cursor.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))

    def delete_account(self, user_id: str, password: str) -> None:
        with self._lock, self._connection.cursor() as cursor:
            cursor.execute("SELECT password_hash FROM users WHERE id = %s", (user_id,))
            row = cursor.fetchone()
            if not row or not verify_password(password, row["password_hash"]):
                raise InvalidCredentialsError("密码不正确")
            cursor.execute("DELETE FROM feedback WHERE user_id = %s", (user_id,))
            cursor.execute("DELETE FROM entities WHERE user_id = %s", (user_id,))
            cursor.execute("DELETE FROM auth_tokens WHERE user_id = %s", (user_id,))
            cursor.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))
            cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))

    @staticmethod
    def _save_auth_token(cursor: Any, user_id: str, purpose: str, raw_token: str, expires_at: datetime) -> None:
        cursor.execute("DELETE FROM auth_tokens WHERE user_id = %s AND purpose = %s", (user_id, purpose))
        cursor.execute(
            "INSERT INTO auth_tokens (token_hash, user_id, purpose, expires_at) VALUES (%s, %s, %s, %s)",
            (token_hash(raw_token), user_id, purpose, expires_at),
        )

    @staticmethod
    def _consume_auth_token(cursor: Any, raw_token: str, purpose: str) -> str:
        cursor.execute(
            """UPDATE auth_tokens SET used_at = NOW()
            WHERE token_hash = %s AND purpose = %s AND used_at IS NULL AND expires_at > NOW()
            RETURNING user_id""",
            (token_hash(raw_token), purpose),
        )
        row = cursor.fetchone()
        if not row:
            raise InvalidAuthTokenError("链接无效或已过期")
        return row["user_id"]

    def user_for_token(self, token: str) -> DemoUser | None:
        with self._lock, self._connection.cursor() as cursor:
            cursor.execute(
                """SELECT users.* FROM sessions
                JOIN users ON users.id = sessions.user_id
                WHERE sessions.token = %s AND sessions.expires_at > NOW() AND users.status = 'active'""",
                (token_hash(token),),
            )
            row = cursor.fetchone()
        return postgres_user(row) if row else None

    def _save_entity(self, user_id: str, kind: str, entity_id: str, model: BaseModel, created_at: datetime | None = None) -> None:
        from psycopg.types.json import Jsonb

        now = datetime.now(UTC)
        with self._lock, self._connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO entities (user_id, kind, entity_id, payload, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, kind, entity_id) DO UPDATE SET payload = EXCLUDED.payload, updated_at = EXCLUDED.updated_at""",
                (user_id, kind, entity_id, Jsonb(model.model_dump(mode="json")), created_at or now, now),
            )

    def _get_entity(self, user_id: str, kind: str, entity_id: str, model_type: type[ModelT]) -> ModelT | None:
        with self._lock, self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT payload FROM entities WHERE user_id = %s AND kind = %s AND entity_id = %s",
                (user_id, kind, entity_id),
            )
            row = cursor.fetchone()
        return model_type.model_validate(row["payload"]) if row else None

    def _list_entities(self, user_id: str, kind: str, model_type: type[ModelT]) -> list[ModelT]:
        with self._lock, self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT payload FROM entities WHERE user_id = %s AND kind = %s ORDER BY updated_at DESC",
                (user_id, kind),
            )
            rows = cursor.fetchall()
        return [model_type.model_validate(row["payload"]) for row in rows]

    def save_profile(self, user_id: str, profile: ApplicantProfile) -> ApplicantProfile:
        self._save_entity(user_id, "profile", "current", profile)
        return profile

    def get_profile(self, user_id: str) -> ApplicantProfile | None:
        return self._get_entity(user_id, "profile", "current", ApplicantProfile)

    def save_run(self, user_id: str, profile: ApplicantProfile, result: AgentRecommendationResponse) -> RecommendationRunSummary:
        created_at = datetime.now(UTC)
        summary = RecommendationRunSummary(
            run_id=result.run_id, created_at=created_at, workflow_version=result.workflow_version,
            target_field=profile.target_field, intake=profile.intake,
            recommendation_count=len(result.recommendations), summary=result.summary,
        )
        self._save_entity(user_id, "recommendation_result", result.run_id, result, created_at)
        self._save_entity(user_id, "recommendation_summary", result.run_id, summary, created_at)
        return summary

    def list_runs(self, user_id: str) -> list[RecommendationRunSummary]:
        return self._list_entities(user_id, "recommendation_summary", RecommendationRunSummary)

    def get_run(self, user_id: str, run_id: str) -> AgentRecommendationResponse | None:
        return self._get_entity(user_id, "recommendation_result", run_id, AgentRecommendationResponse)

    def save_thread(self, user_id: str, thread: AdvisorThread) -> AdvisorThread:
        self._save_entity(user_id, "advisor_thread", thread.id, thread, thread.created_at)
        return thread

    def list_threads(self, user_id: str) -> list[AdvisorThread]:
        return self._list_entities(user_id, "advisor_thread", AdvisorThread)

    def get_thread(self, user_id: str, thread_id: str) -> AdvisorThread | None:
        return self._get_entity(user_id, "advisor_thread", thread_id, AdvisorThread)

    def save_task(self, user_id: str, task: ApplicationTask) -> ApplicationTask:
        self._save_entity(user_id, "application_task", task.id, task, task.created_at)
        return task

    def list_tasks(self, user_id: str) -> list[ApplicationTask]:
        tasks = self._list_entities(user_id, "application_task", ApplicationTask)
        return sorted(tasks, key=lambda item: (item.status == "已完成", item.priority, item.created_at))

    def get_task(self, user_id: str, task_id: str) -> ApplicationTask | None:
        return self._get_entity(user_id, "application_task", task_id, ApplicationTask)

    def save_audit(self, user_id: str, audit: AgentRunAudit) -> AgentRunAudit:
        self._save_entity(user_id, "agent_audit", audit.id, audit, audit.created_at)
        return audit

    def list_audits(self, user_id: str) -> list[AgentRunAudit]:
        return self._list_entities(user_id, "agent_audit", AgentRunAudit)

    def save_feedback(self, feedback: FeedbackItem) -> FeedbackItem:
        from psycopg.types.json import Jsonb

        with self._lock, self._connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO feedback (feedback_id, user_id, payload, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (feedback_id) DO UPDATE SET payload = EXCLUDED.payload, updated_at = EXCLUDED.updated_at""",
                (feedback.id, feedback.user_id, Jsonb(feedback.model_dump(mode="json")), feedback.created_at, feedback.updated_at),
            )
        return feedback

    def list_feedback(self, user_id: str | None = None) -> list[FeedbackItem]:
        with self._lock, self._connection.cursor() as cursor:
            if user_id:
                cursor.execute("SELECT payload FROM feedback WHERE user_id = %s ORDER BY created_at DESC", (user_id,))
            else:
                cursor.execute("SELECT payload FROM feedback ORDER BY created_at DESC")
            rows = cursor.fetchall()
        return [FeedbackItem.model_validate(row["payload"]) for row in rows]

    def get_feedback(self, feedback_id: str) -> FeedbackItem | None:
        with self._lock, self._connection.cursor() as cursor:
            cursor.execute("SELECT payload FROM feedback WHERE feedback_id = %s", (feedback_id,))
            row = cursor.fetchone()
        return FeedbackItem.model_validate(row["payload"]) if row else None

    def list_users(self) -> list[DemoUser]:
        with self._lock, self._connection.cursor() as cursor:
            cursor.execute("SELECT * FROM users ORDER BY created_at DESC")
            rows = cursor.fetchall()
        return [postgres_user(row) for row in rows]

    def update_user_status(self, user_id: str, status: str) -> DemoUser | None:
        with self._lock, self._connection.cursor() as cursor:
            cursor.execute("UPDATE users SET status = %s WHERE id = %s RETURNING *", (status, user_id))
            row = cursor.fetchone()
            if row and status == "suspended":
                cursor.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))
        return postgres_user(row) if row else None

    def admin_counts(self) -> dict[str, int]:
        queries = {
            "users": "SELECT COUNT(*) AS count FROM users",
            "verified_users": "SELECT COUNT(*) AS count FROM users WHERE email_verified_at IS NOT NULL",
            "active_sessions": "SELECT COUNT(*) AS count FROM sessions WHERE expires_at > NOW()",
            "recommendation_runs": "SELECT COUNT(*) AS count FROM entities WHERE kind = 'recommendation_result'",
            "advisor_threads": "SELECT COUNT(*) AS count FROM entities WHERE kind = 'advisor_thread'",
            "open_feedback": "SELECT COUNT(*) AS count FROM feedback WHERE payload->>'status' != 'resolved'",
        }
        counts: dict[str, int] = {}
        with self._lock, self._connection.cursor() as cursor:
            for name, query in queries.items():
                cursor.execute(query)
                counts[name] = int(cursor.fetchone()["count"])
        return counts

    def healthcheck(self) -> bool:
        with self._lock, self._connection.cursor() as cursor:
            cursor.execute("SELECT 1 AS ok")
            return cursor.fetchone()["ok"] == 1


def postgres_user(row: dict[str, Any]) -> DemoUser:
    return DemoUser(
        id=row["id"], email=row["email"], display_name=row["display_name"],
        role=row.get("role", "user"), email_verified=bool(row.get("email_verified_at")),
        status=row.get("status", "active"), created_at=row.get("created_at"), last_login_at=row.get("last_login_at"),
        terms_accepted_at=row.get("terms_accepted_at"), terms_version=row.get("terms_version"),
    )
