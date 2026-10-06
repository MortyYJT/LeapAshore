import pytest
from sqlalchemy import text

from app.db import SessionLocal, engine


@pytest.fixture
def db_session():
    """A session bound to the real development database.

    M1 has no test database yet: the schema is small and the container is disposable, so tests run
    against the same database the developer uses and clean up after themselves.
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def require_db():
    """Skip instead of failing when the container is not running."""
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
    except Exception:  # noqa: BLE001 - any connection failure means "not available"
        pytest.skip("database container is not running")
