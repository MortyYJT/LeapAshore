from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
import os
from pathlib import Path
import sqlite3
from threading import Lock
from typing import Protocol

from .models import AdvisorThread, AgentRecommendationResponse, ApplicantProfile, DemoUser, RecommendationRunSummary


class Store(Protocol):
    """Persistence contract used by the API and its storage adapters."""

    def login(self, email: str) -> tuple[str, DemoUser]: ...
    def user_for_token(self, token: str) -> DemoUser | None: ...
    def save_profile(self, user_id: str, profile: ApplicantProfile) -> ApplicantProfile: ...
    def get_profile(self, user_id: str) -> ApplicantProfile | None: ...
    def save_run(self, user_id: str, profile: ApplicantProfile, result: AgentRecommendationResponse) -> RecommendationRunSummary: ...
    def list_runs(self, user_id: str) -> list[RecommendationRunSummary]: ...
    def get_run(self, user_id: str, run_id: str) -> AgentRecommendationResponse | None: ...
    def save_thread(self, user_id: str, thread: AdvisorThread) -> AdvisorThread: ...
    def list_threads(self, user_id: str) -> list[AdvisorThread]: ...
    def get_thread(self, user_id: str, thread_id: str) -> AdvisorThread | None: ...


class DemoStore:
    """Small repository abstraction for the demo; replace with PostgreSQL in production."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._users: dict[str, DemoUser] = {}
        self._tokens: dict[str, str] = {}
        self._profiles: dict[str, ApplicantProfile] = {}
        self._runs: dict[str, list[tuple[RecommendationRunSummary, AgentRecommendationResponse]]] = {}
        self._threads: dict[str, list[AdvisorThread]] = {}

    def login(self, email: str) -> tuple[str, DemoUser]:
        normalized = email.strip().lower()
        user_id = f"usr_{sha256(normalized.encode()).hexdigest()[:10]}"
        token = f"demo_{sha256((normalized + ':offerpilot').encode()).hexdigest()}"
        user = DemoUser(id=user_id, email=normalized, display_name=normalized.split("@", 1)[0])
        with self._lock:
            self._users[user_id] = user
            self._tokens[token] = user_id
        return token, user

    def user_for_token(self, token: str) -> DemoUser | None:
        with self._lock:
            user_id = self._tokens.get(token)
            return self._users.get(user_id) if user_id else None

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
                    token TEXT NOT NULL UNIQUE
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
                """
            )

    def login(self, email: str) -> tuple[str, DemoUser]:
        normalized = email.strip().lower()
        user_id = f"usr_{sha256(normalized.encode()).hexdigest()[:10]}"
        token = f"demo_{sha256((normalized + ':offerpilot').encode()).hexdigest()}"
        user = DemoUser(id=user_id, email=normalized, display_name=normalized.split("@", 1)[0])
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO users (id, email, display_name, token) VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    email = excluded.email,
                    display_name = excluded.display_name,
                    token = excluded.token
                """,
                (user.id, user.email, user.display_name, token),
            )
        return token, user

    def user_for_token(self, token: str) -> DemoUser | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT id, email, display_name FROM users WHERE token = ?", (token,)
            ).fetchone()
        return DemoUser(**dict(row)) if row else None

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


def create_store() -> Store:
    """Select durable SQLite only when configured, keeping tests stateless by default."""
    database_path = os.getenv("DATABASE_PATH")
    return SQLiteStore(database_path) if database_path else DemoStore()


store = create_store()
