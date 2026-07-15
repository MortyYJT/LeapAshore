import os
from uuid import uuid4

import pytest

from app.postgres_store import PostgresStore


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
