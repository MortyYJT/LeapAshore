import pytest
from sqlalchemy import delete, select, text

from app.db import SessionLocal, engine
from app.models.client import Client
from app.models.roadmap import MaterialTemplate, RoadmapPhase
from app.models.source import Source
from app.models.task import RoadmapTask
from app.seed_roadmap import GS_SOURCE_URL, seed_roadmap

# The column names a displaced task row is snapshotted by, taken from the table rather than written
# out, so a column added later is carried by the restore without anyone remembering to add it here.
TASK_COLUMNS = tuple(column.key for column in RoadmapTask.__table__.columns)


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


def clear_the_roadmap_definition(session) -> list[dict]:
    """Delete every phase and material, and the Genuine Student source.

    The order is not cosmetic. ``material_templates.phase`` is RESTRICT, so the database refuses to
    drop a phase that still has materials, and ``material_templates.source_id`` points at the source
    the visa materials cite, so the source can only go once those materials have.

    ``roadmap_tasks.material_key`` is RESTRICT as well, and that is a defect rather than an ordering
    detail: a single task row left in the shared development database — by a probe script that failed
    before its cleanup, or by the frontend once it starts writing rows — used to abort the material
    delete with ``roadmap_tasks_material_key_fkey`` and take the whole run down with it, including
    ``test_health.py``, which never touches the database. Measured: one row for an existing subject,
    then ``pytest tests/test_health.py -q`` -> ``ERROR tests/test_health.py::test_health_reports_ok
    ... ForeignKeyViolation``.

    The subject sweep below cannot prevent that: it deletes only the subjects a test created inside
    the session, and the row in question belongs to a subject that was already there. So the task rows
    that stand in the way of the definition are removed here, before the materials, and returned as
    plain column values so the session-scoped fixture can put them back when it restores the
    definition. They are the developer's rows, and a test run that quietly deleted them would violate
    the same "leave the shared database as it was found" rule the subject sweep follows.
    """
    tasks = list(session.scalars(select(RoadmapTask)))
    displaced = [{name: getattr(task, name) for name in TASK_COLUMNS} for task in tasks]
    for task in tasks:
        session.delete(task)
    session.flush()

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
    return displaced


def restore_roadmap_tasks(session, displaced: list[dict]) -> None:
    """Put back the task rows the definition sweep had to remove, as it found them.

    Called only after ``seed_roadmap`` has restored the definition, because a task row names a
    material that has to exist. A row whose subject is gone by now is skipped rather than restored:
    the subject sweep cascades a test's own subjects away, and re-inserting a row for a deleted client
    would fail the foreign key and turn the teardown into the failure it exists to prevent. A row that
    is somehow already back is left alone, so the restore cannot collide with itself.
    """
    for values in displaced:
        if session.get(Client, values["client_id"]) is None:
            continue
        if session.get(RoadmapTask, values["id"]) is not None:
            continue
        session.add(RoadmapTask(**values))


@pytest.fixture
def clear_the_roadmap_definition_after_the_test():
    """Remove the roadmap definition once the test that seeded it has finished.

    ``test_seed_roadmap.py`` and ``test_roadmap_api.py`` both seed the definition and both have to
    remove what they wrote before the next module is collected: ``test_roadmap_model.py`` inserts
    the keys ``selection`` and ``aca-transcript``, and ``test_sources.py`` inserts the Genuine
    Student url, which is unique. A seeded database reaching either one makes it fail on a unique
    violation for a reason that has nothing to do with what it tests. This is why
    ``test_seed_roadmap.py`` has swept after itself since it was written, and why the api module
    has to as well.

    It is deliberately **not** autouse: ``test_roadmap_model.py`` inserts rows the definition owns
    and then asserts on them, so a fixture that swept every module would delete the very rows that
    module is checking. The two modules that seed request it explicitly, as a dependency of their
    own autouse fixture, which is also where the reasoning that is specific to each of them lives.

    ``clear_the_roadmap_definition`` is the cleaner: it deletes the materials, then the phases, then
    the Genuine Student source, in that order, because the database refuses a phase that still has
    materials and a source that materials still point at. It also removes any task row that names one
    of those materials, and returns them; this fixture ignores the return value because it has no way
    to restore them — the materials they point at are deleted until the session ends, and a task row
    cannot exist without its material. The rows a developer left behind are displaced by the
    session-scoped sweep before the first test is collected, so there is nothing left here for this
    mid-run sweep to lose; only rows a test creates mid-run, which belong to subjects the same run
    deletes anyway, can be reached.

    An unreachable database means "no rows were written", not "skip this test", the same rule
    ``remove_the_clients_these_tests_create`` follows: failing here would turn a container that is
    down into a red suite instead of a skipped one.
    """
    yield
    if not database_is_reachable():
        return
    with SessionLocal() as session:
        clear_the_roadmap_definition(session)
        session.commit()


@pytest.fixture(scope="session", autouse=True)
def unseed_the_roadmap_definition_for_the_run_and_restore_it_afterwards():
    """Empty the roadmap definition for the run, then put the canonical one back.

    ``api/seed_cli.py`` writes the seven phases, their materials and the Genuine Student source
    into the same development database these tests use, so a developer who has run ``make seed``
    starts a test run with configuration rows already present. Two test modules hold fixed values
    that the seed now owns: ``test_roadmap_model.py`` inserts the keys ``selection`` and
    ``aca-transcript``, and ``test_sources.py`` inserts the Genuine Student url, which is unique.
    Either one would then fail for a reason that has nothing to do with what it tests. Both are
    ordinary tests of the model and the source, not of the seed, so the definition is removed here
    rather than those modules being rewritten around a seeded database: it has to happen before the
    first of them is collected, and it is the same policy the catalogue already follows when
    ``test_seed.py`` clears the seeded programs before asserting on counts.

    The teardown restores the definition now, which it did not before. Clearing tens of
    configuration rows and leaving it at that made the roadmap the one part of the development
    database a test run destroyed: the program catalogue survives, the roadmap definition did not,
    so ``make seed`` -> ``make test`` left an empty timeline, and ``make dev`` does not seed. The
    next task's ``GET /api/roadmap`` reads these tables, and ``make verify`` runs ``test`` before
    ``screenshots``, so the browser walkthrough would have driven an empty roadmap. ``seed_roadmap``
    is idempotent, so one call returns the definition to the state ``make seed`` produces: the
    phases, the materials and the Genuine Student source that ``clear_the_roadmap_definition``
    removes.

    ``test_seed_roadmap.py``'s own fixture removes what its tests write and does not restore it: the
    definition has to stay empty for the whole run, because a seeded database reaching
    ``test_roadmap_model.py`` or ``test_sources.py`` is what breaks those two modules. The restore
    happens here, once, when every test has finished.

    The task rows the sweep had to displace go back here too, for the same reason the definition
    does. ``clear_the_roadmap_definition`` returns them, and this is the only place that can restore
    them: the row names a material, so it can only be re-inserted after ``seed_roadmap`` has put the
    materials back. A run therefore leaves a developer's own task rows exactly where it found them,
    which is what makes the sweep's new deletion safe rather than destructive.
    """
    # The yield is unconditional on purpose. A fixture that returns before its yield is a generator
    # that ends early, and pytest reports that as "did not yield a value" and errors out of every
    # test that depends on it — with no container, that turned the whole module red instead of
    # skipping it. An unreachable database means "no rows were written", not "skip this test", the
    # same rule ``remove_the_clients_these_tests_create`` below follows.
    reachable = database_is_reachable()
    displaced_tasks: list[dict] = []
    if reachable:
        with SessionLocal() as session:
            displaced_tasks = clear_the_roadmap_definition(session)
            session.commit()
    yield
    if not reachable or not database_is_reachable():
        return
    with SessionLocal() as session:
        seed_roadmap(session)
        restore_roadmap_tasks(session, displaced_tasks)
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
