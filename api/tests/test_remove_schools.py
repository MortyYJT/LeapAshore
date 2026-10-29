"""Removing out-of-scope schools from the catalogue without losing anything an applicant wrote."""

import uuid

import pytest
from sqlalchemy import delete, select

from app.collect.remove_schools import main, remove_universities
from app.models.application import Application
from app.models.client import Client
from app.models.document import Document
from app.models.program import Program, ProgramPrerequisite, University
from app.models.roadmap import MaterialTemplate, RoadmapPhase
from app.models.source import Source, SourceVersion
from app.models.task import RoadmapTask

GONE = "test-remove-gone-university"
OTHER = "test-remove-other-university"


def _source(session, url: str) -> str:
    sid = str(uuid.uuid5(uuid.NAMESPACE_URL, url))
    session.add(Source(id=sid, url=url, title=url, publisher=GONE, domain="example.test"))
    session.flush()
    session.add(SourceVersion(id=str(uuid.uuid4()), source_id=sid, version_no=1, body_text="quote"))
    return sid


def _program(session, pid: str, university: str, source_id: str) -> None:
    session.add(Program(id=pid, university_id=university, name=pid, data_status="机器核对", source_id=source_id))
    session.flush()
    session.add(ProgramPrerequisite(id=f"{pid}-pre", program_id=pid, label="calculus", sort_order=0))


@pytest.fixture
def catalogue(db_session, require_db):
    """One school to remove (three programs) and one to keep, which cites one of its pages."""
    db_session.add_all([
        University(id=GONE, name="移除测试大学", country="日本"),
        University(id=OTHER, name="保留测试大学", country="英国"),
    ])
    db_session.flush()
    own = _source(db_session, "https://gone.example.test/a")
    shared = _source(db_session, "https://gone.example.test/shared")
    orphan = _source(db_session, "https://gone.example.test/orphan")  # an earlier import's leftover
    _program(db_session, f"{GONE}-a", GONE, own)
    _program(db_session, f"{GONE}-b", GONE, shared)
    _program(db_session, f"{GONE}-c", GONE, own)
    _program(db_session, f"{OTHER}-x", OTHER, shared)
    db_session.commit()
    sources = {"own": own, "shared": shared, "orphan": orphan}
    yield sources
    db_session.rollback()
    ids = [f"{GONE}-a", f"{GONE}-b", f"{GONE}-c", f"{OTHER}-x"]
    clients = list(db_session.scalars(select(Application.client_id).where(Application.program_id.in_(ids))))
    clients += list(db_session.scalars(select(Document.client_id).where(Document.program_id.in_(ids))))
    db_session.execute(delete(Application).where(Application.program_id.in_(ids)))
    db_session.execute(delete(Document).where(Document.program_id.in_(ids)))
    db_session.execute(delete(Client).where(Client.id.in_(clients)))
    db_session.execute(delete(ProgramPrerequisite).where(ProgramPrerequisite.program_id.in_(ids)))
    db_session.execute(delete(Program).where(Program.id.in_(ids)))
    db_session.execute(delete(SourceVersion).where(SourceVersion.source_id.in_(sources.values())))
    db_session.execute(delete(Source).where(Source.id.in_(sources.values())))
    db_session.execute(delete(University).where(University.id.in_([GONE, OTHER])))
    db_session.commit()


def _client(session) -> str:
    client = Client(id=str(uuid.uuid4()))
    session.add(client)
    session.flush()
    return client.id


def test_a_school_leaves_with_its_programs_and_the_pages_only_it_cited(db_session, catalogue):
    report = remove_universities(db_session, [GONE])
    db_session.commit()

    assert report == [{
        "university": GONE, "programs_removed": 3, "sources_removed": 2,
        "kept_programs": [], "university_removed": True,
    }]
    assert db_session.get(University, GONE) is None
    assert db_session.scalars(select(Program).where(Program.university_id == GONE)).all() == []
    assert db_session.scalars(
        select(ProgramPrerequisite).where(ProgramPrerequisite.program_id.like(f"{GONE}-%"))).all() == []
    assert db_session.get(Source, catalogue["own"]) is None
    assert db_session.get(Source, catalogue["orphan"]) is None
    assert db_session.scalars(
        select(SourceVersion).where(SourceVersion.source_id == catalogue["own"])).all() == []
    # A page another school's program still cites stays, and so does that program.
    assert db_session.get(Source, catalogue["shared"]) is not None
    assert db_session.get(Program, f"{OTHER}-x") is not None


def test_a_program_in_a_portfolio_stays_with_its_school_and_its_page(db_session, catalogue):
    client = _client(db_session)
    db_session.add(Application(id=str(uuid.uuid4()), client_id=client, program_id=f"{GONE}-a", tier="稳"))
    db_session.commit()

    report = remove_universities(db_session, [GONE])
    db_session.commit()

    assert report == [{
        "university": GONE, "programs_removed": 2, "sources_removed": 1,
        "kept_programs": [f"{GONE}-a"], "university_removed": False,
    }]
    assert db_session.get(Program, f"{GONE}-a") is not None
    assert db_session.get(University, GONE) is not None
    assert db_session.get(Source, catalogue["own"]) is not None  # the kept program still cites it
    assert db_session.scalar(select(Application.program_id).where(Application.client_id == client)) == f"{GONE}-a"


def test_a_program_a_document_names_stays_rather_than_being_unlinked(db_session, catalogue):
    client = _client(db_session)
    document_id = str(uuid.uuid4())
    db_session.add(Document(id=document_id, client_id=client, title="PS", program_id=f"{GONE}-b"))
    db_session.commit()

    report = remove_universities(db_session, [GONE])
    db_session.commit()

    assert report[0]["kept_programs"] == [f"{GONE}-b"]
    assert report[0]["university_removed"] is False
    db_session.expire_all()
    assert db_session.get(Document, document_id).program_id == f"{GONE}-b"


def test_running_it_again_changes_nothing(db_session, catalogue):
    remove_universities(db_session, [GONE])
    db_session.commit()

    assert remove_universities(db_session, [GONE]) == [{
        "university": GONE, "programs_removed": 0, "sources_removed": 0,
        "kept_programs": [], "university_removed": False,
    }]


def test_the_command_only_reports_unless_told_to_apply(db_session, catalogue, capsys):
    assert main([GONE]) == 0
    assert '"programs_removed": 3' in capsys.readouterr().out
    db_session.expire_all()
    assert db_session.get(University, GONE) is not None
    assert len(db_session.scalars(select(Program).where(Program.university_id == GONE)).all()) == 3

    assert main(["--apply", GONE]) == 0
    db_session.expire_all()
    assert db_session.get(University, GONE) is None


def test_a_program_a_roadmap_task_names_stays(db_session, catalogue):
    """`roadmap_tasks.program_id` has no foreign key, so a deleted program would leave the task dangling."""
    phase, material = f"test-phase-{uuid.uuid4().hex[:8]}", f"test-material-{uuid.uuid4().hex[:8]}"
    client = _client(db_session)
    db_session.add(RoadmapPhase(key=phase, title="测试阶段", offset_days=30, sort_order=0))
    db_session.flush()
    db_session.add(MaterialTemplate(key=material, phase=phase, title="测试材料", applies_to="all", sort_order=0))
    db_session.flush()
    task_id = str(uuid.uuid4())
    db_session.add(RoadmapTask(id=task_id, client_id=client, material_key=material, program_id=f"{GONE}-c", phase=phase))
    db_session.commit()
    try:
        report = remove_universities(db_session, [GONE])
        db_session.commit()
        assert report[0]["kept_programs"] == [f"{GONE}-c"]
        assert db_session.get(Program, f"{GONE}-c") is not None
    finally:
        db_session.rollback()
        db_session.execute(delete(RoadmapTask).where(RoadmapTask.id == task_id))
        db_session.execute(delete(MaterialTemplate).where(MaterialTemplate.key == material))
        db_session.execute(delete(RoadmapPhase).where(RoadmapPhase.key == phase))
        db_session.execute(delete(Client).where(Client.id == client))
        db_session.commit()
