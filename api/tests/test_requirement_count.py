"""One definition of "this program has a stated requirement", shared by every count of it.

The catalogue's "只看已收录要求" filter, the school library's "有要求 N" and the advisor's evidence gate
used to disagree: the first two counted a 985/211 mark or an English line only, so a program whose page
gave only a prerequisite or only a mark for other universities was shown with a requirement on its own
page and in the advisor, yet counted as having none in the catalogue. These tests pin the three to the
same rule, on a school of their own that they remove again.
"""

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app.db import SessionLocal
from app.main import app
from app.models.program import Program, ProgramPrerequisite, University, has_requirement_data
from app.models.source import Source, SourceStatus


def _school_with_one_program_per_kind(session, marker: str) -> tuple[str, dict[str, str]]:
    university_id = f"test-stated-{marker}"
    source_id = f"test-stated-source-{marker}"
    session.add(University(id=university_id, name=f"要求口径测试大学 {marker}"))
    session.add(Source(id=source_id, url=f"https://example.edu/stated-{marker}", title="Stated requirement test",
                       status=SourceStatus.UNVERIFIED))
    session.flush()
    kinds = {
        "english": {"english_requirement": "IELTS 6.5"},
        "mark": {"minimum_mark": 80},
        "other_mark": {"non_211_minimum_mark": 85},
        "prerequisite": {},
        "nothing": {},
    }
    ids = {}
    for kind, values in kinds.items():
        ids[kind] = f"{university_id}-{kind}"
        session.add(Program(id=ids[kind], university_id=university_id, name=kind, source_id=source_id,
                            data_status="待核验", **values))
    session.flush()
    session.add(ProgramPrerequisite(id=f"{ids['prerequisite']}-pre-0", program_id=ids["prerequisite"],
                                    label="Calculus", sort_order=0))
    session.commit()
    return university_id, ids


def _remove(university_id: str) -> None:
    with SessionLocal() as cleanup:
        ids = select(Program.id).where(Program.university_id == university_id)
        cleanup.execute(delete(ProgramPrerequisite).where(ProgramPrerequisite.program_id.in_(ids)))
        cleanup.execute(delete(Program).where(Program.university_id == university_id))
        cleanup.execute(delete(Source).where(Source.id == f"test-stated-source-{university_id.removeprefix('test-stated-')}"))
        cleanup.execute(delete(University).where(University.id == university_id))
        cleanup.commit()


def test_every_count_of_stated_requirements_uses_one_rule(require_db, db_session):
    university_id, ids = _school_with_one_program_per_kind(db_session, uuid4().hex[:8])
    expected = {ids["english"], ids["mark"], ids["other_mark"], ids["prerequisite"]}
    try:
        client = TestClient(app)
        stated = client.get("/api/programs", params={"provider": university_id, "has_requirements": "true"})
        unstated = client.get("/api/programs", params={"provider": university_id, "has_requirements": "false"})
        assert {p["slug"] for p in stated.json()} == expected
        assert stated.headers["X-Total-Count"] == "4"
        assert [p["slug"] for p in unstated.json()] == [ids["nothing"]]

        school = next(u for u in client.get("/api/universities").json() if u["id"] == university_id)
        assert (school["programCount"], school["withRequirementsCount"]) == (5, 4)

        with SessionLocal() as session:
            gated = set(session.scalars(
                select(Program.id).where(Program.university_id == university_id, has_requirement_data())))
            assert gated == expected
            assert session.scalar(select(func.count()).select_from(Program).where(
                Program.university_id == university_id, ~has_requirement_data())) == 1
    finally:
        _remove(university_id)


def test_programs_with_a_stated_requirement_still_come_first(require_db, db_session):
    university_id, ids = _school_with_one_program_per_kind(db_session, uuid4().hex[:8])
    try:
        body = TestClient(app).get("/api/programs", params={"provider": university_id}).json()
        assert [p["slug"] for p in body][-1] == ids["nothing"]
    finally:
        _remove(university_id)


def test_the_advisor_gate_is_the_same_rule():
    from app.agent import evidence

    assert evidence.has_requirement_data is has_requirement_data
