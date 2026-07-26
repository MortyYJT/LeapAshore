import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.postgres_store import PostgresStore
from app.models import ApplicationChoice
from app.source_governance import initialize_source_registry, new_candidate


pytestmark = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="requires PostgreSQL integration database")


def test_postgres_verified_account_and_hashed_session_lifecycle() -> None:
    store = PostgresStore(os.environ["DATABASE_URL"])
    email = f"integration-{uuid4().hex}@example.com"
    user, verification = store.register(email, "secure123", "Integration")
    assert user.email_verified is False
    assert user.terms_version == "2026-07-15"
    assert user.terms_accepted_at is not None
    verified = store.verify_email(verification)
    assert verified.email_verified is True

    session, logged_in = store.login(email, "secure123")
    assert logged_in.email == email
    assert store.user_for_token(session) == logged_in
    store.logout(session)
    assert store.user_for_token(session) is None


def test_postgres_choice_write_preserves_one_primary() -> None:
    store = PostgresStore(os.environ["DATABASE_URL"])
    email = f"portfolio-{uuid4().hex}@example.com"
    user, verification = store.register(email, "secure123", "Portfolio")
    user = store.verify_email(verification)
    run_id = f"run-{uuid4().hex}"
    now = datetime.now(UTC)
    store.save_choice(user.id, ApplicationChoice(
        run_id=run_id, program_slug="program-a", status="applying", is_primary=True, updated_at=now,
    ))
    store.save_choice(user.id, ApplicationChoice(
        run_id=run_id, program_slug="program-b", status="applying", is_primary=True, updated_at=now,
    ))

    choices = store.list_choices(user.id, run_id)
    assert [choice.program_slug for choice in choices if choice.is_primary] == ["program-b"]


def test_postgres_source_review_is_persistent_and_keeps_one_published_version() -> None:
    store = PostgresStore(os.environ["DATABASE_URL"])
    initialize_source_registry(store)
    current = next(
        item for item in store.list_program_source_versions("uwa-master-it")
        if item.status == "published"
    )
    candidate = new_candidate(
        current=current,
        proposed=current.program.model_copy(update={"duration": f"integration-{uuid4().hex}"}),
        submitted_by="integration-submitter",
    )
    store.save_program_source_version(candidate)
    approved = store.review_program_source_version(
        candidate.version_id,
        "approve",
        "integration-reviewer",
        datetime.now(UTC),
    )

    assert store.get_program_source_version(candidate.version_id) == approved
    assert approved.status == "published"
    assert approved.reviewed_by == "integration-reviewer"
    assert sum(
        item.status == "published"
        for item in store.list_program_source_versions("uwa-master-it")
    ) == 1

    rollback = new_candidate(
        current=approved,
        proposed=current.program,
        submitted_by="integration-reviewer",
        rollback_of=current.version_id,
    )
    store.save_program_source_version(rollback)
    restored = store.review_program_source_version(
        rollback.version_id,
        "approve",
        "integration-reviewer",
        datetime.now(UTC),
    )
    assert restored.status == "published"
    assert restored.content_hash == current.content_hash
