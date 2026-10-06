"""Tests for the public program catalogue endpoint.

These run against the shared development database, so `seed_programs` is not enough on its own to
guarantee the rows these tests read: it skips any program id that already exists, which means a
row left behind by an earlier run — or by a different tree — is what gets served. The tests that
read the catalogue therefore never assert on a row count and never assume the catalogue holds only
the six seeded rows: the first test pins which programs must be present as a set, and the others
assert on the keys and values the frontend reads. None of them leave a row deleted behind.
"""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import Response
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.main import app
from app.models.program import Program, ProgramPrerequisite, University
from app.models.source import Source, SourceStatus
from app.routers.programs import WITHOUT_SOURCE_HEADER, list_programs
from app.seed import seed_programs
from tests.test_seed import PROGRAM_IDS

# The ordering test needs a program whose prerequisites it controls. Its institution and source are
# stable rows it creates once and reuses, so repeated runs do not accumulate them.
TEST_UNIVERSITY_ID = "test-prerequisites-university"
TEST_SOURCE_ID = "test-prerequisites-source"


def test_lists_every_seeded_program_with_its_source(require_db, db_session):
    """Every seeded program is served, each with the https source it was read from.

    The requirement is that the catalogue lists *every* seeded program, so the served slug set is
    asserted against `PROGRAM_IDS` rather than a row count. A count of `>= 6` cannot carry that
    requirement: `seed_programs` skips ids that already exist, so one leftover row in the
    database is enough for a missing seeded program to keep the count over the threshold. The set
    is a superset check because a leftover row is legitimate; the duplicate check keeps "every
    seeded program" from being satisfied by repetition.
    """
    seed_programs(db_session)
    response = TestClient(app).get("/api/programs")
    assert response.status_code == 200

    programs = response.json()
    slugs = [program["slug"] for program in programs]
    missing = sorted(set(PROGRAM_IDS) - set(slugs))
    assert not missing, f"the catalogue is missing seeded programs: {missing}"
    assert len(slugs) == len(set(slugs)), "a program must not be served twice"

    first = programs[0]
    assert set(first) >= {"slug", "name", "university", "source", "dataStatus"}
    assert first["source"]["url"].startswith("https://")
    assert first["source"]["status"] == "待核验"


def test_filters_by_field(require_db, db_session):
    seed_programs(db_session)
    response = TestClient(app).get("/api/programs", params={"field": "计算机与数据"})
    assert response.status_code == 200
    assert all(p["field"] == "计算机与数据" for p in response.json())


def test_a_field_that_matches_nothing_is_an_empty_list(require_db, db_session):
    """No match is an answer, not a failure: the frontend renders an empty catalogue."""
    seed_programs(db_session)
    response = TestClient(app).get("/api/programs", params={"field": "不存在的专业方向"})
    assert response.status_code == 200
    assert response.json() == []


def test_the_catalogue_needs_no_client_cookie(require_db, db_session):
    """This endpoint serves reference data, not applicant data, so it must not mint a subject.

    `/api/profile` hands out an `offerpilot_client` cookie on first contact. If the catalogue did
    the same, merely opening the school list would create an anonymous applicant row.
    """
    seed_programs(db_session)
    client = TestClient(app)
    response = client.get("/api/programs")
    assert response.status_code == 200
    assert "offerpilot_client" not in client.cookies
    assert "set-cookie" not in {key.lower() for key in response.headers}


def test_the_database_refuses_a_program_whose_source_does_not_exist(require_db, db_session):
    """The "program without its source" state is prevented by the schema, not merely by the router.

    `programs.source_id` is a foreign key, so deleting a source a program still cites is rejected
    by PostgreSQL. That is worth pinning down: it is the guarantee that makes the router's
    missing-source guard a backstop rather than the everyday path, and a later migration that
    relaxes the constraint would break this test instead of silently letting programs lose their
    provenance.
    """
    seed_programs(db_session)
    program_id = db_session.execute(select(Program.id).order_by(Program.id)).scalars().first()
    source_id = db_session.get(Program, program_id).source_id
    assert source_id is not None, "the seed must have attached a source"

    with SessionLocal() as remove:
        with pytest.raises(IntegrityError):
            remove.execute(Source.__table__.delete().where(Source.__table__.c.id == source_id))
            remove.commit()
        remove.rollback()

    # The rejected delete left the catalogue whole.
    with SessionLocal() as check:
        assert check.get(Source, source_id) is not None


def test_the_database_refuses_a_program_with_no_source_at_all(require_db, db_session):
    """`source_id` is mandatory in the schema, not merely filled in by the seed.

    The parallel columns `review_criteria.source_id` and `document_review_findings.criterion_id`
    were always `NOT NULL`; `programs.source_id` was left to the seed, which is what let a single
    sourceless row exist and take the whole catalogue down with a 500. This pins the constraint
    itself, so a later migration that relaxes it fails here instead of quietly restoring the hole.
    The insert is attempted through the ORM with the column left unset, which is exactly how a
    program row with no provenance would be created.
    """
    with SessionLocal() as session:
        with pytest.raises(IntegrityError):
            session.add(
                Program(
                    id="test-program-without-source",
                    university_id="unsw",
                    name="没有来源的项目",
                    data_status="待核验",
                )
            )
            session.flush()
        session.rollback()

    with SessionLocal() as check:
        assert check.get(Program, "test-program-without-source") is None


def test_a_program_without_a_source_does_not_take_the_healthy_rows_down():
    """The router's backstop for a program whose source row cannot be read.

    That state cannot be reached through PostgreSQL — `source_id` is `NOT NULL` and its foreign key
    points at `sources.id` — so this drives the endpoint with a session stub instead of pretending a
    database could produce it. It pins the decision the old version got wrong: one defective row
    used to fail the whole request with a 500, which hid five healthy programs from every applicant
    because a sixth had no provenance.

    The healthy rows are served, `source: null` is never written, and the defective ids travel in the
    `X-OfferPilot-Programs-Without-Source` header rather than being dropped in silence. The header is
    what makes this "serve what can be served and say what could not" rather than "skip the bad row".
    """
    orphan = Program(
        id="orphan-program",
        university_id="unsw",
        name="没有来源的项目",
        requires_cognate=False,
        requires_supervisor=False,
        research_proposal_required=False,
        data_status="待核验",
        source_id="src-that-does-not-exist",
    )
    orphan.university = University(id="unsw", name="新南威尔士大学")
    # The booleans are set rather than left to the column defaults: a `Program` built in Python has
    # none of them yet, and the healthy row is serialised below, so a default that only the INSERT
    # would apply is `None` here and the response model rejects it.
    healthy = Program(
        id="healthy-program",
        university_id="unsw",
        name="有来源的项目",
        requires_cognate=False,
        requires_supervisor=False,
        research_proposal_required=False,
        data_status="待核验",
        source_id="src-that-exists",
    )
    healthy.university = University(id="unsw", name="新南威尔士大学")
    found = Source(
        id="src-that-exists",
        url="https://example.edu/healthy",
        title="Healthy program",
        status=SourceStatus.UNVERIFIED,
    )

    session = MagicMock()
    session.execute.return_value.scalars.return_value = iter([healthy, orphan])
    session.get.side_effect = lambda model, ident, *args, **kwargs: (
        found if ident == "src-that-exists" else None
    )

    response = Response()
    body = list_programs(response=response, session=session, field=None)

    assert [program.slug for program in body] == ["healthy-program"]
    assert body[0].source.url == "https://example.edu/healthy"
    assert response.headers[WITHOUT_SOURCE_HEADER] == "orphan-program"


def test_a_healthy_catalogue_reports_no_defect(require_db, db_session):
    """The defect header is absent when nothing is wrong, so it can be read as an alarm."""
    seed_programs(db_session)
    response = TestClient(app).get("/api/programs")
    assert response.status_code == 200
    assert WITHOUT_SOURCE_HEADER not in response.headers


def test_the_wire_format_uses_the_frontend_key_names(require_db, db_session):
    """Task 8 feeds this response into `Program` in web/lib/types.ts.

    These keys are the contract, not a detail: the frontend reads `slug` where the column is `id`
    and `university` where the column is the university's `name`, so the names are asserted
    explicitly. The fields the endpoint still does not carry are listed in the report rather than
    asserted here, because a name that has no response key cannot be checked against one.
    """
    seed_programs(db_session)
    body = TestClient(app).get("/api/programs").json()
    assert body, "the catalogue must not be empty"

    for key in (
        "slug",
        "name",
        "university",
        "city",
        "degreeLevel",
        "field",
        "duration",
        "minimumMark",
        "non211MinimumMark",
        "requiresCognate",
        "prerequisites",
        "englishRequirement",
        "dataStatus",
    ):
        assert key in body[0], key

    for key in ("url", "title", "status"):
        assert key in body[0]["source"], key


def test_the_prerequisites_are_bare_labels_in_sort_order(require_db, db_session):
    """`eligibility.ts:91` joins `program.prerequisites` with "、" and `:126` tests its length.

    Nothing reads a prerequisite's category or id, so an element is the label alone and the order
    is the only structure the wire format carries. This fixture is built so that `sort_order` is
    the only thing that can produce the expected list: the row ids run backwards against
    `sort_order` (`-pre-a` / `-pre-b` / `-pre-c` for orders 2 / 1 / 0) and the rows are inserted in
    the order 2, 0, 1, so neither sorting by id nor serving the rows unsorted gives the expected
    order while sorting by `sort_order` does. The seed does embed the index in the real
    prerequisite ids (`f"{id}-pre-{index}"` in `api/app/seed.py`), where id order and `sort_order`
    order coincide; this fixture is the place that keeps the two distinguishable.

    The rows are committed, not merely flushed: the endpoint opens its own session per request, so
    an uncommitted row is invisible to it. The institution and the source are stable rows the test
    reuses rather than creates, and the program is removed again in the `finally` block with its
    prerequisite rows, through the model's delete-orphan cascade.
    """
    marker = uuid4().hex[:8]
    program_id = f"test-prerequisites-{marker}"

    session = db_session
    if session.get(University, TEST_UNIVERSITY_ID) is None:
        session.add(University(id=TEST_UNIVERSITY_ID, name="先修课顺序测试大学"))
    if session.get(Source, TEST_SOURCE_ID) is None:
        session.add(
            Source(
                id=TEST_SOURCE_ID,
                url="https://example.edu/prerequisites-order-test",
                title="Prerequisite ordering test",
                status=SourceStatus.UNVERIFIED,
            )
        )
    session.flush()
    session.add(
        Program(
            id=program_id,
            university_id=TEST_UNIVERSITY_ID,
            name="先修课顺序测试项目",
            field="先修课顺序测试方向",
            source_id=TEST_SOURCE_ID,
            data_status="待核验",
        )
    )
    session.flush()

    # (sort_order, label, id suffix): the suffix axis is reversed against `sort_order` on purpose,
    # so the primary key's order is not the order under test.
    prerequisites = [
        (2, "第三步", "pre-a"),
        (0, "第一步", "pre-c"),
        (1, "第二步", "pre-b"),
    ]
    session.add_all(
        [
            ProgramPrerequisite(
                id=f"{program_id}-{suffix}",
                program_id=program_id,
                label=label,
                sort_order=order,
            )
            for order, label, suffix in prerequisites
        ]
    )
    session.commit()

    try:
        response = TestClient(app).get("/api/programs", params={"field": "先修课顺序测试方向"})
        assert response.status_code == 200

        body = response.json()
        assert [row["slug"] for row in body] == [program_id]
        assert body[0]["prerequisites"] == ["第一步", "第二步", "第三步"]
        assert all(isinstance(item, str) for item in body[0]["prerequisites"])
    finally:
        # The program's prerequisite rows go with it through the model's delete-orphan cascade.
        with SessionLocal() as cleanup:
            stored = cleanup.get(Program, program_id)
            if stored is not None:
                cleanup.delete(stored)
            cleanup.commit()
            assert cleanup.get(Program, program_id) is None
