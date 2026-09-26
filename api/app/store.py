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
    AIConsent,
    AgentRecommendationResponse,
    ApplicationChoice,
    ApplicationTask,
    AdvisorThread,
    AdvisorTurnRecord,
    ApplicantProfile,
    DemoUser,
    FeedbackItem,
    KnowledgeGapCandidate,
    ProgramSourceVersion,
    RecommendationRunSummary,
    advisor_turn_status_rank,
)
from .source_errors import (
    SourceVersionConflictError,
    SourceVersionNotFoundError,
    SourceVersionStateError,
)
from .store_errors import AdvisorThreadRevisionConflictError


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
    def save_thread(
        self,
        user_id: str,
        thread: AdvisorThread,
        expected_revision: int | None = None,
    ) -> AdvisorThread: ...
    def list_threads(self, user_id: str) -> list[AdvisorThread]: ...
    def get_thread(self, user_id: str, thread_id: str) -> AdvisorThread | None: ...
    def reserve_advisor_turn(self, user_id: str, turn: AdvisorTurnRecord) -> AdvisorTurnRecord: ...
    def save_advisor_turn(self, user_id: str, turn: AdvisorTurnRecord) -> AdvisorTurnRecord: ...
    def get_advisor_turn(self, user_id: str, request_id: str) -> AdvisorTurnRecord | None: ...
    def save_task(self, user_id: str, task: ApplicationTask) -> ApplicationTask: ...
    def list_tasks(self, user_id: str) -> list[ApplicationTask]: ...
    def get_task(self, user_id: str, task_id: str) -> ApplicationTask | None: ...
    def save_audit(self, user_id: str, audit: AgentRunAudit) -> AgentRunAudit: ...
    def list_audits(self, user_id: str) -> list[AgentRunAudit]: ...
    def save_ai_consent(self, user_id: str, consent: AIConsent) -> AIConsent: ...
    def get_ai_consent(self, user_id: str) -> AIConsent | None: ...
    def save_feedback(self, feedback: FeedbackItem) -> FeedbackItem: ...
    def list_feedback(self, user_id: str | None = None) -> list[FeedbackItem]: ...
    def get_feedback(self, feedback_id: str) -> FeedbackItem | None: ...
    def record_knowledge_gap(self, candidate: KnowledgeGapCandidate, event_id: str) -> KnowledgeGapCandidate: ...
    def list_knowledge_gaps(self) -> list[KnowledgeGapCandidate]: ...
    def update_knowledge_gap(self, candidate: KnowledgeGapCandidate, expected_revision: int) -> KnowledgeGapCandidate | None: ...
    def save_program_source_version(self, version: ProgramSourceVersion) -> ProgramSourceVersion: ...
    def get_program_source_version(self, version_id: str) -> ProgramSourceVersion | None: ...
    def list_program_source_versions(
        self, program_slug: str | None = None, status: str | None = None,
    ) -> list[ProgramSourceVersion]: ...
    def review_program_source_version(
        self, version_id: str, decision: str, reviewer_id: str, reviewed_at: datetime,
        review_note: str | None = None,
    ) -> ProgramSourceVersion: ...
    def list_users(self) -> list[DemoUser]: ...
    def update_user_status(self, user_id: str, status: str) -> DemoUser | None: ...
    def admin_counts(self) -> dict[str, int]: ...
    def admin_model_metrics(self) -> dict[str, int | float]: ...
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
        self._advisor_turns: dict[tuple[str, str], AdvisorTurnRecord] = {}
        self._tasks: dict[str, list[ApplicationTask]] = {}
        self._audits: dict[str, list[AgentRunAudit]] = {}
        self._ai_consents: dict[str, AIConsent] = {}
        self._feedback: dict[str, FeedbackItem] = {}
        self._knowledge_gaps: dict[str, KnowledgeGapCandidate] = {}
        self._knowledge_gap_events: set[tuple[str, str]] = set()
        self._program_source_versions: dict[str, ProgramSourceVersion] = {}

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
            self._advisor_turns = {
                key: value for key, value in self._advisor_turns.items() if key[0] != user_id
            }
            self._tasks.pop(user_id, None)
            self._audits.pop(user_id, None)
            self._ai_consents.pop(user_id, None)
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
            runs = self._runs.setdefault(user_id, [])
            existing = next((item for item in runs if item[0].run_id == result.run_id), None)
            if existing:
                summary = existing[0]
                runs[:] = [
                    (summary, result) if item[0].run_id == result.run_id else item
                    for item in runs
                ]
            else:
                runs.insert(0, (summary, result))
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
            if choice.is_primary:
                choices[:] = [
                    item.model_copy(update={"is_primary": False, "updated_at": choice.updated_at})
                    if item.run_id == choice.run_id and item.is_primary and item.program_slug != choice.program_slug
                    else item
                    for item in choices
                ]
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

    def save_thread(
        self,
        user_id: str,
        thread: AdvisorThread,
        expected_revision: int | None = None,
    ) -> AdvisorThread:
        with self._lock:
            threads = self._threads.setdefault(user_id, [])
            existing = next((item for item in threads if item.id == thread.id), None)
            actual_revision = existing.revision if existing else None
            if expected_revision is None:
                if existing:
                    raise AdvisorThreadRevisionConflictError(
                        thread.id,
                        expected_revision,
                        actual_revision,
                    )
                if thread.revision != 0:
                    raise ValueError("新顾问会话的 revision 必须为 0")
            else:
                if actual_revision != expected_revision:
                    raise AdvisorThreadRevisionConflictError(
                        thread.id,
                        expected_revision,
                        actual_revision,
                    )
                if thread.revision != expected_revision + 1:
                    raise ValueError("顾问会话 revision 必须单调增加 1")
            stored = thread.model_copy(deep=True)
            threads[:] = [item for item in threads if item.id != thread.id]
            threads.insert(0, stored)
        return stored.model_copy(deep=True)

    def list_threads(self, user_id: str) -> list[AdvisorThread]:
        with self._lock:
            return [item.model_copy(deep=True) for item in self._threads.get(user_id, [])]

    def get_thread(self, user_id: str, thread_id: str) -> AdvisorThread | None:
        with self._lock:
            thread = next(
                (item for item in self._threads.get(user_id, []) if item.id == thread_id),
                None,
            )
            return thread.model_copy(deep=True) if thread else None

    def reserve_advisor_turn(self, user_id: str, turn: AdvisorTurnRecord) -> AdvisorTurnRecord:
        key = (user_id, turn.request_id)
        with self._lock:
            existing = self._advisor_turns.get(key)
            if existing:
                return existing.model_copy(deep=True)
            self._advisor_turns[key] = turn.model_copy(deep=True)
        return turn.model_copy(deep=True)

    def save_advisor_turn(self, user_id: str, turn: AdvisorTurnRecord) -> AdvisorTurnRecord:
        key = (user_id, turn.request_id)
        with self._lock:
            existing = self._advisor_turns.get(key)
            if not existing:
                raise ValueError("顾问请求尚未预留")
            if advisor_turn_status_rank(existing.status) >= advisor_turn_status_rank(turn.status):
                return existing.model_copy(deep=True)
            self._advisor_turns[key] = turn.model_copy(deep=True)
        return turn.model_copy(deep=True)

    def get_advisor_turn(self, user_id: str, request_id: str) -> AdvisorTurnRecord | None:
        with self._lock:
            turn = self._advisor_turns.get((user_id, request_id))
            return turn.model_copy(deep=True) if turn else None

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
            audits = self._audits.setdefault(user_id, [])
            audits[:] = [item for item in audits if item.id != audit.id]
            audits.insert(0, audit)
        return audit

    def list_audits(self, user_id: str) -> list[AgentRunAudit]:
        with self._lock:
            return list(self._audits.get(user_id, []))

    def save_ai_consent(self, user_id: str, consent: AIConsent) -> AIConsent:
        with self._lock:
            self._ai_consents[user_id] = consent
        return consent

    def get_ai_consent(self, user_id: str) -> AIConsent | None:
        with self._lock:
            return self._ai_consents.get(user_id)

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

    def record_knowledge_gap(self, candidate: KnowledgeGapCandidate, event_id: str) -> KnowledgeGapCandidate:
        with self._lock:
            event_key = (candidate.id, event_id)
            existing = self._knowledge_gaps.get(candidate.id)
            if event_key not in self._knowledge_gap_events:
                self._knowledge_gap_events.add(event_key)
                candidate = candidate.model_copy(update={
                    "occurrence_count": (existing.occurrence_count if existing else 0) + 1,
                    "status": existing.status if existing else "new",
                    "created_at": existing.created_at if existing else candidate.created_at,
                    "updated_at": candidate.updated_at,
                })
                self._knowledge_gaps[candidate.id] = candidate
            return self._knowledge_gaps.get(candidate.id, candidate)

    def list_knowledge_gaps(self) -> list[KnowledgeGapCandidate]:
        with self._lock:
            items = list(self._knowledge_gaps.values())
        return sorted(items, key=lambda item: (item.occurrence_count, item.updated_at), reverse=True)

    def update_knowledge_gap(self, candidate: KnowledgeGapCandidate, expected_revision: int) -> KnowledgeGapCandidate | None:
        with self._lock:
            current = self._knowledge_gaps.get(candidate.id)
            if not current or current.revision != expected_revision:
                return None
            updated = candidate.model_copy(update={"revision": expected_revision + 1})
            self._knowledge_gaps[candidate.id] = updated
            return updated

    def save_program_source_version(self, version: ProgramSourceVersion) -> ProgramSourceVersion:
        with self._lock:
            existing = self._program_source_versions.get(version.version_id)
            if existing:
                return existing
            if version.status == "published" and any(
                item.program_slug == version.program_slug and item.status == "published"
                for item in self._program_source_versions.values()
            ):
                raise SourceVersionStateError("该项目已经存在发布版本")
            self._program_source_versions[version.version_id] = version
        return version

    def get_program_source_version(self, version_id: str) -> ProgramSourceVersion | None:
        with self._lock:
            return self._program_source_versions.get(version_id)

    def list_program_source_versions(
        self, program_slug: str | None = None, status: str | None = None,
    ) -> list[ProgramSourceVersion]:
        with self._lock:
            versions = [
                item for item in self._program_source_versions.values()
                if program_slug is None or item.program_slug == program_slug
            ]
            if status:
                versions = [item for item in versions if item.status == status]
        return sorted(versions, key=lambda item: item.submitted_at, reverse=True)

    def review_program_source_version(
        self,
        version_id: str,
        decision: str,
        reviewer_id: str,
        reviewed_at: datetime,
        review_note: str | None = None,
    ) -> ProgramSourceVersion:
        with self._lock:
            candidate = self._program_source_versions.get(version_id)
            if not candidate:
                raise SourceVersionNotFoundError("来源版本不存在")
            if candidate.status != "pending_review":
                raise SourceVersionStateError("只有待审核版本可以执行审核")
            if decision == "approve":
                current = next((
                    item for item in self._program_source_versions.values()
                    if item.program_slug == candidate.program_slug and item.status == "published"
                ), None)
                if not current or candidate.base_hash != current.content_hash:
                    raise SourceVersionConflictError("当前发布版本已变化，请重新生成差异")
                self._program_source_versions[current.version_id] = current.model_copy(update={
                    "status": "superseded",
                })
                reviewed = candidate.model_copy(update={
                    "status": "published",
                    "reviewed_by": reviewer_id,
                    "reviewed_at": reviewed_at,
                    "review_note": review_note,
                })
            else:
                reviewed = candidate.model_copy(update={
                    "status": "rejected",
                    "reviewed_by": reviewer_id,
                    "reviewed_at": reviewed_at,
                    "review_note": review_note,
                })
            self._program_source_versions[version_id] = reviewed
        return reviewed

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

    def admin_model_metrics(self) -> dict[str, int | float]:
        today = datetime.now(UTC).date()
        with self._lock:
            audits = [audit for items in self._audits.values() for audit in items if audit.created_at.date() == today]
        calls = len(audits)
        fallbacks = sum(audit.provider == "deterministic-fallback" for audit in audits)
        return {
            "llm_calls_today": calls,
            "llm_average_latency_ms": round(sum(audit.latency_ms for audit in audits) / calls) if calls else 0,
            "llm_fallback_rate": round(fallbacks / calls, 4) if calls else 0,
            "llm_input_tokens_today": sum(audit.input_tokens or 0 for audit in audits),
            "llm_output_tokens_today": sum(audit.output_tokens or 0 for audit in audits),
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
                CREATE TABLE IF NOT EXISTS advisor_turns (
                    user_id TEXT NOT NULL REFERENCES users(id),
                    request_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (
                        status IN ('reserved', 'planned', 'actions_applied', 'reply_ready', 'completed')
                    ),
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, request_id),
                    CHECK (length(content_hash) = 64)
                );
                CREATE INDEX IF NOT EXISTS idx_advisor_turns_user_updated
                    ON advisor_turns(user_id, updated_at DESC);
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
                CREATE TABLE IF NOT EXISTS ai_consents (
                    user_id TEXT PRIMARY KEY REFERENCES users(id),
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
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
                CREATE TABLE IF NOT EXISTS knowledge_gap_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    candidate_hash TEXT NOT NULL UNIQUE,
                    program_slug TEXT,
                    topic_class TEXT NOT NULL,
                    status TEXT NOT NULL,
                    occurrence_count INTEGER NOT NULL CHECK (occurrence_count >= 1),
                    source_version_id TEXT,
                    eval_dataset_hash TEXT,
                    eval_passed INTEGER,
                    review_note TEXT,
                    revision INTEGER NOT NULL CHECK (revision >= 0),
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS knowledge_gap_events (
                    candidate_id TEXT NOT NULL REFERENCES knowledge_gap_candidates(candidate_id),
                    event_id TEXT NOT NULL,
                    PRIMARY KEY (candidate_id, event_id)
                );
                CREATE TABLE IF NOT EXISTS program_source_versions (
                    version_id TEXT PRIMARY KEY,
                    program_slug TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    base_hash TEXT,
                    status TEXT NOT NULL CHECK (status IN ('pending_review', 'published', 'superseded', 'rejected')),
                    payload TEXT NOT NULL,
                    submitted_at TEXT NOT NULL,
                    reviewed_at TEXT,
                    CHECK (length(content_hash) = 64),
                    CHECK (base_hash IS NULL OR length(base_hash) = 64)
                );
                CREATE INDEX IF NOT EXISTS idx_source_versions_program_submitted
                    ON program_source_versions(program_slug, submitted_at DESC);
                CREATE INDEX IF NOT EXISTS idx_source_versions_program_status
                    ON program_source_versions(program_slug, status);
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
            for table in ["feedback", "auth_tokens", "sessions", "profiles", "recommendation_runs", "advisor_turns", "advisor_threads", "application_choices", "application_tasks", "agent_run_audits", "ai_consents"]:
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
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                if choice.is_primary:
                    rows = self._connection.execute(
                        "SELECT program_slug, payload FROM application_choices WHERE user_id = ? AND run_id = ?",
                        (user_id, choice.run_id),
                    ).fetchall()
                    for row in rows:
                        existing = ApplicationChoice.model_validate_json(row["payload"])
                        if existing.is_primary and existing.program_slug != choice.program_slug:
                            demoted = existing.model_copy(update={
                                "is_primary": False,
                                "updated_at": choice.updated_at,
                            })
                            self._connection.execute(
                                """UPDATE application_choices SET payload = ?, updated_at = ?
                                WHERE user_id = ? AND run_id = ? AND program_slug = ?""",
                                (
                                    demoted.model_dump_json(),
                                    demoted.updated_at.isoformat(),
                                    user_id,
                                    choice.run_id,
                                    demoted.program_slug,
                                ),
                            )
                self._connection.execute(
                    """INSERT INTO application_choices (user_id, run_id, program_slug, payload, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, run_id, program_slug) DO UPDATE SET
                        payload = excluded.payload, updated_at = excluded.updated_at""",
                    (user_id, choice.run_id, choice.program_slug, choice.model_dump_json(), choice.updated_at.isoformat()),
                )
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
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

    def save_thread(
        self,
        user_id: str,
        thread: AdvisorThread,
        expected_revision: int | None = None,
    ) -> AdvisorThread:
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                row = self._connection.execute(
                    "SELECT user_id, payload FROM advisor_threads WHERE thread_id = ?",
                    (thread.id,),
                ).fetchone()
                existing = (
                    AdvisorThread.model_validate_json(row["payload"])
                    if row and row["user_id"] == user_id
                    else None
                )
                actual_revision = existing.revision if existing else None
                if expected_revision is None:
                    if row:
                        raise AdvisorThreadRevisionConflictError(
                            thread.id,
                            expected_revision,
                            actual_revision,
                        )
                    if thread.revision != 0:
                        raise ValueError("新顾问会话的 revision 必须为 0")
                    self._connection.execute(
                        """INSERT INTO advisor_threads (thread_id, user_id, payload, updated_at)
                        VALUES (?, ?, ?, ?)""",
                        (
                            thread.id,
                            user_id,
                            thread.model_dump_json(),
                            thread.updated_at.isoformat(),
                        ),
                    )
                else:
                    if actual_revision != expected_revision:
                        raise AdvisorThreadRevisionConflictError(
                            thread.id,
                            expected_revision,
                            actual_revision,
                        )
                    if thread.revision != expected_revision + 1:
                        raise ValueError("顾问会话 revision 必须单调增加 1")
                    self._connection.execute(
                        """UPDATE advisor_threads
                        SET payload = ?, updated_at = ?
                        WHERE thread_id = ? AND user_id = ?""",
                        (
                            thread.model_dump_json(),
                            thread.updated_at.isoformat(),
                            thread.id,
                            user_id,
                        ),
                    )
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
        return thread.model_copy(deep=True)

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

    def reserve_advisor_turn(self, user_id: str, turn: AdvisorTurnRecord) -> AdvisorTurnRecord:
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT OR IGNORE INTO advisor_turns
                (user_id, request_id, thread_id, content_hash, status, payload, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    user_id,
                    turn.request_id,
                    turn.thread_id,
                    turn.content_hash,
                    turn.status,
                    turn.model_dump_json(),
                    turn.created_at.isoformat(),
                    turn.updated_at.isoformat(),
                ),
            )
            row = self._connection.execute(
                "SELECT payload FROM advisor_turns WHERE user_id = ? AND request_id = ?",
                (user_id, turn.request_id),
            ).fetchone()
        return AdvisorTurnRecord.model_validate_json(row["payload"])

    def save_advisor_turn(self, user_id: str, turn: AdvisorTurnRecord) -> AdvisorTurnRecord:
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT payload FROM advisor_turns WHERE user_id = ? AND request_id = ?",
                (user_id, turn.request_id),
            ).fetchone()
            if not row:
                raise ValueError("顾问请求尚未预留")
            existing = AdvisorTurnRecord.model_validate_json(row["payload"])
            if advisor_turn_status_rank(existing.status) >= advisor_turn_status_rank(turn.status):
                return existing
            self._connection.execute(
                """UPDATE advisor_turns
                SET thread_id = ?, content_hash = ?, status = ?, payload = ?, updated_at = ?
                WHERE user_id = ? AND request_id = ?""",
                (
                    turn.thread_id,
                    turn.content_hash,
                    turn.status,
                    turn.model_dump_json(),
                    turn.updated_at.isoformat(),
                    user_id,
                    turn.request_id,
                ),
            )
        return turn

    def get_advisor_turn(self, user_id: str, request_id: str) -> AdvisorTurnRecord | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT payload FROM advisor_turns WHERE user_id = ? AND request_id = ?",
                (user_id, request_id),
            ).fetchone()
        return AdvisorTurnRecord.model_validate_json(row["payload"]) if row else None

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

    def save_ai_consent(self, user_id: str, consent: AIConsent) -> AIConsent:
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO ai_consents (user_id, payload, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at""",
                (user_id, consent.model_dump_json(), consent.updated_at.isoformat()),
            )
        return consent

    def get_ai_consent(self, user_id: str) -> AIConsent | None:
        with self._lock:
            row = self._connection.execute("SELECT payload FROM ai_consents WHERE user_id = ?", (user_id,)).fetchone()
        return AIConsent.model_validate_json(row["payload"]) if row else None

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

    def record_knowledge_gap(self, candidate: KnowledgeGapCandidate, event_id: str) -> KnowledgeGapCandidate:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                event = self._connection.execute(
                    "SELECT 1 FROM knowledge_gap_events WHERE candidate_id = ? AND event_id = ?",
                    (candidate.id, event_id),
                ).fetchone()
                row = self._connection.execute(
                    "SELECT payload FROM knowledge_gap_candidates WHERE candidate_id = ?", (candidate.id,),
                ).fetchone()
                current = KnowledgeGapCandidate.model_validate_json(row["payload"]) if row else None
                if event:
                    self._connection.commit()
                    return current or candidate
                updated = candidate.model_copy(update={
                    "occurrence_count": (current.occurrence_count if current else 0) + 1,
                    "status": current.status if current else "new",
                    "revision": current.revision if current else 0,
                    "created_at": current.created_at if current else candidate.created_at,
                })
                self._connection.execute(
                    """INSERT INTO knowledge_gap_candidates
                    (candidate_id, candidate_hash, program_slug, topic_class, status, occurrence_count, revision, payload, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(candidate_id) DO UPDATE SET status=excluded.status,
                    occurrence_count=excluded.occurrence_count, revision=excluded.revision,
                    payload=excluded.payload, updated_at=excluded.updated_at""",
                    (updated.id, updated.candidate_hash, updated.program_slug, updated.topic_class, updated.status,
                     updated.occurrence_count, updated.revision, updated.model_dump_json(), updated.created_at.isoformat(), updated.updated_at.isoformat()),
                )
                self._connection.execute(
                    "INSERT INTO knowledge_gap_events(candidate_id, event_id) VALUES (?, ?)", (candidate.id, event_id),
                )
                self._connection.commit()
                return updated
            except Exception:
                self._connection.rollback()
                raise

    def list_knowledge_gaps(self) -> list[KnowledgeGapCandidate]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT payload FROM knowledge_gap_candidates ORDER BY occurrence_count DESC, updated_at DESC",
            ).fetchall()
        return [KnowledgeGapCandidate.model_validate_json(row["payload"]) for row in rows]

    def update_knowledge_gap(self, candidate: KnowledgeGapCandidate, expected_revision: int) -> KnowledgeGapCandidate | None:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._connection.execute(
                    "SELECT revision FROM knowledge_gap_candidates WHERE candidate_id = ?", (candidate.id,),
                ).fetchone()
                if not row or row["revision"] != expected_revision:
                    self._connection.rollback()
                    return None
                updated = candidate.model_copy(update={"revision": expected_revision + 1})
                result = self._connection.execute(
                    """UPDATE knowledge_gap_candidates SET status=?, source_version_id=?, eval_dataset_hash=?, eval_passed=?,
                    review_note=?, revision=?, payload=?, updated_at=? WHERE candidate_id=? AND revision=?""",
                    (updated.status, updated.source_version_id, updated.eval_dataset_hash, updated.eval_passed,
                     updated.review_note, updated.revision, updated.model_dump_json(), updated.updated_at.isoformat(),
                     updated.id, expected_revision),
                )
                if result.rowcount != 1:
                    self._connection.rollback()
                    return None
                self._connection.commit()
                return updated
            except Exception:
                self._connection.rollback()
                raise

    def save_program_source_version(self, version: ProgramSourceVersion) -> ProgramSourceVersion:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._connection.execute(
                    "SELECT payload FROM program_source_versions WHERE version_id = ?",
                    (version.version_id,),
                ).fetchone()
                if row:
                    self._connection.commit()
                    return ProgramSourceVersion.model_validate_json(row["payload"])
                if version.status == "published" and self._connection.execute(
                    "SELECT 1 FROM program_source_versions WHERE program_slug = ? AND status = 'published'",
                    (version.program_slug,),
                ).fetchone():
                    raise SourceVersionStateError("该项目已经存在发布版本")
                self._connection.execute(
                    """INSERT INTO program_source_versions
                    (version_id, program_slug, source_id, content_hash, base_hash, status, payload, submitted_at, reviewed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        version.version_id,
                        version.program_slug,
                        version.source_id,
                        version.content_hash,
                        version.base_hash,
                        version.status,
                        version.model_dump_json(),
                        version.submitted_at.isoformat(),
                        version.reviewed_at.isoformat() if version.reviewed_at else None,
                    ),
                )
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
        return version

    def get_program_source_version(self, version_id: str) -> ProgramSourceVersion | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT payload FROM program_source_versions WHERE version_id = ?",
                (version_id,),
            ).fetchone()
        return ProgramSourceVersion.model_validate_json(row["payload"]) if row else None

    def list_program_source_versions(
        self, program_slug: str | None = None, status: str | None = None,
    ) -> list[ProgramSourceVersion]:
        query = "SELECT payload FROM program_source_versions"
        conditions: list[str] = []
        params: list[str] = []
        if program_slug:
            conditions.append("program_slug = ?")
            params.append(program_slug)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY submitted_at DESC"
        with self._lock:
            rows = self._connection.execute(query, params).fetchall()
        return [ProgramSourceVersion.model_validate_json(row["payload"]) for row in rows]

    def review_program_source_version(
        self,
        version_id: str,
        decision: str,
        reviewer_id: str,
        reviewed_at: datetime,
        review_note: str | None = None,
    ) -> ProgramSourceVersion:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._connection.execute(
                    "SELECT payload FROM program_source_versions WHERE version_id = ?",
                    (version_id,),
                ).fetchone()
                if not row:
                    raise SourceVersionNotFoundError("来源版本不存在")
                candidate = ProgramSourceVersion.model_validate_json(row["payload"])
                if candidate.status != "pending_review":
                    raise SourceVersionStateError("只有待审核版本可以执行审核")
                if decision == "approve":
                    current_row = self._connection.execute(
                        """SELECT version_id, payload FROM program_source_versions
                        WHERE program_slug = ? AND status = 'published'""",
                        (candidate.program_slug,),
                    ).fetchone()
                    current = ProgramSourceVersion.model_validate_json(current_row["payload"]) if current_row else None
                    if not current or candidate.base_hash != current.content_hash:
                        raise SourceVersionConflictError("当前发布版本已变化，请重新生成差异")
                    superseded = current.model_copy(update={"status": "superseded"})
                    self._connection.execute(
                        "UPDATE program_source_versions SET status = ?, payload = ? WHERE version_id = ?",
                        (superseded.status, superseded.model_dump_json(), superseded.version_id),
                    )
                    reviewed = candidate.model_copy(update={
                        "status": "published",
                        "reviewed_by": reviewer_id,
                        "reviewed_at": reviewed_at,
                        "review_note": review_note,
                    })
                else:
                    reviewed = candidate.model_copy(update={
                        "status": "rejected",
                        "reviewed_by": reviewer_id,
                        "reviewed_at": reviewed_at,
                        "review_note": review_note,
                    })
                self._connection.execute(
                    """UPDATE program_source_versions
                    SET status = ?, payload = ?, reviewed_at = ? WHERE version_id = ?""",
                    (reviewed.status, reviewed.model_dump_json(), reviewed_at.isoformat(), reviewed.version_id),
                )
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
        return reviewed

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

    def admin_model_metrics(self) -> dict[str, int | float]:
        today = datetime.now(UTC).date().isoformat()
        with self._lock:
            row = self._connection.execute(
                """SELECT COUNT(*) AS calls,
                COALESCE(AVG(CAST(json_extract(payload, '$.latency_ms') AS INTEGER)), 0) AS latency,
                COALESCE(SUM(CASE WHEN json_extract(payload, '$.provider') = 'deterministic-fallback' THEN 1 ELSE 0 END), 0) AS fallbacks,
                COALESCE(SUM(CAST(json_extract(payload, '$.input_tokens') AS INTEGER)), 0) AS input_tokens,
                COALESCE(SUM(CAST(json_extract(payload, '$.output_tokens') AS INTEGER)), 0) AS output_tokens
                FROM agent_run_audits WHERE substr(created_at, 1, 10) = ?""",
                (today,),
            ).fetchone()
        calls = int(row["calls"])
        return {
            "llm_calls_today": calls,
            "llm_average_latency_ms": round(float(row["latency"])),
            "llm_fallback_rate": round(int(row["fallbacks"]) / calls, 4) if calls else 0,
            "llm_input_tokens_today": int(row["input_tokens"]),
            "llm_output_tokens_today": int(row["output_tokens"]),
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
