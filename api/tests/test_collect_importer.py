"""Importing checked requirement files into the catalogue."""

import pytest
from sqlalchemy import delete, func, select

from app.collect.importer import import_school, program_id_for, source_id_for
from app.collect.verify import SchemaError
from app.models.program import Program, ProgramPrerequisite, University
from app.models.source import Source, SourceVersion
from app.seed import seed_programs
from app.seed_catalog import seed_catalog

KEY = "test-importer-university"
SHA = "c" * 64
URL = "https://example.test/msc-data-science"
SCHOOLS = {KEY: {"school_key": KEY, "name_zh": "测试大学", "country": "United Kingdom"}}


def school_file(**field_overrides):
    fields = {
        "academic": {"text": "2:1 honours", "quote": "a 2:1 honours degree", "check": "ok"},
        "ielts": {"overall": 7.0, "min_band": 6.5, "quote": "IELTS 7.0 with 6.5 in each component", "check": "ok"},
        "china_requirement": {"min_mark_211": 80, "min_mark_other": 85, "quote": "80% (211) or 85%", "check": "ok"},
        "prerequisites": [{"text": "linear algebra", "quote": "linear algebra", "check": "ok"}],
    }
    fields.update(field_overrides)
    every_ok = all(
        (all(i["check"] == "ok" for i in f) if isinstance(f, list) else f["check"] == "ok") for f in fields.values()
    )
    return {
        "school_key": KEY, "school_name_en": "Test Importer University", "country": "United Kingdom",
        "listing_urls": ["https://example.test/courses"],
        "programs": [{
            "name": "MSc Data Science", "url": URL, "snapshot_sha256": SHA, "fetched_at": "2026-10-29T01:00:00+00:00",
            "fields": fields, "status": "机器核对" if every_ok else "待人工",
        }],
    }


@pytest.fixture
def cleanup(db_session):
    yield
    pid = program_id_for(KEY, {"url": URL, "name": "MSc Data Science"})
    db_session.rollback()
    db_session.execute(delete(ProgramPrerequisite).where(ProgramPrerequisite.program_id == pid))
    db_session.execute(delete(Program).where(Program.id == pid))
    db_session.execute(delete(SourceVersion).where(SourceVersion.source_id == source_id_for(URL)))
    db_session.execute(delete(Source).where(Source.id == source_id_for(URL)))
    db_session.execute(delete(University).where(University.id == KEY))
    db_session.commit()


def test_a_checked_program_is_imported_as_machine_checked_and_never_verified(db_session, require_db, cleanup, tmp_path):
    result = import_school(db_session, school_file(), SCHOOLS, root=tmp_path)
    assert result["programs_added"] == 1
    program = db_session.get(Program, program_id_for(KEY, {"url": URL, "name": "MSc Data Science"}))
    assert program.data_status == "机器核对"
    assert program.english_requirement == "IELTS 7.0，单项不低于 6.5"
    assert (float(program.minimum_mark), float(program.non_211_minimum_mark)) == (80, 85)
    assert [p.label for p in program.prerequisites] == ["linear algebra"]
    assert db_session.get(University, KEY).name == "测试大学"
    assert db_session.get(University, KEY).country == "英国"
    source = db_session.get(Source, source_id_for(URL))
    assert source.verified_at is None and source.status == "待核验"
    version = db_session.scalars(select(SourceVersion).where(SourceVersion.source_id == source.id)).one()
    assert version.status == "pending_review" and version.content_sha256 == SHA
    assert "[ielts] IELTS 7.0 with 6.5 in each component" in version.body_text


def test_a_collected_program_is_filed_under_the_study_area_its_name_points_to(db_session, require_db, cleanup, tmp_path):
    import_school(db_session, school_file(), SCHOOLS, root=tmp_path)
    program = db_session.get(Program, program_id_for(KEY, {"url": URL, "name": "MSc Data Science"}))
    assert program.field == "计算机与数据"


def test_a_row_with_a_study_area_keeps_it(db_session, require_db, cleanup, tmp_path):
    import_school(db_session, school_file(), SCHOOLS, root=tmp_path)
    program = db_session.get(Program, program_id_for(KEY, {"url": URL, "name": "MSc Data Science"}))
    program.field = "自然科学与数学"
    db_session.commit()

    import_school(db_session, school_file(), SCHOOLS, root=tmp_path)

    assert db_session.get(Program, program.id).field == "自然科学与数学"


def test_a_field_that_failed_its_check_is_not_written(db_session, require_db, cleanup, tmp_path):
    data = school_file(ielts={"overall": 7.0, "quote": "IELTS 7", "check": "quote not found in snapshot"},
                       china_requirement={"min_mark_211": 80, "quote": "80%", "check": "quote not found in snapshot"})
    import_school(db_session, data, SCHOOLS, root=tmp_path)
    program = db_session.get(Program, program_id_for(KEY, {"url": URL, "name": "MSc Data Science"}))
    assert program.english_requirement is None
    assert program.minimum_mark is None
    assert program.data_status == "待核验"


def test_importing_twice_adds_nothing(db_session, require_db, cleanup, tmp_path):
    import_school(db_session, school_file(), SCHOOLS, root=tmp_path)
    again = import_school(db_session, school_file(), SCHOOLS, root=tmp_path)
    assert again["programs_added"] == 0
    versions = db_session.scalar(select(func.count()).select_from(SourceVersion).where(SourceVersion.source_id == source_id_for(URL)))
    assert versions == 1


def test_an_australian_program_lands_on_its_cricos_row(db_session, require_db, tmp_path):
    seed_programs(db_session)
    seed_catalog(db_session)
    url = "https://example.test/au-course-for-importer-test"
    data = {
        "school_key": "university-of-sydney", "school_name_en": "The University of Sydney", "country": "Australia",
        "programs": [{
            "name": "Master of Data Science", "url": url, "cricos_code": "087981E", "snapshot_sha256": SHA,
            "fields": {"ielts": {"overall": 7.0, "min_band": 6.0, "quote": "IELTS 7.0 overall, 6.0 each", "check": "ok"}},
            "status": "机器核对",
        }],
    }
    row = db_session.get(Program, "cricos-087981E")
    before = (row.source_id, row.english_requirement, row.data_status)
    try:
        result = import_school(db_session, data, {}, root=tmp_path)
        assert result == {"school": "university-of-sydney", "programs_added": 0, "programs_updated": 1}
        row = db_session.get(Program, "cricos-087981E")
        assert row.university_id == "usyd"
        assert row.english_requirement == "IELTS 7.0，单项不低于 6.0"
        assert row.data_status == "机器核对"
    finally:
        row.source_id, row.english_requirement, row.data_status = before
        db_session.flush()
        db_session.execute(delete(SourceVersion).where(SourceVersion.source_id == source_id_for(url)))
        db_session.execute(delete(Source).where(Source.id == source_id_for(url)))
        db_session.commit()


def test_a_program_with_nothing_verified_leaves_its_row_alone(db_session, require_db, tmp_path):
    seed_programs(db_session)
    seed_catalog(db_session)
    before = db_session.get(Program, "cricos-103000K")
    snapshot = (before.minimum_mark, before.english_requirement, before.source_id, before.data_status)
    data = {"school_key": "monash-university", "school_name_en": "Monash University", "country": "Australia",
            "programs": [{"name": "Master of Artificial Intelligence", "url": "https://handbook.example/c6007",
                          "cricos_code": "103000K", "snapshot_sha256": SHA, "fields": {}, "status": "待人工"}]}
    result = import_school(db_session, data, {}, root=tmp_path)
    assert result["programs_updated"] == 0
    after = db_session.get(Program, "cricos-103000K")
    assert (after.minimum_mark, after.english_requirement, after.source_id, after.data_status) == snapshot


def test_a_quote_from_a_shared_page_names_that_page(db_session, require_db, cleanup, tmp_path):
    data = school_file(china_requirement={"min_mark_211": 80, "min_mark_other": 85, "quote": "80% (211) or 85%",
                                          "check": "ok", "source_sha256": "d" * 64,
                                          "source_url": "https://example.test/china"})
    import_school(db_session, data, SCHOOLS, root=tmp_path)
    version = db_session.scalars(select(SourceVersion).where(SourceVersion.source_id == source_id_for(URL))).one()
    assert "[china_requirement] 80% (211) or 85% (出处: https://example.test/china)" in version.body_text


def test_new_content_on_a_reviewed_page_returns_it_to_unverified(db_session, require_db, cleanup, tmp_path):
    from datetime import datetime, timezone

    import_school(db_session, school_file(), SCHOOLS, root=tmp_path)
    source = db_session.get(Source, source_id_for(URL))
    source.status, source.verified_at = "已核验", datetime.now(timezone.utc)
    db_session.commit()
    changed = school_file()
    changed["programs"][0]["snapshot_sha256"] = "e" * 64
    import_school(db_session, changed, SCHOOLS, root=tmp_path)
    source = db_session.get(Source, source_id_for(URL))
    assert source.status == "待核验" and source.verified_at is None


def test_two_prerequisites_of_a_long_named_program_get_distinct_ids(db_session, require_db, tmp_path):
    long_name = "Master of Business Administration in Global Supply Chain and Operations Strategy"
    url = "https://example.test/very-long-programme-name"
    data = school_file(prerequisites=[{"text": "GMAT", "quote": "GMAT", "check": "ok"},
                                      {"text": "two years of work", "quote": "two years", "check": "ok"}])
    data["programs"][0].update({"name": long_name, "url": url})
    pid = program_id_for(KEY, {"url": url, "name": long_name})
    assert len(pid) <= 64
    try:
        import_school(db_session, data, SCHOOLS, root=tmp_path)
        labels = [p.label for p in db_session.get(Program, pid).prerequisites]
        assert sorted(labels) == ["GMAT", "two years of work"]
    finally:
        db_session.rollback()
        db_session.execute(delete(ProgramPrerequisite).where(ProgramPrerequisite.program_id == pid))
        db_session.execute(delete(Program).where(Program.id == pid))
        db_session.execute(delete(SourceVersion).where(SourceVersion.source_id == source_id_for(url)))
        db_session.execute(delete(Source).where(Source.id == source_id_for(url)))
        db_session.execute(delete(University).where(University.id == KEY))
        db_session.commit()


def test_two_programs_on_one_page_get_distinct_ids():
    """A page can list two variants whose names differ only past the slug's length (45 vs 65 credits)."""
    url = "https://example.edu/health-management"
    short = program_id_for("example-university", {"name": "Master of Science in Health Management (45-credit)", "url": url})
    long = program_id_for("example-university", {"name": "Master of Science in Health Management (65-credit)", "url": url})
    assert short != long
    assert len(short) <= 64 and len(long) <= 64


def test_no_two_collected_programs_share_an_id():
    """Across every committed requirement file: a collision would make one program overwrite another."""
    import json
    from pathlib import Path

    seen: dict[str, str] = {}
    for path in sorted((Path(__file__).resolve().parents[1] / "data" / "requirements").glob("*.json")):
        if path.name.startswith("_"):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for program in data["programs"]:
            key = program_id_for(data["school_key"], program)
            where = f"{path.name}: {program['name']}"
            assert key not in seen or program.get("cricos_code"), f"{where} and {seen.get(key)} share {key}"
            seen[key] = where


def test_a_recommended_score_is_not_written_as_a_minimum():
    """"We recommend at least 7.5" is not a threshold; the interface compares any `IELTS <n>` it finds."""
    import re

    from app.collect.importer import english_text

    fields = {
        "ielts": {"overall": 7.5, "recommended": True, "quote": "we recommend that you aim for at least IELTS 7.5", "check": "ok"},
        "toefl": {"overall": 90, "quote": "minimum TOEFL 90", "check": "ok"},
    }
    text = english_text(fields)
    assert text == "建议雅思 7.5（非最低要求）；TOEFL iBT 90"
    assert not re.search(r"IELTS\s*\d", text)


def test_recommended_must_be_a_flag():
    from app.collect.verify import validate

    with pytest.raises(SchemaError):
        validate({"school_key": "x", "school_name_en": "X", "programs": [{
            "name": "M", "url": "https://x.edu", "snapshot_sha256": "a" * 64,
            "fields": {"ielts": {"overall": 7, "recommended": "yes", "quote": "q"}}}]})


def test_pruning_removes_rows_the_file_no_longer_lists_but_keeps_one_a_portfolio_holds(db_session, require_db, cleanup, tmp_path):
    """A program dropped from a school's file leaves the catalogue, unless someone's portfolio names it."""
    import uuid

    from app.collect.importer import prune_school
    from app.models.application import Application
    from app.models.client import Client

    import_school(db_session, school_file(), SCHOOLS, root=tmp_path)
    for orphan in (f"{KEY}-dropped-a", f"{KEY}-dropped-b"):
        db_session.add(Program(id=orphan, university_id=KEY, name=orphan, data_status="机器核对", source_id=source_id_for(URL)))
    client = Client(id=str(uuid.uuid4()))
    db_session.add(client)
    db_session.flush()
    db_session.add(Application(id=str(uuid.uuid4()), client_id=client.id, program_id=f"{KEY}-dropped-b", tier="稳妥"))
    db_session.commit()
    try:
        result = prune_school(db_session, school_file(), SCHOOLS)
        assert result == {"school": KEY, "pruned": 1, "kept_in_portfolios": [f"{KEY}-dropped-b"]}
        assert db_session.get(Program, f"{KEY}-dropped-a") is None
        assert db_session.get(Program, program_id_for(KEY, {"url": URL, "name": "MSc Data Science"})) is not None
    finally:
        db_session.rollback()
        db_session.execute(delete(Application).where(Application.client_id == client.id))
        db_session.execute(delete(Program).where(Program.id.in_([f"{KEY}-dropped-a", f"{KEY}-dropped-b"])))
        db_session.execute(delete(Client).where(Client.id == client.id))
        db_session.commit()


# ---- deadlines and the academic requirement (TASKS.md P1 #1, openspec requirement-dates) ----------

DEADLINES = [
    {"label": "Round 1", "date": "2026-11-15", "quote": "Round 1 closes 15 November 2026", "check": "ok"},
    {"label": "Round 2", "date": "2027-01-31", "quote": "Round 2 closes 31 January 2027", "check": "ok",
     "source_sha256": "d" * 64, "source_url": "https://example.test/deadlines"},
    {"label": "Round 3", "date": "2027-03-31", "quote": "Round 3 closes 31 March", "check": "date not in quote"},
]


def _deadline_rows(session, pid):
    from app.models.program import ProgramDeadline

    return [
        (row.label, row.deadline.isoformat(), row.source_url, row.quote, row.sort_order)
        for row in session.scalars(
            select(ProgramDeadline).where(ProgramDeadline.program_id == pid).order_by(ProgramDeadline.sort_order))
    ]


def test_verified_deadlines_and_the_academic_requirement_are_imported(db_session, require_db, cleanup, tmp_path):
    import_school(db_session, school_file(deadlines=DEADLINES), SCHOOLS, root=tmp_path)
    pid = program_id_for(KEY, {"url": URL, "name": "MSc Data Science"})
    program = db_session.get(Program, pid)
    assert program.academic_requirement == "2:1 honours"
    # The failed third round is absent; a quote from a shared page cites that page, others the program page.
    assert _deadline_rows(db_session, pid) == [
        ("Round 1", "2026-11-15", URL, "Round 1 closes 15 November 2026", 0),
        ("Round 2", "2027-01-31", "https://example.test/deadlines", "Round 2 closes 31 January 2027", 1),
    ]
    assert db_session.get(Source, source_id_for(URL)).verified_at is None


def test_an_academic_requirement_that_failed_its_check_stays_unknown(db_session, require_db, cleanup, tmp_path):
    data = school_file(academic={"text": "2:1 honours", "quote": "a 2:1", "check": "quote not found in snapshot"})
    import_school(db_session, data, SCHOOLS, root=tmp_path)
    program = db_session.get(Program, program_id_for(KEY, {"url": URL, "name": "MSc Data Science"}))
    assert program.academic_requirement is None


def test_rerunning_the_import_writes_nothing(db_session, require_db, cleanup, tmp_path):
    from app.models.program import ProgramDeadline

    import_school(db_session, school_file(deadlines=DEADLINES), SCHOOLS, root=tmp_path)
    pid = program_id_for(KEY, {"url": URL, "name": "MSc Data Science"})

    def state():
        db_session.expire_all()
        program = db_session.get(Program, pid)
        deadlines = [(r.id, r.label, r.deadline, r.source_url, r.quote, r.sort_order)
                     for r in db_session.scalars(select(ProgramDeadline).where(ProgramDeadline.program_id == pid)
                                                 .order_by(ProgramDeadline.sort_order))]
        prerequisites = [(r.id, r.label) for r in program.prerequisites]
        versions = db_session.scalar(select(func.count()).select_from(SourceVersion)
                                     .where(SourceVersion.source_id == source_id_for(URL)))
        return program.updated_at, program.academic_requirement, deadlines, prerequisites, versions

    before = state()
    import_school(db_session, school_file(deadlines=DEADLINES), SCHOOLS, root=tmp_path)
    assert state() == before


def test_a_changed_deadline_list_replaces_the_stored_one(db_session, require_db, cleanup, tmp_path):
    import_school(db_session, school_file(deadlines=DEADLINES), SCHOOLS, root=tmp_path)
    moved = [dict(DEADLINES[1], date="2027-02-07", quote="Round 2 closes 7 February 2027")]
    import_school(db_session, school_file(deadlines=moved), SCHOOLS, root=tmp_path)
    pid = program_id_for(KEY, {"url": URL, "name": "MSc Data Science"})
    assert _deadline_rows(db_session, pid) == [
        ("Round 2", "2027-02-07", "https://example.test/deadlines", "Round 2 closes 7 February 2027", 0),
    ]


def test_a_toefl_minimum_on_the_new_six_point_scale_says_so():
    """NTU states TOEFL iBT 4.5 on the 1-6 scale from January 2026; it is not a score of 4.5 out of 120."""
    from app.collect.importer import english_text

    fields = {"toefl": {"overall": 4.5, "scale": "iBT 1-6", "quote": "A TOEFL iBT score of 4.5 or more", "check": "ok"}}
    assert english_text(fields) == "TOEFL iBT 4.5（新版 1–6 分制）"


def test_the_import_never_touches_a_date_somebody_entered(
    db_session, require_db, cleanup, tmp_path, clear_the_roadmap_definition_after_the_test
):
    """The portfolio row's own deadline and a user's roadmap row keep their dates through an import."""
    import uuid
    from datetime import date

    from app.models.application import Application
    from app.models.client import Client
    from app.models.task import RoadmapTask
    from app.seed_roadmap import seed_roadmap

    seed_roadmap(db_session)
    import_school(db_session, school_file(), SCHOOLS, root=tmp_path)
    pid = program_id_for(KEY, {"url": URL, "name": "MSc Data Science"})
    client = Client(id=str(uuid.uuid4()))
    db_session.add(client)
    db_session.flush()
    db_session.add(Application(id=str(uuid.uuid4()), client_id=client.id, program_id=pid, tier="稳",
                               official_deadline=date(2027, 1, 2), deadline_source_url="https://example.test/mine"))
    db_session.add(RoadmapTask(id=str(uuid.uuid4()), client_id=client.id, material_key="sub-form", program_id=pid,
                               phase="submission", due_at=date(2027, 1, 1), schedule_origin="user", origin="user"))
    db_session.commit()

    def entered():
        db_session.expire_all()
        app_row = db_session.scalars(select(Application).where(Application.client_id == client.id)).one()
        task = db_session.scalars(select(RoadmapTask).where(RoadmapTask.client_id == client.id)).one()
        return (app_row.official_deadline, app_row.deadline_source_url, app_row.updated_at,
                task.due_at, task.schedule_origin, task.origin, task.updated_at)

    before = entered()
    try:
        import_school(db_session, school_file(deadlines=DEADLINES), SCHOOLS, root=tmp_path)
        assert entered() == before
    finally:
        db_session.rollback()
        db_session.execute(delete(RoadmapTask).where(RoadmapTask.client_id == client.id))
        db_session.execute(delete(Application).where(Application.client_id == client.id))
        db_session.execute(delete(Client).where(Client.id == client.id))
        db_session.commit()
