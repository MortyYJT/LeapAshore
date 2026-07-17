import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.postgres_store import PostgresStore
from app.models import ApplicationChoice


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
