"""The CRICOS catalogue seed and the fold of the placeholder slugs (spec: program-catalog)."""

import hashlib
import uuid
from pathlib import Path

from sqlalchemy import func, select

from app.models.application import Application
from app.models.client import Client
from app.models.program import Program, University
from app.models.source import Source
from app.seed import seed_programs
from app.seed_catalog import (
    COURSES_FILE,
    CRICOS_SOURCE_ID,
    LEGACY_SLUGS,
    load_courses,
    program_id,
    seed_catalog,
    study_area,
    university_id,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_COPY = REPO_ROOT / "web" / "prototype-fixtures" / "cricos-au-masters.json"


def seeded(session):
    seed_programs(session)
    return seed_catalog(session)


def test_the_api_copy_of_the_extract_matches_the_web_copy():
    """The API image cannot read web/, so it carries a copy; the two must never drift apart."""
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()  # noqa: E731
    assert digest(COURSES_FILE) == digest(WEB_COPY)


def test_every_extract_course_has_a_row_under_its_provider(db_session, require_db):
    seeded(db_session)
    courses = load_courses()
    ids = {program_id(c["code"]) for c in courses}
    stored = dict(db_session.execute(select(Program.id, Program.university_id).where(Program.id.in_(ids))).all())
    assert set(stored) == ids
    assert all(stored[program_id(c["code"])] == university_id(c["provider"]) for c in courses)


def test_catalogue_rows_state_no_requirement_and_are_not_verified(db_session, require_db):
    seeded(db_session)
    rows = db_session.scalars(select(Program).where(Program.source_id == CRICOS_SOURCE_ID)).all()
    assert len(rows) > 2000
    assert all(r.minimum_mark is None and r.non_211_minimum_mark is None and r.english_requirement is None for r in rows)
    assert {r.data_status for r in rows} == {"待核验"}
    assert db_session.get(Source, CRICOS_SOURCE_ID).verified_at is None


def test_the_seed_is_idempotent(db_session, require_db):
    seeded(db_session)
    second = seed_catalog(db_session)
    assert second["programs_added"] == 0
    assert second["programs_updated"] == 0
    assert second["universities_added"] == 0
    assert second["folded"] == 0


def test_hand_entered_rows_keep_their_requirements_and_source(db_session, require_db):
    seeded(db_session)
    sydney_cs = db_session.get(Program, "cricos-111671D")
    assert float(sydney_cs.minimum_mark) == 65
    assert sydney_cs.source_id != CRICOS_SOURCE_ID
    assert sydney_cs.name == "计算机科学硕士", "the catalogue must not overwrite a row another source describes"


def test_universities_carry_the_school_library_names(db_session, require_db):
    seeded(db_session)
    anu = db_session.get(University, "cricos-00120C")
    assert anu.name == "澳大利亚国立大学"
    assert anu.name_en.startswith("Australian National University")


def test_study_areas_follow_the_interface_taxonomy():
    assert study_area("02 - Information Technology", "0203 - Information Systems") == "计算机与数据"
    assert study_area("09 - Society and Culture", "0909 - Law") == "法律与犯罪学"
    assert study_area("01 - Natural and Physical Sciences", "0109 - Biological Sciences") == "生命科学"
    assert study_area("12 - Mixed Field Programmes", "1201 - General Education") is None


def _legacy_row(session, slug: str, university: str):
    session.add(Program(
        id=slug, university_id=university, name="placeholder", name_en="placeholder",
        degree_level="授课型硕士", source_id=CRICOS_SOURCE_ID, data_status="待核验",
    ))
    session.flush()


def test_a_portfolio_on_a_placeholder_slug_moves_to_its_cricos_row(db_session, require_db):
    seeded(db_session)
    client = Client(id=str(uuid.uuid4()))
    db_session.add(client)
    _legacy_row(db_session, "usyd-master-cs", "usyd")
    _legacy_row(db_session, "monash-master-cs", "monash")
    db_session.add_all([
        Application(id=str(uuid.uuid4()), client_id=client.id, program_id="usyd-master-cs", tier="稳", status="applying", is_primary=True),
        Application(id=str(uuid.uuid4()), client_id=client.id, program_id="monash-master-cs", tier="冲"),
    ])
    db_session.commit()

    result = seed_catalog(db_session)

    assert result["folded"] == 2
    rows = db_session.scalars(select(Application).where(Application.client_id == client.id)).all()
    assert [(r.program_id, r.status, r.is_primary, r.tier) for r in rows] == [("cricos-111671D", "applying", True, "稳")]
    assert db_session.get(Program, "usyd-master-cs") is None
    assert db_session.get(Program, "monash-master-cs") is None
    assert LEGACY_SLUGS["monash-master-cs"] is None


def test_no_placeholder_slug_survives_a_seed(db_session, require_db):
    seeded(db_session)
    left = db_session.scalar(select(func.count()).select_from(Program).where(Program.id.in_(list(LEGACY_SLUGS))))
    assert left == 0
