from __future__ import annotations

from datetime import UTC, datetime, timedelta
import secrets
from threading import Lock
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
                CREATE TABLE IF NOT EXISTS program_source_versions (
                    version_id TEXT PRIMARY KEY, program_slug TEXT NOT NULL, source_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
                    base_hash TEXT CHECK (base_hash IS NULL OR length(base_hash) = 64),
                    status TEXT NOT NULL CHECK (status IN ('pending_review', 'published', 'superseded', 'rejected')),
                    payload JSONB NOT NULL, submitted_at TIMESTAMPTZ NOT NULL, reviewed_at TIMESTAMPTZ
                );
                CREATE INDEX IF NOT EXISTS idx_source_versions_program_submitted
                    ON program_source_versions(program_slug, submitted_at DESC);
                CREATE INDEX IF NOT EXISTS idx_source_versions_program_status
                    ON program_source_versions(program_slug, status);
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

    def save_choice(self, user_id: str, choice: ApplicationChoice) -> ApplicationChoice:
        from psycopg.types.json import Jsonb

        now = datetime.now(UTC)
        entity_id = f"{choice.run_id}:{choice.program_slug}"
        with self._lock, self._connection.transaction(), self._connection.cursor() as cursor:
            # The advisory lock makes the one-primary invariant hold across API instances.
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"{user_id}:{choice.run_id}",),
            )
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

        if expected_revision is None and thread.revision != 0:
            raise ValueError("新顾问会话的 revision 必须为 0")
        if expected_revision is not None and thread.revision != expected_revision + 1:
            raise ValueError("顾问会话 revision 必须单调增加 1")

        with self._lock, self._connection.transaction(), self._connection.cursor() as cursor:
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
        return thread.model_copy(deep=True)

    def list_threads(self, user_id: str) -> list[AdvisorThread]:
        return self._list_entities(user_id, "advisor_thread", AdvisorThread)

    def get_thread(self, user_id: str, thread_id: str) -> AdvisorThread | None:
        return self._get_entity(user_id, "advisor_thread", thread_id, AdvisorThread)

    def reserve_advisor_turn(self, user_id: str, turn: AdvisorTurnRecord) -> AdvisorTurnRecord:
        from psycopg.types.json import Jsonb

        with self._lock, self._connection.transaction(), self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"advisor-turn:{user_id}:{turn.request_id}",),
            )
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

        with self._lock, self._connection.transaction(), self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"advisor-turn:{user_id}:{turn.request_id}",),
            )
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

    def save_program_source_version(self, version: ProgramSourceVersion) -> ProgramSourceVersion:
        from psycopg.types.json import Jsonb

        with self._lock, self._connection.transaction(), self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"program-source:{version.program_slug}",),
            )
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

        with self._lock, self._connection.transaction(), self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT payload FROM program_source_versions WHERE version_id = %s FOR UPDATE",
                (version_id,),
            )
            row = cursor.fetchone()
            if not row:
                raise SourceVersionNotFoundError("来源版本不存在")
            candidate = ProgramSourceVersion.model_validate(row["payload"])
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"program-source:{candidate.program_slug}",),
            )
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
