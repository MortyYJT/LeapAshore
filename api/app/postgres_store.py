from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import secrets
from threading import Lock
from time import perf_counter
from typing import Any, TypeVar

from pydantic import BaseModel

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
from .observability import (
    record_postgres_advisory_lock_wait,
    record_postgres_connection_slot_wait,
    record_postgres_transaction,
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
POSTGRES_SCHEMA_REVISIONS = frozenset({"0005_knowledge_gaps"})


class _MeasuredConnectionLock:
    """Serialize one psycopg connection and expose process-local queue time."""

    def __init__(self) -> None:
        self._lock = Lock()

    def __enter__(self) -> "_MeasuredConnectionLock":
        started = perf_counter()
        self._lock.acquire()
        try:
            record_postgres_connection_slot_wait(perf_counter() - started)
        except BaseException:
            self._lock.release()
            raise
        return self

    def __exit__(self, *_args: object) -> None:
        self._lock.release()


def verify_postgres_schema(cursor: Any) -> None:
    """Require the database to be migrated before the application starts."""
    try:
        cursor.execute("SELECT version_num FROM alembic_version")
        actual_revisions = frozenset(row["version_num"] for row in cursor.fetchall())
    except Exception as error:
        raise RuntimeError(
            "PostgreSQL schema is not initialized by Alembic. "
            "Run `alembic upgrade head` before starting OfferPilot."
        ) from error

    if actual_revisions != POSTGRES_SCHEMA_REVISIONS:
        expected = ", ".join(sorted(POSTGRES_SCHEMA_REVISIONS))
        actual = ", ".join(sorted(actual_revisions)) or "(none)"
        raise RuntimeError(
            "PostgreSQL schema revision mismatch: "
            f"expected {expected}, found {actual}. "
            "Run `alembic upgrade head` before starting OfferPilot."
        )


class PostgresStore:
    """Production adapter using PostgreSQL JSONB for versionable product entities."""

    def __init__(self, database_url: str) -> None:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as error:  # pragma: no cover - only reachable in a misconfigured deployment
            raise RuntimeError("DATABASE_URL requires the psycopg dependency") from error
        self._lock = _MeasuredConnectionLock()
        self._connection = psycopg.connect(database_url, autocommit=True, row_factory=dict_row)
        try:
            with self._connection.cursor() as cursor:
                verify_postgres_schema(cursor)
        except Exception:
            self._connection.close()
            raise

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        started = perf_counter()
        outcome = "success"
        try:
            with self._connection.transaction():
                yield
        except BaseException:
            outcome = "error"
            raise
        finally:
            record_postgres_transaction(outcome, perf_counter() - started)

    @staticmethod
    def _acquire_advisory_lock(cursor: Any, key: str) -> None:
        started = perf_counter()
        outcome = "success"
        try:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (key,),
            )
        except BaseException:
            outcome = "error"
            raise
        finally:
            record_postgres_advisory_lock_wait(outcome, perf_counter() - started)

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

    def save_choice(self, user_id: str, choice: ApplicationChoice) -> ApplicationChoice:
        from psycopg.types.json import Jsonb

        now = datetime.now(UTC)
        entity_id = f"{choice.run_id}:{choice.program_slug}"
        with self._lock, self._transaction(), self._connection.cursor() as cursor:
            # The advisory lock makes the one-primary invariant hold across API instances.
            self._acquire_advisory_lock(cursor, f"{user_id}:{choice.run_id}")
            if choice.is_primary:
                cursor.execute(
                    """UPDATE entities
                    SET payload = jsonb_set(payload, '{is_primary}', 'false'::jsonb), updated_at = %s
                    WHERE user_id = %s AND kind = 'application_choice'
                      AND payload->>'run_id' = %s AND payload->>'is_primary' = 'true'
                      AND entity_id <> %s""",
                    (now, user_id, choice.run_id, entity_id),
                )
            cursor.execute(
                """INSERT INTO entities (user_id, kind, entity_id, payload, created_at, updated_at)
                VALUES (%s, 'application_choice', %s, %s, %s, %s)
                ON CONFLICT (user_id, kind, entity_id) DO UPDATE
                SET payload = EXCLUDED.payload, updated_at = EXCLUDED.updated_at""",
                (user_id, entity_id, Jsonb(choice.model_dump(mode="json")), now, now),
            )
        return choice

    def list_choices(self, user_id: str, run_id: str | None = None) -> list[ApplicationChoice]:
        choices = self._list_entities(user_id, "application_choice", ApplicationChoice)
        return [choice for choice in choices if run_id is None or choice.run_id == run_id]

    def get_choice(self, user_id: str, run_id: str, program_slug: str) -> ApplicationChoice | None:
        return self._get_entity(user_id, "application_choice", f"{run_id}:{program_slug}", ApplicationChoice)

    def save_thread(
        self,
        user_id: str,
        thread: AdvisorThread,
        expected_revision: int | None = None,
    ) -> AdvisorThread:
        from psycopg.types.json import Jsonb
        from .agent_store.events import advisor_thread_changed_event

        if expected_revision is None and thread.revision != 0:
            raise ValueError("新顾问会话的 revision 必须为 0")
        if expected_revision is not None and thread.revision != expected_revision + 1:
            raise ValueError("顾问会话 revision 必须单调增加 1")

        with self._lock, self._transaction(), self._connection.cursor() as cursor:
            if expected_revision is None:
                cursor.execute(
                    """INSERT INTO entities
                    (user_id, kind, entity_id, payload, created_at, updated_at)
                    VALUES (%s, 'advisor_thread', %s, %s, %s, %s)
                    ON CONFLICT (user_id, kind, entity_id) DO NOTHING
                    RETURNING payload""",
                    (
                        user_id,
                        thread.id,
                        Jsonb(thread.model_dump(mode="json")),
                        thread.created_at,
                        thread.updated_at,
                    ),
                )
            else:
                cursor.execute(
                    """UPDATE entities
                    SET payload = %s, updated_at = %s
                    WHERE user_id = %s
                      AND kind = 'advisor_thread'
                      AND entity_id = %s
                      AND COALESCE((payload->>'revision')::INTEGER, 0) = %s
                    RETURNING payload""",
                    (
                        Jsonb(thread.model_dump(mode="json")),
                        thread.updated_at,
                        user_id,
                        thread.id,
                        expected_revision,
                    ),
                )
            saved = cursor.fetchone()
            if not saved:
                cursor.execute(
                    """SELECT payload FROM entities
                    WHERE user_id = %s AND kind = 'advisor_thread' AND entity_id = %s""",
                    (user_id, thread.id),
                )
                row = cursor.fetchone()
                actual_revision = (
                    AdvisorThread.model_validate(row["payload"]).revision
                    if row
                    else None
                )
                raise AdvisorThreadRevisionConflictError(
                    thread.id,
                    expected_revision,
                    actual_revision,
                )
            event = advisor_thread_changed_event(user_id, thread.id, thread.revision, len(thread.messages))
            cursor.execute(
                """INSERT INTO agent_projection_outbox
                (event_id, event_type, schema_version, aggregate_type, aggregate_id,
                 source_revision, payload, occurred_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (event_id) DO NOTHING""",
                (
                    event["event_id"], event["event_type"], event["schema_version"],
                    event["aggregate_type"], event["aggregate_id"], event["source_revision"],
                    Jsonb(event["payload"]), event["occurred_at"],
                ),
            )
        return thread.model_copy(deep=True)

    def claim_projection_events(
        self,
        worker_id: str,
        *,
        limit: int = 50,
        lease_seconds: int = 30,
        aggregate_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if not worker_id or len(worker_id) > 128 or not 1 <= limit <= 500 or not 1 <= lease_seconds <= 3600:
            raise ValueError("invalid projection lease parameters")
        with self._lock, self._transaction(), self._connection.cursor() as cursor:
            aggregate_clause = "AND aggregate_id = %s" if aggregate_id is not None else ""
            parameters = (aggregate_id, limit, worker_id, lease_seconds) if aggregate_id is not None else (limit, worker_id, lease_seconds)
            cursor.execute(
                f"""WITH candidates AS (
                    SELECT event_id FROM agent_projection_outbox
                    WHERE acknowledged_at IS NULL AND available_at <= NOW()
                      AND (lease_expires_at IS NULL OR lease_expires_at < NOW())
                      {aggregate_clause}
                    ORDER BY created_at, event_id
                    FOR UPDATE SKIP LOCKED
                    LIMIT %s
                )
                UPDATE agent_projection_outbox AS outbox
                SET lease_owner = %s,
                    lease_expires_at = NOW() + (%s * INTERVAL '1 second'),
                    attempts = attempts + 1
                FROM candidates
                WHERE outbox.event_id = candidates.event_id
                RETURNING outbox.event_id, outbox.event_type, outbox.schema_version,
                          outbox.aggregate_type, outbox.aggregate_id, outbox.source_revision,
                          outbox.payload, outbox.occurred_at, outbox.attempts""",
                parameters,
            )
            return cursor.fetchall()

    def acknowledge_projection_event(self, worker_id: str, event_id: str) -> bool:
        with self._lock, self._transaction(), self._connection.cursor() as cursor:
            cursor.execute(
                """UPDATE agent_projection_outbox
                SET acknowledged_at = NOW(), lease_owner = NULL, lease_expires_at = NULL,
                    last_error_class = NULL
                WHERE event_id = %s AND lease_owner = %s AND acknowledged_at IS NULL
                RETURNING event_id""",
                (event_id, worker_id),
            )
            return cursor.fetchone() is not None

    def retry_projection_event(self, worker_id: str, event_id: str, *, error_class: str, delay_seconds: int = 10) -> bool:
        safe_error_class = "".join(character for character in error_class if character.isalnum() or character in "._-")[:80]
        if not safe_error_class or not 1 <= delay_seconds <= 3600:
            raise ValueError("invalid projection retry parameters")
        with self._lock, self._transaction(), self._connection.cursor() as cursor:
            cursor.execute(
                """UPDATE agent_projection_outbox
                SET available_at = NOW() + (%s * INTERVAL '1 second'),
                    lease_owner = NULL, lease_expires_at = NULL, last_error_class = %s
                WHERE event_id = %s AND lease_owner = %s AND acknowledged_at IS NULL
                RETURNING event_id""",
                (delay_seconds, safe_error_class, event_id, worker_id),
            )
            return cursor.fetchone() is not None

    def list_threads(self, user_id: str) -> list[AdvisorThread]:
        return self._list_entities(user_id, "advisor_thread", AdvisorThread)

    def get_thread(self, user_id: str, thread_id: str) -> AdvisorThread | None:
        return self._get_entity(user_id, "advisor_thread", thread_id, AdvisorThread)

    def reserve_advisor_turn(self, user_id: str, turn: AdvisorTurnRecord) -> AdvisorTurnRecord:
        from psycopg.types.json import Jsonb

        with self._lock, self._transaction(), self._connection.cursor() as cursor:
            self._acquire_advisory_lock(cursor, f"advisor-turn:{user_id}:{turn.request_id}")
            cursor.execute(
                """SELECT payload FROM entities
                WHERE user_id = %s AND kind = 'advisor_turn' AND entity_id = %s""",
                (user_id, turn.request_id),
            )
            row = cursor.fetchone()
            if row:
                return AdvisorTurnRecord.model_validate(row["payload"])
            cursor.execute(
                """INSERT INTO entities (user_id, kind, entity_id, payload, created_at, updated_at)
                VALUES (%s, 'advisor_turn', %s, %s, %s, %s)""",
                (
                    user_id,
                    turn.request_id,
                    Jsonb(turn.model_dump(mode="json")),
                    turn.created_at,
                    turn.updated_at,
                ),
            )
        return turn

    def save_advisor_turn(self, user_id: str, turn: AdvisorTurnRecord) -> AdvisorTurnRecord:
        from psycopg.types.json import Jsonb

        with self._lock, self._transaction(), self._connection.cursor() as cursor:
            self._acquire_advisory_lock(cursor, f"advisor-turn:{user_id}:{turn.request_id}")
            cursor.execute(
                """SELECT payload FROM entities
                WHERE user_id = %s AND kind = 'advisor_turn' AND entity_id = %s""",
                (user_id, turn.request_id),
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError("顾问请求尚未预留")
            existing = AdvisorTurnRecord.model_validate(row["payload"])
            if advisor_turn_status_rank(existing.status) >= advisor_turn_status_rank(turn.status):
                return existing
            cursor.execute(
                """UPDATE entities SET payload = %s, updated_at = %s
                WHERE user_id = %s AND kind = 'advisor_turn' AND entity_id = %s""",
                (
                    Jsonb(turn.model_dump(mode="json")),
                    turn.updated_at,
                    user_id,
                    turn.request_id,
                ),
            )
        return turn

    def get_advisor_turn(self, user_id: str, request_id: str) -> AdvisorTurnRecord | None:
        return self._get_entity(user_id, "advisor_turn", request_id, AdvisorTurnRecord)

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

    def save_ai_consent(self, user_id: str, consent: AIConsent) -> AIConsent:
        self._save_entity(user_id, "ai_consent", "deepseek", consent, consent.updated_at)
        return consent

    def get_ai_consent(self, user_id: str) -> AIConsent | None:
        return self._get_entity(user_id, "ai_consent", "deepseek", AIConsent)

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

    def record_knowledge_gap(self, candidate: KnowledgeGapCandidate, event_id: str) -> KnowledgeGapCandidate:
        from psycopg.types.json import Jsonb

        with self._lock, self._transaction(), self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM knowledge_gap_events WHERE candidate_id = %s AND event_id = %s",
                (candidate.id, event_id),
            )
            if cursor.fetchone():
                cursor.execute("SELECT payload FROM knowledge_gap_candidates WHERE candidate_id = %s", (candidate.id,))
                row = cursor.fetchone()
                return KnowledgeGapCandidate.model_validate(row["payload"]) if row else candidate
            cursor.execute(
                "SELECT payload FROM knowledge_gap_candidates WHERE candidate_id = %s FOR UPDATE", (candidate.id,),
            )
            row = cursor.fetchone()
            current = KnowledgeGapCandidate.model_validate(row["payload"]) if row else None
            updated = candidate.model_copy(update={
                "occurrence_count": (current.occurrence_count if current else 0) + 1,
                "status": current.status if current else "new",
                "revision": current.revision if current else 0,
                "created_at": current.created_at if current else candidate.created_at,
            })
            cursor.execute(
                """INSERT INTO knowledge_gap_candidates
                (candidate_id, candidate_hash, program_slug, topic_class, status, occurrence_count, revision, payload, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (candidate_id) DO UPDATE SET status=EXCLUDED.status,
                occurrence_count=EXCLUDED.occurrence_count, revision=EXCLUDED.revision,
                payload=EXCLUDED.payload, updated_at=EXCLUDED.updated_at""",
                (updated.id, updated.candidate_hash, updated.program_slug, updated.topic_class, updated.status,
                 updated.occurrence_count, updated.revision, Jsonb(updated.model_dump(mode="json")), updated.created_at, updated.updated_at),
            )
            cursor.execute(
                "INSERT INTO knowledge_gap_events(candidate_id, event_id) VALUES (%s, %s)", (candidate.id, event_id),
            )
            return updated

    def list_knowledge_gaps(self) -> list[KnowledgeGapCandidate]:
        with self._lock, self._connection.cursor() as cursor:
            cursor.execute("SELECT payload FROM knowledge_gap_candidates ORDER BY occurrence_count DESC, updated_at DESC")
            rows = cursor.fetchall()
        return [KnowledgeGapCandidate.model_validate(row["payload"]) for row in rows]

    def update_knowledge_gap(self, candidate: KnowledgeGapCandidate, expected_revision: int) -> KnowledgeGapCandidate | None:
        from psycopg.types.json import Jsonb

        with self._lock, self._transaction(), self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT revision FROM knowledge_gap_candidates WHERE candidate_id = %s FOR UPDATE", (candidate.id,),
            )
            row = cursor.fetchone()
            if not row or row["revision"] != expected_revision:
                return None
            updated = candidate.model_copy(update={"revision": expected_revision + 1})
            cursor.execute(
                """UPDATE knowledge_gap_candidates SET status=%s, source_version_id=%s, eval_dataset_hash=%s,
                eval_passed=%s, review_note=%s, revision=%s, payload=%s, updated_at=%s
                WHERE candidate_id=%s AND revision=%s""",
                (updated.status, updated.source_version_id, updated.eval_dataset_hash, updated.eval_passed,
                 updated.review_note, updated.revision, Jsonb(updated.model_dump(mode="json")), updated.updated_at,
                 updated.id, expected_revision),
            )
            if cursor.rowcount != 1:
                return None
            return updated

    def save_program_source_version(self, version: ProgramSourceVersion) -> ProgramSourceVersion:
        from psycopg.types.json import Jsonb

        with self._lock, self._transaction(), self._connection.cursor() as cursor:
            self._acquire_advisory_lock(cursor, f"program-source:{version.program_slug}")
            cursor.execute(
                "SELECT payload FROM program_source_versions WHERE version_id = %s",
                (version.version_id,),
            )
            row = cursor.fetchone()
            if row:
                return ProgramSourceVersion.model_validate(row["payload"])
            if version.status == "published":
                cursor.execute(
                    "SELECT 1 FROM program_source_versions WHERE program_slug = %s AND status = 'published'",
                    (version.program_slug,),
                )
                if cursor.fetchone():
                    raise SourceVersionStateError("该项目已经存在发布版本")
            cursor.execute(
                """INSERT INTO program_source_versions
                (version_id, program_slug, source_id, content_hash, base_hash, status, payload, submitted_at, reviewed_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    version.version_id,
                    version.program_slug,
                    version.source_id,
                    version.content_hash,
                    version.base_hash,
                    version.status,
                    Jsonb(version.model_dump(mode="json")),
                    version.submitted_at,
                    version.reviewed_at,
                ),
            )
        return version

    def get_program_source_version(self, version_id: str) -> ProgramSourceVersion | None:
        with self._lock, self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT payload FROM program_source_versions WHERE version_id = %s",
                (version_id,),
            )
            row = cursor.fetchone()
        return ProgramSourceVersion.model_validate(row["payload"]) if row else None

    def list_program_source_versions(
        self, program_slug: str | None = None, status: str | None = None,
    ) -> list[ProgramSourceVersion]:
        with self._lock, self._connection.cursor() as cursor:
            if program_slug and status:
                cursor.execute(
                    """SELECT payload FROM program_source_versions
                    WHERE program_slug = %s AND status = %s ORDER BY submitted_at DESC""",
                    (program_slug, status),
                )
            elif program_slug:
                cursor.execute(
                    """SELECT payload FROM program_source_versions
                    WHERE program_slug = %s ORDER BY submitted_at DESC""",
                    (program_slug,),
                )
            elif status:
                cursor.execute(
                    """SELECT payload FROM program_source_versions
                    WHERE status = %s ORDER BY submitted_at DESC""",
                    (status,),
                )
            else:
                cursor.execute("SELECT payload FROM program_source_versions ORDER BY submitted_at DESC")
            rows = cursor.fetchall()
        return [ProgramSourceVersion.model_validate(row["payload"]) for row in rows]

    def review_program_source_version(
        self,
        version_id: str,
        decision: str,
        reviewer_id: str,
        reviewed_at: datetime,
        review_note: str | None = None,
    ) -> ProgramSourceVersion:
        from psycopg.types.json import Jsonb

        with self._lock, self._transaction(), self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT payload FROM program_source_versions WHERE version_id = %s FOR UPDATE",
                (version_id,),
            )
            row = cursor.fetchone()
            if not row:
                raise SourceVersionNotFoundError("来源版本不存在")
            candidate = ProgramSourceVersion.model_validate(row["payload"])
            self._acquire_advisory_lock(cursor, f"program-source:{candidate.program_slug}")
            if candidate.status != "pending_review":
                raise SourceVersionStateError("只有待审核版本可以执行审核")
            if decision == "approve":
                cursor.execute(
                    """SELECT version_id, payload FROM program_source_versions
                    WHERE program_slug = %s AND status = 'published' FOR UPDATE""",
                    (candidate.program_slug,),
                )
                current_row = cursor.fetchone()
                current = ProgramSourceVersion.model_validate(current_row["payload"]) if current_row else None
                if not current or candidate.base_hash != current.content_hash:
                    raise SourceVersionConflictError("当前发布版本已变化，请重新生成差异")
                superseded = current.model_copy(update={"status": "superseded"})
                cursor.execute(
                    "UPDATE program_source_versions SET status = %s, payload = %s WHERE version_id = %s",
                    (superseded.status, Jsonb(superseded.model_dump(mode="json")), superseded.version_id),
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
            cursor.execute(
                """UPDATE program_source_versions
                SET status = %s, payload = %s, reviewed_at = %s WHERE version_id = %s""",
                (
                    reviewed.status,
                    Jsonb(reviewed.model_dump(mode="json")),
                    reviewed_at,
                    reviewed.version_id,
                ),
            )
        return reviewed

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

    def admin_model_metrics(self) -> dict[str, int | float]:
        with self._lock, self._connection.cursor() as cursor:
            cursor.execute(
                """SELECT COUNT(*) AS calls,
                COALESCE(AVG((payload->>'latency_ms')::INTEGER), 0) AS latency,
                COUNT(*) FILTER (WHERE payload->>'provider' = 'deterministic-fallback') AS fallbacks,
                COALESCE(SUM((payload->>'input_tokens')::INTEGER), 0) AS input_tokens,
                COALESCE(SUM((payload->>'output_tokens')::INTEGER), 0) AS output_tokens
                FROM entities WHERE kind = 'agent_audit' AND created_at >= CURRENT_DATE"""
            )
            row = cursor.fetchone()
        calls = int(row["calls"])
        return {
            "llm_calls_today": calls,
            "llm_average_latency_ms": round(float(row["latency"])),
            "llm_fallback_rate": round(int(row["fallbacks"]) / calls, 4) if calls else 0,
            "llm_input_tokens_today": int(row["input_tokens"]),
            "llm_output_tokens_today": int(row["output_tokens"]),
        }

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
