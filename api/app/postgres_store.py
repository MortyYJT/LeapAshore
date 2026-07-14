from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
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
    RecommendationRunSummary,
)
from .store import InvalidCredentialsError, hash_password, session_hours, verify_password


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
                    id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL, password_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), expires_at TIMESTAMPTZ NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
                CREATE TABLE IF NOT EXISTS entities (
                    user_id TEXT NOT NULL REFERENCES users(id), kind TEXT NOT NULL, entity_id TEXT NOT NULL,
                    payload JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL,
                    PRIMARY KEY (user_id, kind, entity_id)
                );
                CREATE INDEX IF NOT EXISTS idx_entities_user_kind_updated
                    ON entities(user_id, kind, updated_at DESC);
                """
            )

    def login(self, email: str, password: str) -> tuple[str, DemoUser]:
        normalized = email.strip().lower()
        user = DemoUser(
            id=f"usr_{sha256(normalized.encode()).hexdigest()[:10]}",
            email=normalized,
            display_name=normalized.split("@", 1)[0],
        )
        token = f"op_{secrets.token_urlsafe(32)}"
        with self._lock, self._connection.cursor() as cursor:
            cursor.execute("SELECT password_hash FROM users WHERE id = %s", (user.id,))
            existing = cursor.fetchone()
            if existing and not verify_password(password, existing["password_hash"]):
                raise InvalidCredentialsError("邮箱或密码不正确")
            password_hash = existing["password_hash"] if existing else hash_password(password)
            cursor.execute(
                """INSERT INTO users (id, email, display_name, password_hash) VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET email = EXCLUDED.email, display_name = EXCLUDED.display_name""",
                (user.id, user.email, user.display_name, password_hash),
            )
            cursor.execute(
                "INSERT INTO sessions (token, user_id, expires_at) VALUES (%s, %s, %s)",
                (token, user.id, datetime.now(UTC) + timedelta(hours=session_hours())),
            )
        return token, user

    def user_for_token(self, token: str) -> DemoUser | None:
        with self._lock, self._connection.cursor() as cursor:
            cursor.execute(
                """SELECT users.id, users.email, users.display_name FROM sessions
                JOIN users ON users.id = sessions.user_id
                WHERE sessions.token = %s AND sessions.expires_at > NOW()""",
                (token,),
            )
            row = cursor.fetchone()
        return DemoUser(**row) if row else None

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
