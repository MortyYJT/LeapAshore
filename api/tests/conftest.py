import pytest
from sqlalchemy import delete, select, text

from app.db import SessionLocal, engine
from app.models.client import Client


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


@pytest.fixture
def remove_the_clients_these_tests_create(require_db):
    """Leave the shared development database exactly as it was found.

    M1 has no test database, so these tests write real rows. Deleting only the ids that appeared
    during the test keeps that from also deleting whatever the developer has been trying out. It
    lives here because both profile test modules need it.
    """
    with SessionLocal() as session:
        before = set(session.scalars(select(Client.id)))
    yield
    with SessionLocal() as session:
        after = set(session.scalars(select(Client.id)))
        created = after - before
        if created:
            # The database cascade takes each profile with its client.
            session.execute(delete(Client).where(Client.id.in_(created)))
            session.commit()
