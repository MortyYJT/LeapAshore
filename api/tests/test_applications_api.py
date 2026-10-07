"""The school-choice portfolio's two doors, at the wire: read it whole, replace it whole.

`GET /api/applications` serves the caller's own rows with the program information the frontend
renders; `PUT /api/applications` replaces that portfolio whole, in one transaction, and reports what
it did. Four facts are asserted here that the write alone cannot show:

- the two ways a payload can contradict the table's own constraints are *different* refusals, and
  both are a mapped 4xx naming the offender rather than a 500: the same program named by two rows
  violates `UNIQUE (client_id, program_id)`, and two rows marked `isPrimary` violate the partial
  unique index `uq_applications_one_primary_per_client`. The two are separate constraints, so a test
  that accepted either message for either payload would not prove the payloads are told apart;
- an unknown program is the caller's mistake, answered with a message, not the foreign key's 500;
- the caller's cookie is read, and *proven* read: another subject's flight sends the same program id
  under a different cookie, the control shows the route answers the cookie it is given, and the first
  subject's row is asserted to be untouched — id, band, first-choice flag and all. "Two clients
  differ" is not that claim;
- every change lands in `task_events` as the applicant's own, and a row the payload restates without
  moving anything does not.

The subjects these tests create are swept by `conftest`'s autouse fixture, and their application rows
follow the subject through the foreign key's CASCADE. The programs are the seeded ones: no probe row
is written, because `test_seed.py` dumps every stored program into the mirror guard and a stray row
would be reported as a catalogue that no longer matches `web/lib/programs.ts`.
"""

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.deps import COOKIE_NAME
from app.main import app
from app.models.application import (
    Application,
    ApplicationOrigin,
    ApplicationStatus,
    ApplicationTier,
)
from app.models.client import Client
from app.models.task import TaskEvent
from app.seed import seed_programs
from app.services.applications import InvalidApplicationPayload, replace_applications
from tests.test_seed import PROGRAM_IDS

# Three of the six seeded programs, in the seed's own order, plus a program id that names nothing.
REACH, MATCH, SAFETY = PROGRAM_IDS[:3]
NO_SUCH_PROGRAM = "no-such-program-at-all"


def _row(program_id: str, **overrides) -> dict:
    """One portfolio row in the spelling the wire uses, with the one required band filled in."""
    row = {"programId": program_id, "tier": "稳"}
    row.update(overrides)
    return row


def _put(client: TestClient, rows: list[dict]):
    return client.put("/api/applications", json={"rows": rows})


def _events(session, client_id: str) -> list[TaskEvent]:
    """The history rows written for one subject, read after dropping what this session cached."""
    session.expire_all()
    return list(session.scalars(select(TaskEvent).where(TaskEvent.client_id == client_id)))


def _stored(session, client_id: str) -> dict[str, Application]:
    """The rows one subject holds, keyed by program, read without the session's memory."""
    session.expire_all()
    return {
        row.program_id: row
        for row in session.scalars(select(Application).where(Application.client_id == client_id))
    }


def test_an_empty_portfolio_is_an_empty_list_and_a_read_writes_nothing(require_db, db_session):
    """A first visit is [] and no subject: the read is a read.

    `GET /api/profile` creates the subject it answers for, and this route deliberately does not: a
    browser that only looks at its portfolio must not leave an applicant row behind. The row is
    created by the first write, which is what the cookie is there for.
    """
    seed_programs(db_session)
    client = TestClient(app)

    response = client.get("/api/applications")
    assert response.status_code == 200
    assert response.json() == []
    assert COOKIE_NAME in client.cookies, "the read must still name the subject it answered for"
    assert db_session.get(Client, client.cookies[COOKIE_NAME]) is None, (
        "reading an empty portfolio created an applicant row"
    )


def test_put_replaces_the_portfolio_whole_and_the_read_serves_it(require_db, db_session):
    """The whole replacement, and the wire shape the frontend reads.

    A row that leaves the payload is gone, a row that stays is moved, a row that arrives is created —
    in one call. The served row carries the program information the two portfolio lists render
    (`HomeView.tsx:77` and `FlowView.tsx:135` draw `university` and the English program name), and an
    official deadline nobody typed is null rather than a date this endpoint made up.
    """
    seed_programs(db_session)
    client = TestClient(app)

    created = _put(
        client,
        [
            _row(REACH, tier="冲", isPrimary=True, needsReview=False),
            _row(MATCH, tier="稳", needsReview=True, status="applying"),
        ],
    )
    assert created.status_code == 200, created.text
    assert created.json() == {"created": 2, "updated": 0, "kept": 0, "removed": 0}

    served = client.get("/api/applications").json()
    assert [row["programId"] for row in served] == [REACH, MATCH], (
        "the first choice leads, then the bands in 冲 / 稳 / 保 order"
    )
    first = served[0]
    for key in (
        "id",
        "programId",
        "tier",
        "status",
        "isPrimary",
        "officialDeadline",
        "deadlineSourceUrl",
        "needsReview",
        "origin",
        "program",
        "createdAt",
        "updatedAt",
    ):
        assert key in first, key
    assert first["tier"] == "冲" and first["isPrimary"] is True
    assert first["status"] == ApplicationStatus.CONSIDERING.value, "the band is required, the status is not"
    assert first["origin"] == ApplicationOrigin.USER.value
    assert first["officialDeadline"] is None, "a deadline nobody looked up must not be invented"
    assert first["deadlineSourceUrl"] is None
    assert first["needsReview"] is False
    assert first["program"]["slug"] == REACH
    assert first["program"]["university"], "the portfolio list renders the institution"
    assert first["program"]["nameEn"], "the portfolio list renders the English program name"
    assert served[1]["needsReview"] is True and served[1]["status"] == "applying"

    replaced = _put(client, [_row(MATCH, tier="保", status="applying", needsReview=True)])
    assert replaced.status_code == 200, replaced.text
    assert replaced.json() == {"created": 0, "updated": 1, "kept": 0, "removed": 1}

    after = client.get("/api/applications").json()
    assert [(row["programId"], row["tier"]) for row in after] == [(MATCH, "保")], (
        "a program the payload no longer names must be gone from the portfolio"
    )


def test_a_program_named_twice_and_a_second_first_choice_are_two_different_refusals(
    require_db, db_session
):
    """The two constraints, told apart by name instead of by a shared 500.

    `UNIQUE (client_id, program_id)` refuses the same program twice; the partial unique index refuses
    two first choices. They are separate constraints, so the two payloads must produce two different
    messages that each name what is wrong — a single "invalid portfolio" answer would leave the
    applicant unable to tell which rule the payload broke, and an `IntegrityError` reaching the wire
    would tell them nothing at all.
    """
    seed_programs(db_session)
    client = TestClient(app)

    # The control: the payload shape itself is acceptable, so a 422 below is about the contradiction
    # and not about a route that refuses this body for another reason. It names a program neither
    # refusal mentions, so the control's row is what the state assertions at the end look for.
    accepted = _put(client, [_row(SAFETY, tier="保")])
    assert accepted.status_code == 200, accepted.text

    # Both payloads name programs the subject does not hold yet, which is what makes them able to
    # fail: an unwritten check lets the inserts reach the constraints, and PostgreSQL then refuses
    # them with an `IntegrityError` the caller sees as a 500.
    twice = _put(client, [_row(MATCH), _row(MATCH, tier="冲")])
    assert twice.status_code == 422, f"a duplicated program was not a mapped refusal: {twice.text}"
    assert MATCH in twice.text, "the refusal must name the program that was named twice"
    assert "more than one row" in twice.text, twice.text

    two_primaries = _put(
        client, [_row(REACH, isPrimary=True), _row(MATCH, isPrimary=True)]
    )
    assert two_primaries.status_code == 422, (
        f"a second first choice was not a mapped refusal: {two_primaries.text}"
    )
    assert REACH in two_primaries.text and MATCH in two_primaries.text, two_primaries.text
    assert "first choice" in two_primaries.text, two_primaries.text

    assert twice.text != two_primaries.text, "one message for two different constraints"
    assert "first choice" not in twice.text, "the duplication message describes the wrong constraint"
    assert "more than one row" not in two_primaries.text, (
        "the first-choice message describes the wrong constraint"
    )

    served = client.get("/api/applications").json()
    assert [row["programId"] for row in served] == [SAFETY], (
        "a refused payload wrote or removed a row"
    )
    assert [event.event for event in _events(db_session, client.cookies[COOKIE_NAME])] == ["created"], (
        "a refused payload left history behind"
    )


def test_an_unknown_program_is_refused_by_name_not_by_the_foreign_key(require_db, db_session):
    """`program_id` is a foreign key, so an unknown one used to be an `IntegrityError` and a 500.

    The caller can act on the mistake, so it is answered with a message that names the id. The valid
    half of the same payload is not written either: the refusal happens before anything lands, which
    is what makes the replacement one transaction rather than a partial one.
    """
    seed_programs(db_session)
    client = TestClient(app)

    refused = _put(client, [_row(REACH), _row(NO_SUCH_PROGRAM, tier="保")])
    assert refused.status_code == 422, (
        f"an unknown program was not a mapped refusal: {refused.status_code} {refused.text}"
    )
    assert NO_SUCH_PROGRAM in refused.text, refused.text
    assert client.get("/api/applications").json() == [], "a refused payload wrote the valid half"

    accepted = _put(client, [_row(REACH)])
    assert accepted.status_code == 200, accepted.text
    assert [row["programId"] for row in client.get("/api/applications").json()] == [REACH]


def test_an_omitted_deadline_survives_and_an_explicit_null_clears_it(require_db, db_session):
    """Omission is silence about a field; null is the claim that the row has no deadline.

    They are different claims, and treating them alike is how a replacement that mentions a band but
    not a deadline silently wipes a deadline the applicant entered — a loss invisible in the payload
    that caused it. The two deadline fields move independently, each by its own rule.
    """
    seed_programs(db_session)
    client = TestClient(app)

    entered = _put(
        client,
        [
            _row(
                REACH,
                officialDeadline="2027-01-15",
                deadlineSourceUrl="https://example.edu/admissions/deadlines",
            )
        ],
    )
    assert entered.status_code == 200, entered.text
    assert entered.json() == {"created": 1, "updated": 0, "kept": 0, "removed": 0}

    # The same band and nothing said about the deadlines: the payload states the row it already
    # holds, so nothing moves and the count says so rather than calling it an update.
    restated = _put(client, [_row(REACH)])
    assert restated.status_code == 200, restated.text
    assert restated.json() == {"created": 0, "updated": 0, "kept": 1, "removed": 0}, (
        "a row the payload restated without moving anything is not an update"
    )
    kept = client.get("/api/applications").json()[0]
    assert kept["officialDeadline"] == "2027-01-15", "an omitted deadline was cleared"
    assert kept["deadlineSourceUrl"] == "https://example.edu/admissions/deadlines", (
        "an omitted source url was cleared"
    )

    cleared = _put(client, [_row(REACH, officialDeadline=None)])
    assert cleared.status_code == 200, cleared.text
    assert cleared.json() == {"created": 0, "updated": 1, "kept": 0, "removed": 0}
    after = client.get("/api/applications").json()[0]
    assert after["officialDeadline"] is None, "an explicit null did not clear the deadline"
    assert after["deadlineSourceUrl"] == "https://example.edu/admissions/deadlines", (
        "clearing the date cleared the url that was not mentioned"
    )

    url_cleared = _put(client, [_row(REACH, deadlineSourceUrl=None)])
    assert url_cleared.status_code == 200, url_cleared.text
    assert client.get("/api/applications").json()[0]["deadlineSourceUrl"] is None


def test_a_row_the_applicant_writes_is_theirs_and_cannot_claim_the_advisor(
    require_db, db_session
):
    """`origin` is the server's to set, not the client's to claim.

    A portfolio is the applicant's own decision, so everything this route writes is `user`. The field
    is refused by the schema rather than dropped in silence, which is what keeps a payload that sends
    it from being read as a request the server honoured. A row the advisor had put there and the
    applicant re-states becomes the applicant's, because restating a choice is claiming it.
    """
    seed_programs(db_session)
    client = TestClient(app)

    refused = _put(client, [_row(REACH, origin="agent")])
    assert refused.status_code == 422, f"a client claimed the advisor's origin: {refused.text}"
    assert "origin" in refused.text, refused.text
    assert client.get("/api/applications").json() == [], "a refused payload wrote a row"

    written = _put(client, [_row(REACH)])
    assert written.status_code == 200, written.text
    stored = _stored(db_session, client.cookies[COOKIE_NAME])
    assert stored[REACH].origin == ApplicationOrigin.USER, (
        "a row the applicant writes must be the applicant's"
    )

    # An advisor-owned row, which no client route can write, is claimed by the applicant restating
    # the program: the row that comes out of the write says `user`, and the change is in the history.
    db_session.add(
        Application(
            id=str(uuid.uuid4()),
            client_id=client.cookies[COOKIE_NAME],
            program_id=SAFETY,
            tier=ApplicationTier.SAFETY.value,
            origin=ApplicationOrigin.AGENT,
        )
    )
    db_session.commit()

    claimed = _put(client, [_row(REACH), _row(SAFETY, tier="保")])
    assert claimed.status_code == 200, claimed.text
    assert claimed.json() == {"created": 0, "updated": 1, "kept": 1, "removed": 0}
    stored = _stored(db_session, client.cookies[COOKIE_NAME])
    assert stored[SAFETY].origin == ApplicationOrigin.USER, (
        "the applicant restated the row without claiming it"
    )
    # The advisor's row was inserted straight into the table, so it has no `created` event: the only
    # entry it owns is the one this write wrote, and it says the origin moved.
    reassigned = [
        event
        for event in _events(db_session, client.cookies[COOKIE_NAME])
        if event.application_id == stored[SAFETY].id
    ]
    assert [event.event for event in reassigned] == ["reassigned"], (
        f"the claim is not in the history: {[(e.event, e.actor) for e in reassigned]}"
    )


def test_one_subject_never_sees_or_overwrites_another_subjects_portfolio(require_db, db_session):
    """Cross-subject isolation, proven rather than assumed.

    The earlier isolation test this project shipped proved only that two clients differ, which a route
    that never read the cookie would also satisfy. What is asserted here instead is that the cookie is
    read: the same program id is presented under the stranger's cookie, the stranger gets its own row
    for it, and the owner's row is asserted untouched — same id, same band, same first-choice flag —
    while the database is asserted to hold one row for that program *per subject*. A route that
    matched a portfolio row by program alone would have moved the owner's row and left a single one.
    """
    seed_programs(db_session)
    owner, stranger = TestClient(app), TestClient(app)
    owner.get("/api/profile")
    stranger.get("/api/profile")
    assert owner.cookies[COOKIE_NAME] != stranger.cookies[COOKIE_NAME], (
        "the two clients have to be different subjects for this test to mean anything"
    )

    written = _put(owner, [_row(REACH, tier="冲", isPrimary=True), _row(MATCH, tier="稳")])
    assert written.status_code == 200, written.text
    owner_row = _stored(db_session, owner.cookies[COOKIE_NAME])[REACH]
    owner_row_id = owner_row.id

    # The control: the read answers the cookie it was given, so "the stranger sees nothing" below is
    # the subject filter talking rather than a route that serves nothing to anyone.
    assert [row["programId"] for row in owner.get("/api/applications").json()] == [REACH, MATCH]
    assert stranger.get("/api/applications").json() == [], (
        "another subject saw rows that are not theirs"
    )

    # The same program, presented under the stranger's cookie.
    strangers_write = _put(stranger, [_row(REACH, tier="保", isPrimary=True)])
    assert strangers_write.status_code == 200, strangers_write.text
    assert strangers_write.json() == {"created": 1, "updated": 0, "kept": 0, "removed": 0}, (
        "the stranger's write updated a row instead of creating its own"
    )
    assert [(row["programId"], row["tier"]) for row in stranger.get("/api/applications").json()] == [
        (REACH, "保")
    ]

    rows = _stored(db_session, owner.cookies[COOKIE_NAME])
    assert rows[REACH].id == owner_row_id, "the other subject's write replaced this subject's row"
    assert rows[REACH].tier == "冲", "the other subject's band landed on this subject's row"
    assert rows[REACH].is_primary is True
    assert rows[REACH].client_id == owner.cookies[COOKIE_NAME]
    assert [row["tier"] for row in owner.get("/api/applications").json()] == ["冲", "稳"], (
        "the owner's own read stopped answering the owner's cookie"
    )

    # One row per subject for that program, which is the other half of "not written": a route that
    # ignored the subject would have left a single row behind and one portfolio short.
    both = list(
        db_session.scalars(
            select(Application).where(Application.program_id == REACH).order_by(Application.id)
        )
    )
    assert {row.client_id for row in both} == {
        owner.cookies[COOKIE_NAME],
        stranger.cookies[COOKIE_NAME],
    }, f"the program is held by {len(both)} rows: {[(r.client_id, r.tier) for r in both]}"


def test_every_change_is_history_as_the_applicants_own_and_an_empty_payload_clears_it(
    require_db, db_session
):
    """The audit trail, and the four counts that describe one call.

    `task_events` is the table this one was waiting for, so every row this route inserts, moves or
    removes leaves an entry with `actor="user"` naming the application. A row the payload restates
    without moving anything writes nothing: an entry whose before and after are equal would say
    something happened at a moment when nothing did. The counts are disjoint and each says what it
    did — one row moved, one restated, one removed — and an empty payload is the statement that the
    portfolio holds nothing, which empties it.
    """
    seed_programs(db_session)
    client = TestClient(app)

    created = _put(
        client, [_row(REACH, tier="冲", isPrimary=True), _row(MATCH, tier="稳"), _row(SAFETY, tier="保")]
    )
    assert created.status_code == 200, created.text
    assert created.json() == {"created": 3, "updated": 0, "kept": 0, "removed": 0}
    safety_id = _stored(db_session, client.cookies[COOKIE_NAME])[SAFETY].id

    second = _put(
        client,
        [
            _row(REACH, tier="保", isPrimary=True),
            _row(MATCH, tier="稳"),
        ],
    )
    assert second.status_code == 200, second.text
    assert second.json() == {"created": 0, "updated": 1, "kept": 1, "removed": 1}, (
        "the four counts have to be disjoint and each has to mean what it says"
    )

    rows = _stored(db_session, client.cookies[COOKIE_NAME])
    events = _events(db_session, client.cookies[COOKIE_NAME])
    assert {event.actor for event in events} == {ApplicationOrigin.USER.value}, (
        f"every entry is the applicant's own: {[(e.event, e.actor) for e in events]}"
    )
    assert all(event.application_id for event in events), "an entry names no application"
    assert sorted(event.event for event in events) == [
        "created",
        "created",
        "created",
        "removed",
        "updated",
    ], f"{sorted((e.event, e.actor) for e in events)}"

    # The removed entry outlives the row it describes, which is why `task_events.application_id` is
    # not a foreign key: it still names the application that is gone, with the before side filled in.
    the_removed = next(event for event in events if event.event == "removed")
    assert the_removed.application_id == safety_id, "the removal does not name the row it removed"
    assert the_removed.before["program_id"] == SAFETY and the_removed.after is None
    the_moved = next(event for event in events if event.event == "updated")
    assert the_moved.before["tier"] == "冲" and the_moved.after["tier"] == "保", (
        "the retiered row's history does not carry both sides"
    )
    restated = rows[MATCH]
    assert not [
        event for event in events if event.application_id == restated.id and event.event != "created"
    ], "a restated row that moved nothing wrote an entry"

    emptied = _put(client, [])
    assert emptied.status_code == 200, emptied.text
    assert emptied.json() == {"created": 0, "updated": 0, "kept": 0, "removed": 2}
    assert client.get("/api/applications").json() == []
    assert _events(db_session, client.cookies[COOKIE_NAME])[-1].event == "removed"


def _subject(session) -> str:
    """One subject, written straight into `clients`, for the tests that drive the service."""
    client_id = str(uuid.uuid4())
    session.add(Client(id=client_id))
    session.commit()
    return client_id


def test_the_service_interface_serves_plain_mappings_and_keeps_the_omission_rule(
    require_db, db_session
):
    """`replace_applications(session, client_id, rows)` is callable without a schema in front of it.

    The route passes `ApplicationIn` instances, but the interface is a service, and a caller that
    hands it plain mappings — the shape its own tests use, and the shape `app.services.roadmap_tasks`
    documents for the same reason — has to get the same behaviour. The omission rule is what those
    mappings are here to check: a mapping that states a band and no deadline leaves the stored
    deadline where it is, because the two doors onto this rule must not answer differently.
    """
    seed_programs(db_session)
    client_id = _subject(db_session)

    created = replace_applications(
        db_session,
        client_id,
        [
            {
                "program_id": REACH,
                "tier": "冲",
                "is_primary": True,
                "official_deadline": date(2027, 1, 15),
            },
            {"program_id": MATCH, "tier": "稳"},
        ],
    )
    assert created == {"created": 2, "updated": 0, "kept": 0, "removed": 0}
    assert db_session.get(Application, _stored(db_session, client_id)[REACH].id).is_primary is True

    # The mapping says nothing about the deadline and drops MATCH, so the deadline stays and the row
    # that is no longer named goes.
    restated = replace_applications(
        db_session,
        client_id,
        [{"program_id": REACH, "tier": "冲", "is_primary": True}],
    )
    assert restated == {"created": 0, "updated": 0, "kept": 1, "removed": 1}
    rows = _stored(db_session, client_id)
    assert set(rows) == {REACH}
    assert rows[REACH].official_deadline == date(2027, 1, 15), (
        "a mapping that omits the deadline cleared it"
    )
    assert rows[REACH].tier == "冲"
    assert rows[REACH].origin == ApplicationOrigin.USER


def test_the_service_refuses_a_mapping_that_states_no_band(require_db, db_session):
    """The one required field, checked at the door a mapping caller comes through.

    `ApplicationIn` requires `tier`, but the service is callable without it, and the column has no
    default to fall back on: a row with no band would otherwise reach the `NOT NULL` column and come
    back as an `IntegrityError`, which is the 500 this check exists to prevent. Nothing is written,
    so the refusal leaves the portfolio as it was.
    """
    seed_programs(db_session)
    client_id = _subject(db_session)

    with pytest.raises(InvalidApplicationPayload) as raised:
        replace_applications(db_session, client_id, [{"program_id": REACH}])

    assert REACH in str(raised.value), "the refusal must name the row that states no band"
    assert _stored(db_session, client_id) == {}
    assert _events(db_session, client_id) == []
