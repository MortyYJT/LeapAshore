"""Merging university rows that are one school, without losing anything an applicant wrote."""

import uuid

import pytest
from sqlalchemy import delete, select

from app.collect.importer import import_school
from app.collect.merge_schools import duplicate_groups, main, merge
from app.models.application import Application
from app.models.client import Client
from app.models.program import Program, University
from app.models.roadmap import MaterialTemplate, RoadmapPhase
from app.models.snapshot import SnapshotPage
from app.models.source import Source
from app.models.task import RoadmapTask
from app.seed_catalog import load_providers, university_id

KEEP = "test-merge-keep"
DUP = "test-merge-dup"
EMPTY = "test-merge-empty"
NAME_EN = "Test Merge University"


@pytest.fixture
def schools(db_session, require_db):
    """Three rows of one school: the kept one (one program), a duplicate (two programs, a cited page,
    a snapshot page, a portfolio row and a roadmap task on one of its programs) and an empty one."""
    client = Client(id=str(uuid.uuid4()))
    db_session.add_all([
        University(id=KEEP, name="合并测试大学", name_en=NAME_EN, country="澳大利亚"),
        University(id=DUP, name="合并测试大学", name_en=NAME_EN, country="澳大利亚",
                   official_url="https://merge.test/", city="Toowoomba"),
        University(id=EMPTY, name="合并测试大学", name_en=NAME_EN, country="澳大利亚"),
        client,
    ])
    db_session.flush()
    source_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "https://merge.test/mds"))
    db_session.add(Source(id=source_id, url="https://merge.test/mds", title="MDS", publisher=DUP, domain="merge.test"))
    db_session.flush()
    db_session.add_all([
        Program(id="test-merge-p0", university_id=KEEP, name="P0", data_status="机器核对", source_id=source_id),
        Program(id="test-merge-p1", university_id=DUP, name="P1", data_status="机器核对", source_id=source_id),
        Program(id="test-merge-p2", university_id=DUP, name="P2", data_status="机器核对", source_id=source_id),
    ])
    db_session.flush()
    db_session.add(SnapshotPage(id=str(uuid.uuid4()), url="https://merge.test/fees", school_key="test-merge",
                                university_id=DUP, program_id=None, snapshot_sha256="d" * 64,
                                content_sha256="e" * 64, title="Fees", chunker="t", chunk_count=0))
    db_session.add(Application(id=str(uuid.uuid4()), client_id=client.id, program_id="test-merge-p1", tier="稳"))
    phase, material = f"test-phase-{uuid.uuid4().hex[:8]}", f"test-material-{uuid.uuid4().hex[:8]}"
    db_session.add(RoadmapPhase(key=phase, title="测试阶段", offset_days=30, sort_order=0))
    db_session.flush()
    db_session.add(MaterialTemplate(key=material, phase=phase, title="测试材料", applies_to="all", sort_order=0))
    db_session.flush()
    db_session.add(RoadmapTask(id=str(uuid.uuid4()), client_id=client.id, material_key=material,
                               program_id="test-merge-p1", phase=phase))
    db_session.commit()
    yield client.id
    db_session.rollback()
    db_session.execute(delete(RoadmapTask).where(RoadmapTask.client_id == client.id))
    db_session.execute(delete(Application).where(Application.client_id == client.id))
    db_session.execute(delete(SnapshotPage).where(SnapshotPage.url == "https://merge.test/fees"))
    db_session.execute(delete(Program).where(Program.id.like("test-merge-%")))
    db_session.execute(delete(Source).where(Source.id == source_id))
    db_session.execute(delete(University).where(University.id.in_([KEEP, DUP, EMPTY])))
    db_session.execute(delete(Client).where(Client.id == client.id))
    db_session.execute(delete(MaterialTemplate).where(MaterialTemplate.key == material))
    db_session.execute(delete(RoadmapPhase).where(RoadmapPhase.key == phase))
    db_session.commit()


def test_same_name_rows_are_listed_as_one_group(db_session, schools):
    group = next(g for g in duplicate_groups(db_session) if g["name_en"] == NAME_EN)
    assert {row["id"]: row["programs"] for row in group["rows"]} == {KEEP: 1, DUP: 2, EMPTY: 0}
    assert {row["id"]: row["snapshot_pages"] for row in group["rows"]}[DUP] == 1


def test_merging_moves_programs_pages_and_sources_and_deletes_only_the_duplicates(db_session, schools):
    client_id = schools
    report = merge(db_session, KEEP, [DUP, EMPTY])
    db_session.commit()
    assert report == {"keep": KEEP, "merged": [DUP, EMPTY], "programs_moved": 2, "snapshot_pages_moved": 1,
                      "sources_repointed": 1}
    assert db_session.get(University, DUP) is None and db_session.get(University, EMPTY) is None
    assert set(db_session.scalars(select(Program.id).where(Program.university_id == KEEP))) == {
        "test-merge-p0", "test-merge-p1", "test-merge-p2"}
    assert db_session.scalar(select(SnapshotPage.university_id).where(SnapshotPage.url == "https://merge.test/fees")) == KEEP
    assert db_session.scalar(select(Source.publisher).where(Source.url == "https://merge.test/mds")) == KEEP
    # What the applicant wrote names programs, whose ids did not change.
    assert db_session.scalar(select(Application.program_id).where(Application.client_id == client_id)) == "test-merge-p1"
    assert db_session.scalar(select(RoadmapTask.program_id).where(RoadmapTask.client_id == client_id)) == "test-merge-p1"
    # The kept row takes what it lacked from the duplicate and keeps what it had.
    kept = db_session.get(University, KEEP)
    assert (kept.official_url, kept.city, kept.name) == ("https://merge.test/", "Toowoomba", "合并测试大学")


def test_merging_twice_changes_nothing_the_second_time(db_session, schools):
    merge(db_session, KEEP, [DUP])
    db_session.commit()
    with pytest.raises(ValueError, match="no university"):
        merge(db_session, KEEP, [DUP])


@pytest.mark.parametrize("keep, dups, message", [
    (KEEP, [KEEP], "itself"), ("test-merge-missing", [DUP], "no university"), (KEEP, [], "nothing to merge"),
])
def test_a_merge_that_makes_no_sense_is_refused_before_touching_anything(db_session, schools, keep, dups, message):
    with pytest.raises(ValueError, match=message):
        merge(db_session, keep, dups)
    db_session.rollback()
    assert db_session.get(University, DUP) is not None


def test_without_apply_the_command_only_reports(db_session, schools, capsys):
    assert main([KEEP, DUP]) == 0
    assert '"programs_moved": 2' in capsys.readouterr().out
    db_session.expire_all()
    assert db_session.get(University, DUP) is not None
    assert db_session.scalar(select(Program.university_id).where(Program.id == "test-merge-p1")) == DUP


# ---- not again ----------------------------------------------------------------------------------------


def test_every_cricos_provider_of_one_institution_lands_on_one_row():
    """University of Southern Queensland (00244B, 02225M) and Victoria University (00124K, 02475D) each
    hold two CRICOS provider codes; one row per institution, not per code."""
    by_name: dict[str, set[str]] = {}
    for code, identity in load_providers().items():
        by_name.setdefault(identity["name_en"], set()).add(university_id(code))
    assert {name: ids for name, ids in by_name.items() if len(ids) > 1} == {}
    assert university_id("02225M") == university_id("00244B") == "cricos-00244B"
    assert university_id("02475D") == university_id("00124K") == "cricos-00124K"


def test_an_australian_file_whose_courses_have_no_catalogue_row_makes_no_school_row(db_session, require_db, tmp_path):
    """Before, a file none of whose CRICOS courses was in the catalogue made a second row for the school
    under its file key (`deakin-university` next to `cricos-00113B`, 12 such rows in production)."""
    key = "test-merge-au-school"
    data = {"school_key": key, "school_name_en": NAME_EN, "country": "Australia",
            "listing_urls": ["https://merge.test/"], "programs": [{
                "name": "Master of Nothing", "url": "https://merge.test/mn", "snapshot_sha256": "f" * 64,
                "cricos_code": "000000X", "status": "机器核对",
                "fields": {"academic": {"text": "A degree", "quote": "A degree", "check": "ok"}}}]}
    schools = {key: {"school_key": key, "cricos_institution": NAME_EN, "country": "Australia"}}
    try:
        report = import_school(db_session, data, schools, root=tmp_path)
        assert db_session.get(University, key) is None
        assert report["programs_added"] == 0 and report.get("no_catalogue_row") == 1
    finally:
        db_session.rollback()
        db_session.execute(delete(University).where(University.id == key))
        db_session.commit()
