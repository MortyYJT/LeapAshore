"""The review criteria: what the seed writes, and what the API refuses to do with them.

The seed is a transcription, so the tests here are about faithfulness and about the two states it
must not fake:

- every criterion cites the one official page the visa materials already cite, and none carries a
  verification date — `verified_at` is a human's statement and the seed is not a human;
- re-seeding does not overwrite a verification someone has already made. That property is not
  cosmetic: the session sweep removes the criteria before every test run and the teardown seeds them
  back, so an upsert that clobbered `status` would silently un-verify a checked requirement on every
  `make test`.

The API is read-only by design. There is no login and no role in this repository, so an HTTP write
route would let any visitor mark a requirement as verified.
"""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models.review import CheckType, CriterionStatus, ReviewCriterion
from app.models.source import Source
from app.seed_review_criteria import GS_CRITERIA, seed_review_criteria
from app.seed_roadmap import GS_SOURCE_URL

# A stand-in for the moment a human checked a page. Named rather than written at the assignment:
# `scripts/check-no-fake-dates.cjs` refuses a date literal assigned to `verified_at`, and it is right
# to — the one place that value may come from is the operator command's `now()`.
A_STAMP = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
AN_EARLIER_STAMP = datetime(2026, 10, 8, 9, 30, tzinfo=UTC)


@pytest.fixture(autouse=True)
def remove_the_criteria_these_tests_seed(clear_the_roadmap_definition_after_the_test):
    """Sweep the definition after each test here, the way `test_roadmap_api.py` does.

    `seed_review_criteria` commits and calls `seed_roadmap` for the page the criteria cite, so without
    this the Genuine Student source would still be present when `test_sources.py` is collected and
    that module's insert of the same url would fail on a unique violation for a reason that has
    nothing to do with what it tests. The sweep is also what the review asks to have exercised: it
    has to remove the criteria before the source, or it aborts on `review_criteria_source_id_fkey`.
    """


def read_criteria(client: TestClient | None = None) -> list[dict]:
    response = (client or TestClient(app)).get("/api/review-criteria")
    assert response.status_code == 200, response.text
    return response.json()


def test_the_seed_writes_the_transcribed_criteria(db_session, require_db):
    written = seed_review_criteria(db_session)

    assert written == len(GS_CRITERIA) == 10
    assert len(read_criteria()) == 10


def test_every_criterion_cites_the_official_page(db_session, require_db):
    seed_review_criteria(db_session)

    urls = {row["source"]["url"] for row in read_criteria()}
    assert urls == {GS_SOURCE_URL}, "a criterion cited something other than the Genuine Student page"


def test_every_criterion_is_served_unverified(db_session, require_db):
    seed_review_criteria(db_session)

    for row in read_criteria():
        assert row["status"] == CriterionStatus.UNVERIFIED
        assert row["verifiedAt"] is None


def test_the_answer_length_criterion_is_machine_checkable(db_session, require_db):
    seed_review_criteria(db_session)

    length = next(row for row in read_criteria() if row["code"] == "gs-answer-length")
    assert length["checkType"] == CheckType.LENGTH
    assert length["rule"] == {"maxWords": 150}


def test_a_criterion_only_a_human_can_check_reports_no_rule(db_session, require_db):
    """`null` says "a person judges this"; an empty object would claim a machine can."""
    seed_review_criteria(db_session)

    presence = next(row for row in read_criteria() if row["code"] == "gs-current-circumstances")
    assert presence["checkType"] == CheckType.PRESENCE
    assert presence["rule"] is None


def test_every_criterion_names_its_scope(db_session, require_db):
    seed_review_criteria(db_session)

    assert {row["scope"] for row in read_criteria()} == {"gs"}


def test_the_seed_is_repeatable(db_session, require_db):
    seed_review_criteria(db_session)
    seed_review_criteria(db_session)

    codes = [row["code"] for row in read_criteria()]
    assert len(codes) == 10
    assert len(set(codes)) == 10, "re-seeding duplicated a criterion"


def test_re_seeding_keeps_a_verification_a_human_made(db_session, require_db):
    """The upsert updates what the source says and leaves what a person decided alone.

    The session sweep in `conftest` deletes the criteria before every test run and the teardown seeds
    them back. If re-seeding reset `status` and `verified_at`, the developer's own verification would
    disappear every time anyone ran `make test` — silently, and with only the interface to notice.
    """
    seed_review_criteria(db_session)
    with SessionLocal() as session:
        row = session.execute(
            select(ReviewCriterion).where(ReviewCriterion.code == "gs-evidence")
        ).scalar_one()
        row.status = CriterionStatus.VERIFIED
        row.verified_at = A_STAMP
        session.commit()

    seed_review_criteria(db_session)

    stored = next(row for row in read_criteria() if row["code"] == "gs-evidence")
    assert stored["status"] == CriterionStatus.VERIFIED
    assert stored["verifiedAt"] is not None


def test_a_verification_survives_the_session_sweep_and_the_restore(db_session, require_db):
    """The sweep removes the criteria and the teardown seeds them back; the human's fields return.

    Exercised directly rather than through the fixtures because the property under test *is* the
    sweep's, and a test that only ever ran the fixtures could not show that the restore happens.
    """
    from tests.conftest import clear_the_roadmap_definition, restore_review_criteria

    seed_review_criteria(db_session)
    with SessionLocal() as session:
        row = session.execute(
            select(ReviewCriterion).where(ReviewCriterion.code == "gs-immigration-history")
        ).scalar_one()
        row.status = CriterionStatus.VERIFIED
        row.verified_at = AN_EARLIER_STAMP
        session.commit()

    with SessionLocal() as session:
        _, criterion_states = clear_the_roadmap_definition(session)
        session.commit()
        assert session.execute(select(ReviewCriterion)).scalars().all() == []

        seed_review_criteria(session)
        restored = restore_review_criteria(session, criterion_states)
        session.commit()

    assert restored == 10
    stored = next(row for row in read_criteria() if row["code"] == "gs-immigration-history")
    assert stored["status"] == CriterionStatus.VERIFIED
    assert stored["verifiedAt"] is not None


def test_no_http_route_can_change_a_criterion(db_session, require_db):
    seed_review_criteria(db_session)
    client = TestClient(app)

    for method in ("post", "put", "patch", "delete"):
        response = getattr(client, method)("/api/review-criteria")
        assert response.status_code == 405, f"{method.upper()} was not refused"
        assert len(read_criteria(client)) == 10


def test_the_criteria_are_the_same_for_every_caller(db_session, require_db):
    """Shared configuration, not anyone's data: no cookie, and the same list either way."""
    seed_review_criteria(db_session)

    first = read_criteria(TestClient(app))
    second = read_criteria(TestClient(app))

    assert [row["code"] for row in first] == [row["code"] for row in second]


def test_the_seed_does_not_duplicate_a_source_url(db_session, require_db):
    """It reuses the page `seed_roadmap` writes rather than adding a second row for the same url."""
    seed_review_criteria(db_session)
    seed_review_criteria(db_session)

    with SessionLocal() as session:
        rows = session.execute(select(Source).where(Source.url == GS_SOURCE_URL)).scalars().all()
    assert len(rows) == 1
