from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
import secrets
import sqlite3
from threading import Lock
from typing import Protocol

from .auth import (
    AccountExistsError,
    AccountSuspendedError,
    EmailNotVerifiedError,
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
from .models import (
    AgentRunAudit,
    AgentRecommendationResponse,
    ApplicationChoice,
    ApplicationTask,
    AdvisorThread,
    ApplicantProfile,
    DemoUser,
    FeedbackItem,
    RecommendationRunSummary,
)


class Store(Protocol):
    """Persistence contract used by the API and its storage adapters."""

    def register(self, email: str, password: str, display_name: str) -> tuple[DemoUser, str]: ...
    def verify_email(self, token: str) -> DemoUser: ...
    def create_email_verification(self, email: str) -> tuple[DemoUser, str] | None: ...
    def login(self, email: str, password: str) -> tuple[str, DemoUser]: ...
    def logout(self, token: str) -> None: ...
    def create_password_reset(self, email: str) -> tuple[DemoUser, str] | None: ...
    def reset_password(self, token: str, password: str) -> None: ...
    def delete_account(self, user_id: str, password: str) -> None: ...
    def user_for_token(self, token: str) -> DemoUser | None: ...
    def save_profile(self, user_id: str, profile: ApplicantProfile) -> ApplicantProfile: ...
    def get_profile(self, user_id: str) -> ApplicantProfile | None: ...
    def save_run(self, user_id: str, profile: ApplicantProfile, result: AgentRecommendationResponse) -> RecommendationRunSummary: ...
    def list_runs(self, user_id: str) -> list[RecommendationRunSummary]: ...
    def get_run(self, user_id: str, run_id: str) -> AgentRecommendationResponse | None: ...
    def save_choice(self, user_id: str, choice: ApplicationChoice) -> ApplicationChoice: ...
    def list_choices(self, user_id: str, run_id: str | None = None) -> list[ApplicationChoice]: ...
    def get_choice(self, user_id: str, run_id: str, program_slug: str) -> ApplicationChoice | None: ...
    def save_thread(self, user_id: str, thread: AdvisorThread) -> AdvisorThread: ...
    def list_threads(self, user_id: str) -> list[AdvisorThread]: ...
    def get_thread(self, user_id: str, thread_id: str) -> AdvisorThread | None: ...
    def save_task(self, user_id: str, task: ApplicationTask) -> ApplicationTask: ...
    def list_tasks(self, user_id: str) -> list[ApplicationTask]: ...
    def get_task(self, user_id: str, task_id: str) -> ApplicationTask | None: ...
    def save_audit(self, user_id: str, audit: AgentRunAudit) -> AgentRunAudit: ...
    def list_audits(self, user_id: str) -> list[AgentRunAudit]: ...
    def save_feedback(self, feedback: FeedbackItem) -> FeedbackItem: ...
    def list_feedback(self, user_id: str | None = None) -> list[FeedbackItem]: ...
    def get_feedback(self, feedback_id: str) -> FeedbackItem | None: ...
    def list_users(self) -> list[DemoUser]: ...
    def update_user_status(self, user_id: str, status: str) -> DemoUser | None: ...
    def admin_counts(self) -> dict[str, int]: ...
    def healthcheck(self) -> bool: ...


class DemoStore:
    """Small repository abstraction for the demo; replace with PostgreSQL in production."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._users: dict[str, DemoUser] = {}
        self._tokens: dict[str, tuple[str, datetime]] = {}
        self._auth_tokens: dict[str, tuple[str, str, datetime]] = {}
        self._passwords: dict[str, str] = {}
        self._profiles: dict[str, ApplicantProfile] = {}
        self._runs: dict[str, list[tuple[RecommendationRunSummary, AgentRecommendationResponse]]] = {}
        self._choices: dict[str, list[ApplicationChoice]] = {}
        self._threads: dict[str, list[AdvisorThread]] = {}
        self._tasks: dict[str, list[ApplicationTask]] = {}
        self._audits: dict[str, list[AgentRunAudit]] = {}
        self._feedback: dict[str, FeedbackItem] = {}

    def register(self, email: str, password: str, display_name: str) -> tuple[DemoUser, str]:
        normalized = normalize_email(email)
        user_id = user_id_for_email(normalized)
        raw_token = new_auth_token()
        now = datetime.now(UTC)
        user = DemoUser(
            id=user_id, email=normalized, display_name=display_name.strip(), role=role_for_email(normalized),
            email_verified=False, created_at=now, terms_accepted_at=now, terms_version=TERMS_VERSION,
        )
        with self._lock:
            if user_id in self._users:
                raise AccountExistsError("该邮箱已注册")
            self._users[user_id] = user
            self._passwords[user_id] = hash_password(password)
            self._auth_tokens[token_hash(raw_token)] = (user_id, "verify_email", now + timedelta(hours=24))
        return user, raw_token

    def verify_email(self, token: str) -> DemoUser:
        with self._lock:
            user_id = self._consume_auth_token(token, "verify_email")
            user = self._users[user_id].model_copy(update={"email_verified": True})
            self._users[user_id] = user
        return user

    def create_email_verification(self, email: str) -> tuple[DemoUser, str] | None:
        user_id = user_id_for_email(normalize_email(email))
        with self._lock:
            user = self._users.get(user_id)
            if not user or user.email_verified:
                return None
            raw_token = new_auth_token()
            self._auth_tokens[token_hash(raw_token)] = (user_id, "verify_email", datetime.now(UTC) + timedelta(hours=24))
        return user, raw_token

    def login(self, email: str, password: str) -> tuple[str, DemoUser]:
        normalized = normalize_email(email)
        user_id = user_id_for_email(normalized)
        token = f"op_{secrets.token_urlsafe(32)}"
        with self._lock:
            user = self._users.get(user_id)
            stored_hash = self._passwords.get(user_id)
            if not user or not stored_hash or not verify_password(password, stored_hash):
                raise InvalidCredentialsError("邮箱或密码不正确")
            ensure_login_allowed(user)
            now = datetime.now(UTC)
            user = user.model_copy(update={"last_login_at": now})
            self._users[user_id] = user
            self._tokens[token_hash(token)] = (user_id, now + timedelta(hours=session_hours()))
        return token, user

    def logout(self, token: str) -> None:
        with self._lock:
            self._tokens.pop(token_hash(token), None)

    def create_password_reset(self, email: str) -> tuple[DemoUser, str] | None:
        user_id = user_id_for_email(normalize_email(email))
        with self._lock:
            user = self._users.get(user_id)
            if not user:
                return None
            raw_token = new_auth_token()
            self._auth_tokens[token_hash(raw_token)] = (user_id, "reset_password", datetime.now(UTC) + timedelta(minutes=30))
        return user, raw_token

    def reset_password(self, token: str, password: str) -> None:
        with self._lock:
            user_id = self._consume_auth_token(token, "reset_password")
            self._passwords[user_id] = hash_password(password)
            self._tokens = {key: value for key, value in self._tokens.items() if value[0] != user_id}

    def delete_account(self, user_id: str, password: str) -> None:
        with self._lock:
            encoded = self._passwords.get(user_id)
            if not encoded or not verify_password(password, encoded):
                raise InvalidCredentialsError("密码不正确")
            self._users.pop(user_id, None)
            self._passwords.pop(user_id, None)
            self._profiles.pop(user_id, None)
            self._runs.pop(user_id, None)
            self._choices.pop(user_id, None)
            self._threads.pop(user_id, None)
            self._tasks.pop(user_id, None)
            self._audits.pop(user_id, None)
            self._tokens = {key: value for key, value in self._tokens.items() if value[0] != user_id}
            self._auth_tokens = {key: value for key, value in self._auth_tokens.items() if value[0] != user_id}
            self._feedback = {key: value for key, value in self._feedback.items() if value.user_id != user_id}

    def _consume_auth_token(self, token: str, purpose: str) -> str:
        key = token_hash(token)
        record = self._auth_tokens.pop(key, None)
        if not record or record[1] != purpose or record[2] <= datetime.now(UTC):
            raise InvalidAuthTokenError("链接无效或已过期")
        return record[0]

    def user_for_token(self, token: str) -> DemoUser | None:
        with self._lock:
            session = self._tokens.get(token_hash(token))
            if not session or session[1] <= datetime.now(UTC):
                return None
            user = self._users.get(session[0])
            return user if user and user.status == "active" else None

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

    def save_choice(self, user_id: str, choice: ApplicationChoice) -> ApplicationChoice:
        with self._lock:
            choices = self._choices.setdefault(user_id, [])
            choices[:] = [item for item in choices if not (
                item.run_id == choice.run_id and item.program_slug == choice.program_slug
            )]
            choices.append(choice)
        return choice

    def list_choices(self, user_id: str, run_id: str | None = None) -> list[ApplicationChoice]:
        with self._lock:
            return [item for item in self._choices.get(user_id, []) if run_id is None or item.run_id == run_id]

    def get_choice(self, user_id: str, run_id: str, program_slug: str) -> ApplicationChoice | None:
        with self._lock:
            return next((item for item in self._choices.get(user_id, []) if item.run_id == run_id and item.program_slug == program_slug), None)

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

    def save_feedback(self, feedback: FeedbackItem) -> FeedbackItem:
        with self._lock:
            self._feedback[feedback.id] = feedback
        return feedback

    def list_feedback(self, user_id: str | None = None) -> list[FeedbackItem]:
        with self._lock:
            items = [item for item in self._feedback.values() if user_id is None or item.user_id == user_id]
        return sorted(items, key=lambda item: item.created_at, reverse=True)

    def get_feedback(self, feedback_id: str) -> FeedbackItem | None:
        with self._lock:
            return self._feedback.get(feedback_id)

    def list_users(self) -> list[DemoUser]:
        with self._lock:
            return sorted(self._users.values(), key=lambda user: user.created_at or datetime.min.replace(tzinfo=UTC), reverse=True)

    def update_user_status(self, user_id: str, status: str) -> DemoUser | None:
        with self._lock:
            user = self._users.get(user_id)
            if not user:
                return None
            updated = user.model_copy(update={"status": status})
            self._users[user_id] = updated
            if status == "suspended":
                self._tokens = {key: value for key, value in self._tokens.items() if value[0] != user_id}
            return updated

    def admin_counts(self) -> dict[str, int]:
        with self._lock:
            return {
                "users": len(self._users),
                "verified_users": sum(user.email_verified for user in self._users.values()),
                "active_sessions": sum(expires > datetime.now(UTC) for _, expires in self._tokens.values()),
                "recommendation_runs": sum(len(items) for items in self._runs.values()),
                "advisor_threads": sum(len(items) for items in self._threads.values()),
                "open_feedback": sum(item.status != "resolved" for item in self._feedback.values()),
            }

    def healthcheck(self) -> bool:
        return True


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
                    password_hash TEXT,
                    email_verified_at TEXT,
                    role TEXT NOT NULL DEFAULT 'user',
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT,
                    last_login_at TEXT,
                    terms_accepted_at TEXT,
                    terms_version TEXT
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
                CREATE TABLE IF NOT EXISTS application_choices (
                    user_id TEXT NOT NULL REFERENCES users(id),
                    run_id TEXT NOT NULL,
                    program_slug TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, run_id, program_slug)
                );
                CREATE INDEX IF NOT EXISTS idx_choices_user_run
                    ON application_choices(user_id, run_id, updated_at DESC);
                CREATE TABLE IF NOT EXISTS agent_run_audits (
                    audit_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id),
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_audits_user_created
                    ON agent_run_audits(user_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS auth_tokens (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id),
                    purpose TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_at TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_auth_tokens_user_purpose
                    ON auth_tokens(user_id, purpose, expires_at DESC);
                CREATE TABLE IF NOT EXISTS feedback (
                    feedback_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id),
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            columns = {row[1] for row in self._connection.execute("PRAGMA table_info(users)").fetchall()}
            if "password_hash" not in columns:
                self._connection.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
            for name, definition in {
                "email_verified_at": "TEXT",
                "role": "TEXT NOT NULL DEFAULT 'user'",
                "status": "TEXT NOT NULL DEFAULT 'active'",
                "created_at": "TEXT",
                "last_login_at": "TEXT",
                "terms_accepted_at": "TEXT",
                "terms_version": "TEXT",
            }.items():
                if name not in columns:
                    self._connection.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")
            self._legacy_token_column = "token" in columns

    def register(self, email: str, password: str, display_name: str) -> tuple[DemoUser, str]:
        normalized = normalize_email(email)
        user_id = user_id_for_email(normalized)
        now = datetime.now(UTC)
        raw_token = new_auth_token()
        user = DemoUser(
            id=user_id, email=normalized, display_name=display_name.strip(), role=role_for_email(normalized),
            email_verified=False, status="active", created_at=now,
            terms_accepted_at=now, terms_version=TERMS_VERSION,
        )
        with self._lock, self._connection:
            if self._connection.execute("SELECT 1 FROM users WHERE email = ?", (normalized,)).fetchone():
                raise AccountExistsError("该邮箱已注册")
            self._connection.execute(
                """INSERT INTO users
                (id, email, display_name, password_hash, email_verified_at, role, status, created_at,
                 terms_accepted_at, terms_version)
                VALUES (?, ?, ?, ?, NULL, ?, 'active', ?, ?, ?)""",
                (user.id, user.email, user.display_name, hash_password(password), user.role, now.isoformat(),
                 now.isoformat(), TERMS_VERSION),
            )
            self._save_auth_token(user.id, "verify_email", raw_token, now + timedelta(hours=24))
        return user, raw_token

    def verify_email(self, token: str) -> DemoUser:
        with self._lock, self._connection:
            user_id = self._consume_auth_token(token, "verify_email")
            self._connection.execute("UPDATE users SET email_verified_at = ? WHERE id = ?", (datetime.now(UTC).isoformat(), user_id))
            row = self._connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return sqlite_user(row)

    def create_email_verification(self, email: str) -> tuple[DemoUser, str] | None:
        with self._lock, self._connection:
            row = self._connection.execute("SELECT * FROM users WHERE email = ?", (normalize_email(email),)).fetchone()
            if not row or row["email_verified_at"]:
                return None
            raw_token = new_auth_token()
            self._save_auth_token(row["id"], "verify_email", raw_token, datetime.now(UTC) + timedelta(hours=24))
        return sqlite_user(row), raw_token

    def login(self, email: str, password: str) -> tuple[str, DemoUser]:
        normalized = normalize_email(email)
        token = f"op_{secrets.token_urlsafe(32)}"
        with self._lock, self._connection:
            existing = self._connection.execute("SELECT * FROM users WHERE email = ?", (normalized,)).fetchone()
            if not existing or not existing["password_hash"] or not verify_password(password, existing["password_hash"]):
                raise InvalidCredentialsError("邮箱或密码不正确")
            user = sqlite_user(existing)
            ensure_login_allowed(user)
            now = datetime.now(UTC)
            self._connection.execute(
                "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
                (token_hash(token), user.id, (now + timedelta(hours=session_hours())).isoformat()),
            )
            self._connection.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now.isoformat(), user.id))
            user = user.model_copy(update={"last_login_at": now})
        return token, user

    def logout(self, token: str) -> None:
        with self._lock, self._connection:
            self._connection.execute("DELETE FROM sessions WHERE token = ?", (token_hash(token),))

    def create_password_reset(self, email: str) -> tuple[DemoUser, str] | None:
        with self._lock, self._connection:
            row = self._connection.execute("SELECT * FROM users WHERE email = ?", (normalize_email(email),)).fetchone()
            if not row:
                return None
            raw_token = new_auth_token()
            self._save_auth_token(row["id"], "reset_password", raw_token, datetime.now(UTC) + timedelta(minutes=30))
        return sqlite_user(row), raw_token

    def reset_password(self, token: str, password: str) -> None:
        with self._lock, self._connection:
            user_id = self._consume_auth_token(token, "reset_password")
            self._connection.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(password), user_id))
            self._connection.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

    def delete_account(self, user_id: str, password: str) -> None:
        with self._lock, self._connection:
            row = self._connection.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
            if not row or not verify_password(password, row["password_hash"]):
                raise InvalidCredentialsError("密码不正确")
            for table in ["feedback", "auth_tokens", "sessions", "profiles", "recommendation_runs", "advisor_threads", "application_choices", "application_tasks", "agent_run_audits"]:
                self._connection.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
            self._connection.execute("DELETE FROM users WHERE id = ?", (user_id,))

    def _save_auth_token(self, user_id: str, purpose: str, raw_token: str, expires_at: datetime) -> None:
        self._connection.execute("DELETE FROM auth_tokens WHERE user_id = ? AND purpose = ?", (user_id, purpose))
        self._connection.execute(
            "INSERT INTO auth_tokens (token_hash, user_id, purpose, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
            (token_hash(raw_token), user_id, purpose, expires_at.isoformat(), datetime.now(UTC).isoformat()),
        )

    def _consume_auth_token(self, raw_token: str, purpose: str) -> str:
        row = self._connection.execute(
            "SELECT * FROM auth_tokens WHERE token_hash = ? AND purpose = ? AND used_at IS NULL",
            (token_hash(raw_token), purpose),
        ).fetchone()
        if not row or datetime.fromisoformat(row["expires_at"]) <= datetime.now(UTC):
            raise InvalidAuthTokenError("链接无效或已过期")
        self._connection.execute("UPDATE auth_tokens SET used_at = ? WHERE token_hash = ?", (datetime.now(UTC).isoformat(), row["token_hash"]))
        return row["user_id"]

    def user_for_token(self, token: str) -> DemoUser | None:
        with self._lock:
            row = self._connection.execute(
                """SELECT users.id, users.email, users.display_name, sessions.expires_at
                FROM sessions JOIN users ON users.id = sessions.user_id WHERE sessions.token = ?""", (token_hash(token),)
            ).fetchone()
        if not row or datetime.fromisoformat(row["expires_at"]) <= datetime.now(UTC):
            return None
        with self._lock:
            user_row = self._connection.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
        user = sqlite_user(user_row)
        return user if user.status == "active" else None

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

    def save_choice(self, user_id: str, choice: ApplicationChoice) -> ApplicationChoice:
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO application_choices (user_id, run_id, program_slug, payload, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, run_id, program_slug) DO UPDATE SET
                    payload = excluded.payload, updated_at = excluded.updated_at""",
                (user_id, choice.run_id, choice.program_slug, choice.model_dump_json(), choice.updated_at.isoformat()),
            )
        return choice

    def list_choices(self, user_id: str, run_id: str | None = None) -> list[ApplicationChoice]:
        query = "SELECT payload FROM application_choices WHERE user_id = ?"
        params: tuple[str, ...] = (user_id,)
        if run_id is not None:
            query += " AND run_id = ?"
            params = (user_id, run_id)
        query += " ORDER BY updated_at DESC"
        with self._lock:
            rows = self._connection.execute(query, params).fetchall()
        return [ApplicationChoice.model_validate_json(row["payload"]) for row in rows]

    def get_choice(self, user_id: str, run_id: str, program_slug: str) -> ApplicationChoice | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT payload FROM application_choices WHERE user_id = ? AND run_id = ? AND program_slug = ?",
                (user_id, run_id, program_slug),
            ).fetchone()
        return ApplicationChoice.model_validate_json(row["payload"]) if row else None

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

    def save_feedback(self, feedback: FeedbackItem) -> FeedbackItem:
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO feedback (feedback_id, user_id, payload, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(feedback_id) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at""",
                (feedback.id, feedback.user_id, feedback.model_dump_json(), feedback.created_at.isoformat(), feedback.updated_at.isoformat()),
            )
        return feedback

    def list_feedback(self, user_id: str | None = None) -> list[FeedbackItem]:
        query = "SELECT payload FROM feedback"
        params: tuple[str, ...] = ()
        if user_id:
            query += " WHERE user_id = ?"
            params = (user_id,)
        query += " ORDER BY created_at DESC"
        with self._lock:
            rows = self._connection.execute(query, params).fetchall()
        return [FeedbackItem.model_validate_json(row["payload"]) for row in rows]

    def get_feedback(self, feedback_id: str) -> FeedbackItem | None:
        with self._lock:
            row = self._connection.execute("SELECT payload FROM feedback WHERE feedback_id = ?", (feedback_id,)).fetchone()
        return FeedbackItem.model_validate_json(row["payload"]) if row else None

    def list_users(self) -> list[DemoUser]:
        with self._lock:
            rows = self._connection.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
        return [sqlite_user(row) for row in rows]

    def update_user_status(self, user_id: str, status: str) -> DemoUser | None:
        with self._lock, self._connection:
            self._connection.execute("UPDATE users SET status = ? WHERE id = ?", (status, user_id))
            if status == "suspended":
                self._connection.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            row = self._connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return sqlite_user(row) if row else None

    def admin_counts(self) -> dict[str, int]:
        with self._lock:
            scalar = lambda query, params=(): int(self._connection.execute(query, params).fetchone()[0])
            return {
                "users": scalar("SELECT COUNT(*) FROM users"),
                "verified_users": scalar("SELECT COUNT(*) FROM users WHERE email_verified_at IS NOT NULL"),
                "active_sessions": scalar("SELECT COUNT(*) FROM sessions WHERE expires_at > ?", (datetime.now(UTC).isoformat(),)),
                "recommendation_runs": scalar("SELECT COUNT(*) FROM recommendation_runs"),
                "advisor_threads": scalar("SELECT COUNT(*) FROM advisor_threads"),
                "open_feedback": scalar("SELECT COUNT(*) FROM feedback WHERE json_extract(payload, '$.status') != 'resolved'"),
            }

    def healthcheck(self) -> bool:
        with self._lock:
            return self._connection.execute("SELECT 1").fetchone()[0] == 1


def create_store() -> Store:
    """Select PostgreSQL in production, SQLite locally, or memory for isolated tests."""
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        from .postgres_store import PostgresStore

        return PostgresStore(database_url)
    database_path = os.getenv("DATABASE_PATH")
    return SQLiteStore(database_path) if database_path else DemoStore()


def sqlite_user(row: sqlite3.Row) -> DemoUser:
    return DemoUser(
        id=row["id"],
        email=row["email"],
        display_name=row["display_name"],
        role=row["role"] or "user",
        email_verified=bool(row["email_verified_at"]),
        status=row["status"] or "active",
        created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
        last_login_at=datetime.fromisoformat(row["last_login_at"]) if row["last_login_at"] else None,
        terms_accepted_at=datetime.fromisoformat(row["terms_accepted_at"]) if row["terms_accepted_at"] else None,
        terms_version=row["terms_version"],
    )


store = create_store()
