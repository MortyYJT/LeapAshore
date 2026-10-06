import pytest
from sqlalchemy import delete, select, text

from app.db import SessionLocal, engine
from app.models.client import Client
from app.models.roadmap import MaterialTemplate, RoadmapPhase
from app.models.source import Source
from app.seed_roadmap import GS_SOURCE_URL


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


def clear_the_roadmap_definition(session) -> None:
    """Delete every phase and material, and the Genuine Student source.

    The order is not cosmetic. ``material_templates.phase`` is RESTRICT, so the database refuses to
    drop a phase that still has materials, and ``material_templates.source_id`` points at the source
    the visa materials cite, so the source can only go once those materials have.
    """
    for row in session.scalars(select(MaterialTemplate)):
        session.delete(row)
    session.flush()
    for row in session.scalars(select(RoadmapPhase)):
        session.delete(row)
    session.flush()
    source = session.execute(
        select(Source).where(Source.url == GS_SOURCE_URL)
    ).scalar_one_or_none()
    if source is not None:
        session.delete(source)
    session.flush()


@pytest.fixture(scope="session", autouse=True)
def start_from_an_unseeded_roadmap_definition():
    """Remove the seeded roadmap definition once, before the first test of the session.

    ``api/seed_cli.py`` writes the seven phases, their materials and the Genuine Student source into
    the same development database these tests use, so a developer who has run ``make seed`` starts a
    test run with configuration rows already present. Two test modules hold fixed values that the
    seed now owns: ``test_roadmap_model.py`` inserts the keys ``selection`` and ``aca-transcript``,
    and ``test_sources.py`` inserts the Genuine Student url, which is unique. Either one would then
    fail for a reason that has nothing to do with what it tests.

    The definition is removed here rather than in those modules because it has to happen before the
    first of them is collected, and because this is the same policy the catalogue already follows:
    ``test_seed.py`` clears the seeded programs before it asserts on counts, which is why no test
    depends on the developer's database being seeded. ``test_seed_roadmap.py`` also removes what it
    writes, so the suite neither depends on nor leaves behind the seeded definition.
    """
    if not database_is_reachable():
        return
    with SessionLocal() as session:
        clear_the_roadmap_definition(session)
        session.commit()


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
