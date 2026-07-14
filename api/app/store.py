from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import scrypt, sha256
import hmac
import os
from pathlib import Path
import secrets
import sqlite3
from threading import Lock
from typing import Protocol

from .models import AgentRunAudit, ApplicationTask, AdvisorThread, AgentRecommendationResponse, ApplicantProfile, DemoUser, RecommendationRunSummary


class Store(Protocol):
    """Persistence contract used by the API and its storage adapters."""

    def login(self, email: str, password: str) -> tuple[str, DemoUser]: ...
    def user_for_token(self, token: str) -> DemoUser | None: ...
    def save_profile(self, user_id: str, profile: ApplicantProfile) -> ApplicantProfile: ...
    def get_profile(self, user_id: str) -> ApplicantProfile | None: ...
    def save_run(self, user_id: str, profile: ApplicantProfile, result: AgentRecommendationResponse) -> RecommendationRunSummary: ...
    def list_runs(self, user_id: str) -> list[RecommendationRunSummary]: ...
    def get_run(self, user_id: str, run_id: str) -> AgentRecommendationResponse | None: ...
    def save_thread(self, user_id: str, thread: AdvisorThread) -> AdvisorThread: ...
    def list_threads(self, user_id: str) -> list[AdvisorThread]: ...
    def get_thread(self, user_id: str, thread_id: str) -> AdvisorThread | None: ...
    def save_task(self, user_id: str, task: ApplicationTask) -> ApplicationTask: ...
    def list_tasks(self, user_id: str) -> list[ApplicationTask]: ...
    def get_task(self, user_id: str, task_id: str) -> ApplicationTask | None: ...
    def save_audit(self, user_id: str, audit: AgentRunAudit) -> AgentRunAudit: ...
    def list_audits(self, user_id: str) -> list[AgentRunAudit]: ...


class DemoStore:
    """Small repository abstraction for the demo; replace with PostgreSQL in production."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._users: dict[str, DemoUser] = {}
        self._tokens: dict[str, tuple[str, datetime]] = {}
        self._passwords: dict[str, str] = {}
        self._profiles: dict[str, ApplicantProfile] = {}
        self._runs: dict[str, list[tuple[RecommendationRunSummary, AgentRecommendationResponse]]] = {}
        self._threads: dict[str, list[AdvisorThread]] = {}
        self._tasks: dict[str, list[ApplicationTask]] = {}
        self._audits: dict[str, list[AgentRunAudit]] = {}

    def login(self, email: str, password: str) -> tuple[str, DemoUser]:
        normalized = email.strip().lower()
        user_id = f"usr_{sha256(normalized.encode()).hexdigest()[:10]}"
        token = f"op_{secrets.token_urlsafe(32)}"
        user = DemoUser(id=user_id, email=normalized, display_name=normalized.split("@", 1)[0])
        with self._lock:
            stored_hash = self._passwords.get(user_id)
            if stored_hash and not verify_password(password, stored_hash):
                raise InvalidCredentialsError("邮箱或密码不正确")
            self._users[user_id] = user
            self._passwords.setdefault(user_id, hash_password(password))
            self._tokens[token] = (user_id, datetime.now(UTC) + timedelta(hours=session_hours()))
        return token, user

    def user_for_token(self, token: str) -> DemoUser | None:
        with self._lock:
            session = self._tokens.get(token)
            if not session or session[1] <= datetime.now(UTC):
                return None
            return self._users.get(session[0])

    def save_profile(self, user_id: str, profile: ApplicantProfile) -> ApplicantProfile:
        with self._lock:
            self._profiles[user_id] = profile
        return profile

    def get_profile(self, user_id: str) -> ApplicantProfile | None:
        with self._lock:
            return self._profiles.get(user_id)

    def save_run(self, user_id: str, profile: ApplicantProfile, result: AgentRecommendationResponse) -> RecommendationRunSummary:
        summary = RecommendationRunSummary(
            run_id=result.run_id,
            created_at=datetime.now(UTC),
            workflow_version=result.workflow_version,
            target_field=profile.target_field,
            intake=profile.intake,
            recommendation_count=len(result.recommendations),
            summary=result.summary,
        )
        with self._lock:
            self._runs.setdefault(user_id, []).insert(0, (summary, result))
        return summary

    def list_runs(self, user_id: str) -> list[RecommendationRunSummary]:
        with self._lock:
            return [summary for summary, _ in self._runs.get(user_id, [])]

    def get_run(self, user_id: str, run_id: str) -> AgentRecommendationResponse | None:
        with self._lock:
            for summary, result in self._runs.get(user_id, []):
                if summary.run_id == run_id:
                    return result
        return None

    def save_thread(self, user_id: str, thread: AdvisorThread) -> AdvisorThread:
        with self._lock:
            threads = self._threads.setdefault(user_id, [])
            threads[:] = [item for item in threads if item.id != thread.id]
            threads.insert(0, thread)
        return thread

    def list_threads(self, user_id: str) -> list[AdvisorThread]:
        with self._lock:
            return list(self._threads.get(user_id, []))

    def get_thread(self, user_id: str, thread_id: str) -> AdvisorThread | None:
        with self._lock:
            return next((item for item in self._threads.get(user_id, []) if item.id == thread_id), None)

    def save_task(self, user_id: str, task: ApplicationTask) -> ApplicationTask:
        with self._lock:
            tasks = self._tasks.setdefault(user_id, [])
            tasks[:] = [item for item in tasks if item.id != task.id]
            tasks.append(task)
        return task

    def list_tasks(self, user_id: str) -> list[ApplicationTask]:
        with self._lock:
            return sorted(self._tasks.get(user_id, []), key=lambda item: (item.status == "已完成", item.priority, item.created_at))

    def get_task(self, user_id: str, task_id: str) -> ApplicationTask | None:
        with self._lock:
            return next((item for item in self._tasks.get(user_id, []) if item.id == task_id), None)

    def save_audit(self, user_id: str, audit: AgentRunAudit) -> AgentRunAudit:
        with self._lock:
            self._audits.setdefault(user_id, []).insert(0, audit)
        return audit

    def list_audits(self, user_id: str) -> list[AgentRunAudit]:
        with self._lock:
            return list(self._audits.get(user_id, []))


class SQLiteStore:
    """Durable local adapter with the same contract as the in-memory demo store."""

    def __init__(self, database_path: str) -> None:
        self.database_path = database_path
        Path(database_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._connection = sqlite3.connect(database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._create_schema()

    def _create_schema(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    password_hash TEXT
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id),
                    expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS profiles (
                    user_id TEXT PRIMARY KEY REFERENCES users(id),
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS recommendation_runs (
                    run_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id),
                    summary_payload TEXT NOT NULL,
                    result_payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_runs_user_created
                    ON recommendation_runs(user_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS advisor_threads (
                    thread_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id),
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_threads_user_updated
                    ON advisor_threads(user_id, updated_at DESC);
                CREATE TABLE IF NOT EXISTS application_tasks (
                    task_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id),
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_user_updated
                    ON application_tasks(user_id, updated_at DESC);
                CREATE TABLE IF NOT EXISTS agent_run_audits (
                    audit_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id),
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_audits_user_created
                    ON agent_run_audits(user_id, created_at DESC);
                """
            )
            columns = {row[1] for row in self._connection.execute("PRAGMA table_info(users)").fetchall()}
            if "password_hash" not in columns:
                self._connection.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
            self._legacy_token_column = "token" in columns

    def login(self, email: str, password: str) -> tuple[str, DemoUser]:
        normalized = email.strip().lower()
        user_id = f"usr_{sha256(normalized.encode()).hexdigest()[:10]}"
        token = f"op_{secrets.token_urlsafe(32)}"
        user = DemoUser(id=user_id, email=normalized, display_name=normalized.split("@", 1)[0])
        with self._lock, self._connection:
            existing = self._connection.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
            if existing and existing["password_hash"] and not verify_password(password, existing["password_hash"]):
                raise InvalidCredentialsError("邮箱或密码不正确")
            password_hash = existing["password_hash"] if existing and existing["password_hash"] else hash_password(password)
            if self._legacy_token_column:
                self._connection.execute(
                    """INSERT INTO users (id, email, display_name, password_hash, token) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET email = excluded.email, display_name = excluded.display_name,
                    password_hash = excluded.password_hash, token = excluded.token""",
                    (user.id, user.email, user.display_name, password_hash, token),
                )
            else:
                self._connection.execute(
                    """INSERT INTO users (id, email, display_name, password_hash) VALUES (?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET email = excluded.email, display_name = excluded.display_name,
                    password_hash = excluded.password_hash""",
                    (user.id, user.email, user.display_name, password_hash),
                )
            self._connection.execute(
                "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
                (token, user.id, (datetime.now(UTC) + timedelta(hours=session_hours())).isoformat()),
            )
        return token, user

    def user_for_token(self, token: str) -> DemoUser | None:
        with self._lock:
            row = self._connection.execute(
                """SELECT users.id, users.email, users.display_name, sessions.expires_at
                FROM sessions JOIN users ON users.id = sessions.user_id WHERE sessions.token = ?""", (token,)
            ).fetchone()
        if not row or datetime.fromisoformat(row["expires_at"]) <= datetime.now(UTC):
            return None
        return DemoUser(id=row["id"], email=row["email"], display_name=row["display_name"])

    def save_profile(self, user_id: str, profile: ApplicantProfile) -> ApplicantProfile:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO profiles (user_id, payload, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (user_id, profile.model_dump_json(), datetime.now(UTC).isoformat()),
            )
        return profile

    def get_profile(self, user_id: str) -> ApplicantProfile | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT payload FROM profiles WHERE user_id = ?", (user_id,)
            ).fetchone()
        return ApplicantProfile.model_validate_json(row["payload"]) if row else None

    def save_run(self, user_id: str, profile: ApplicantProfile, result: AgentRecommendationResponse) -> RecommendationRunSummary:
        created_at = datetime.now(UTC)
        summary = RecommendationRunSummary(
            run_id=result.run_id,
            created_at=created_at,
            workflow_version=result.workflow_version,
            target_field=profile.target_field,
            intake=profile.intake,
            recommendation_count=len(result.recommendations),
            summary=result.summary,
        )
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT OR REPLACE INTO recommendation_runs
                    (run_id, user_id, summary_payload, result_payload, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    result.run_id,
                    user_id,
                    summary.model_dump_json(),
                    result.model_dump_json(),
                    created_at.isoformat(),
                ),
            )
        return summary

    def list_runs(self, user_id: str) -> list[RecommendationRunSummary]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT summary_payload FROM recommendation_runs
                WHERE user_id = ? ORDER BY created_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [RecommendationRunSummary.model_validate_json(row["summary_payload"]) for row in rows]

    def get_run(self, user_id: str, run_id: str) -> AgentRecommendationResponse | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT result_payload FROM recommendation_runs
                WHERE user_id = ? AND run_id = ?
                """,
                (user_id, run_id),
            ).fetchone()
        return AgentRecommendationResponse.model_validate_json(row["result_payload"]) if row else None

    def save_thread(self, user_id: str, thread: AdvisorThread) -> AdvisorThread:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO advisor_threads (thread_id, user_id, payload, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (thread.id, user_id, thread.model_dump_json(), thread.updated_at.isoformat()),
            )
        return thread

    def list_threads(self, user_id: str) -> list[AdvisorThread]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT payload FROM advisor_threads WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,),
            ).fetchall()
        return [AdvisorThread.model_validate_json(row["payload"]) for row in rows]

    def get_thread(self, user_id: str, thread_id: str) -> AdvisorThread | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT payload FROM advisor_threads WHERE user_id = ? AND thread_id = ?",
                (user_id, thread_id),
            ).fetchone()
        return AdvisorThread.model_validate_json(row["payload"]) if row else None

    def save_task(self, user_id: str, task: ApplicationTask) -> ApplicationTask:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO application_tasks (task_id, user_id, payload, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at
                """,
                (task.id, user_id, task.model_dump_json(), task.updated_at.isoformat()),
            )
        return task

    def list_tasks(self, user_id: str) -> list[ApplicationTask]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT payload FROM application_tasks WHERE user_id = ? ORDER BY updated_at DESC", (user_id,)
            ).fetchall()
        tasks = [ApplicationTask.model_validate_json(row["payload"]) for row in rows]
        return sorted(tasks, key=lambda item: (item.status == "已完成", item.priority, item.created_at))

    def get_task(self, user_id: str, task_id: str) -> ApplicationTask | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT payload FROM application_tasks WHERE user_id = ? AND task_id = ?", (user_id, task_id)
            ).fetchone()
        return ApplicationTask.model_validate_json(row["payload"]) if row else None

    def save_audit(self, user_id: str, audit: AgentRunAudit) -> AgentRunAudit:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO agent_run_audits (audit_id, user_id, payload, created_at) VALUES (?, ?, ?, ?)",
                (audit.id, user_id, audit.model_dump_json(), audit.created_at.isoformat()),
            )
        return audit

    def list_audits(self, user_id: str) -> list[AgentRunAudit]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT payload FROM agent_run_audits WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
            ).fetchall()
        return [AgentRunAudit.model_validate_json(row["payload"]) for row in rows]


def create_store() -> Store:
    """Select durable SQLite only when configured, keeping tests stateless by default."""
    database_path = os.getenv("DATABASE_PATH")
    return SQLiteStore(database_path) if database_path else DemoStore()


store = create_store()


class InvalidCredentialsError(ValueError):
    pass


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
