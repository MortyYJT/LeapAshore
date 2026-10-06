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


def database_is_reachable() -> bool:
    """True when the development database answers."""
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
    except Exception:  # noqa: BLE001 - any connection failure means "not available"
        return False
    return True


@pytest.fixture
def require_db():
    """Skip instead of failing when the container is not running."""
    if not database_is_reachable():
        pytest.skip("database container is not running")


@pytest.fixture(autouse=True)
def remove_the_clients_these_tests_create():
    """Leave the shared development database exactly as it was found.

    M1 has no test database, so these tests write real rows. Deleting only the ids that appeared
    during the test keeps that from also deleting whatever the developer has been trying out.

    It is autouse rather than requested per test because that is the only way it can be trusted: a
    test that forgets the fixture would still be counted green while quietly leaving its subject
    rows in the database the developer uses. Sweeping every test costs two `select id` queries and
    makes the cleanup independent of who remembers to ask for it.

    It does not depend on `require_db`, because a fixture that skips takes its test with it:
    `test_health.py` never touches the database and still has to run while the container is down.
    An unreachable database therefore means "no rows were written", not "skip this test".
    """
    if not database_is_reachable():
        yield
        return

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
