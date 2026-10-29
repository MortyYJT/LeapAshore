"""The evidence gate against a real database: the questions TASKS.md P0 #4 lists, answered right.

The fixture adds a small catalogue under the real university ids the curated short forms point at
(created only when absent, so the development database's own rows stay), plus programs and sources
with test ids, and removes exactly what it added. Assertions are about properties (which school, which
area, how many rows were read), so they hold on the fixture alone (CI) and on the full local catalogue.
"""

import uuid

import pytest
from sqlalchemy import delete, event, func, select

from app.agent import evidence, graph
from app.agent.tools import search_programs
from app.db import SessionLocal, engine
from app.models.program import Program, ProgramPrerequisite, University
from app.models.source import Source

pytestmark = pytest.mark.usefixtures("require_db")

PREFIX = "test-retrieval-"
UNIVERSITIES = [
    ("imperial-college-london", "帝国理工学院", "Imperial College London", "英国"),
    ("university-of-hong-kong", "香港大學", "The University of Hong Kong", "中国香港"),
    ("chinese-university-of-hong-kong", "香港中文大學", "The Chinese University of Hong Kong", "中国香港"),
    (f"{PREFIX}empty", "测试零项目大学", "Retrieval Test Empty University", "英国"),
]
# (university, name, field, has requirement data)
PROGRAMS = [
    ("imperial-college-london", "MSc Computing", "计算机与数据", True),
    ("imperial-college-london", "MSc Artificial Intelligence", "计算机与数据", True),
    ("imperial-college-london", "MSc Molecular Medicine", "医学与健康", True),
    ("imperial-college-london", "MSc Applied Machine Learning", "计算机与数据", False),
    ("university-of-hong-kong", "Master of Science in Computer Science", "计算机与数据", True),
    ("university-of-hong-kong", "Master of Finance", "商科与金融", True),
    ("university-of-hong-kong", "Master of Data Science", "计算机与数据", False),
    ("university-of-hong-kong", "Master of Common Law", "法律与犯罪学", True),
    ("university-of-hong-kong", "Master of Laws in Human Rights", "法律与犯罪学", True),
    ("chinese-university-of-hong-kong", "MSc in Computer Science", "计算机与数据", True),
]


@pytest.fixture
def catalogue():
    created_universities, program_ids, source_ids = [], [], []
    with SessionLocal() as s:
        for uid, name, name_en, country in UNIVERSITIES:
            if s.get(University, uid) is None:
                s.add(University(id=uid, name=name, name_en=name_en, country=country))
                created_universities.append(uid)
        s.flush()
        for uid, name, area, has_data in PROGRAMS:
            sid, pid = str(uuid.uuid4()), f"{PREFIX}{uuid.uuid4().hex[:12]}"
            s.add(Source(id=sid, url=f"https://example.org/{PREFIX}{sid}", title=f"{name} (test)"))
            s.flush()
            s.add(Program(
                id=pid, university_id=uid, name=name, name_en=name, field=area, source_id=sid,
                data_status="机器核对", english_requirement="IELTS 7.0" if has_data else None,
            ))
            program_ids.append(pid)
            source_ids.append(sid)
        s.commit()
    evidence._counts_cache.clear()
    yield program_ids
    with SessionLocal() as s:
        s.execute(delete(ProgramPrerequisite).where(ProgramPrerequisite.program_id.in_(program_ids)))
        s.execute(delete(Program).where(Program.id.in_(program_ids)))
        s.execute(delete(Source).where(Source.id.in_(source_ids)))
        s.execute(delete(University).where(University.id.in_(created_universities)))
        s.commit()
    evidence._counts_cache.clear()


def gate(question: str) -> dict:
    with SessionLocal() as s:
        return evidence.gate(s, question)


def cited(update: dict) -> list[Program]:
    ids = [c["programId"] for c in update["citations"]]
    with SessionLocal() as s:
        rows = {p.id: p for p in s.scalars(select(Program).where(Program.id.in_(ids)))}
        for p in rows.values():
            s.expunge(p)
    return [rows[i] for i in ids]


def test_a_short_form_is_answered(catalogue):
    update = gate("帝国理工计算机硕士的语言要求是多少？")
    assert update["evidence_strong"] is True
    assert {p.university_id for p in cited(update)} == {"imperial-college-london"}


def test_simplified_chinese_finds_a_school_stored_in_traditional(catalogue):
    update = gate("香港大学计算机科学硕士申请要求")
    assert update["evidence_strong"] is True
    assert {p.university_id for p in cited(update)} == {"university-of-hong-kong"}


def test_a_subject_question_returns_only_that_subject(catalogue):
    """The original bug: "帝国理工学院计算机" returned AI and molecular medicine. Now every row is in the
    computing area, and rows whose name says computing come before the rest of it."""
    rows = cited(gate("帝国理工学院计算机"))
    assert rows
    assert all(p.field == "计算机与数据" for p in rows)
    assert "MSc Molecular Medicine" not in {p.name for p in rows}
    assert "comput" in rows[0].name_en.lower()


def test_a_row_without_requirement_data_is_never_evidence(catalogue):
    rows = cited(gate("帝国理工 机器学习"))
    assert all(p.english_requirement or p.minimum_mark is not None or p.non_211_minimum_mark is not None
               or p.id not in catalogue for p in rows)
    assert catalogue[3] not in {p.id for p in rows}


def test_a_comparison_gets_evidence_for_both_schools(catalogue):
    rows = cited(gate("港大和港中文的计算机硕士要求对比一下"))
    assert {p.university_id for p in rows} == {"university-of-hong-kong", "chinese-university-of-hong-kong"}


def test_the_gate_never_returns_more_than_k_rows(catalogue):
    update = gate("帝国理工的硕士要求")
    assert 0 < len(update["citations"]) <= evidence.TOP_K


def test_an_unknown_school_is_refused_with_counts_from_the_catalogue(catalogue):
    update = gate("清华大学计算机硕士要求")
    assert update["evidence_strong"] is False
    assert update["refusal"] == "no_school"
    with SessionLocal() as s:
        schools = s.scalar(
            select(func.count(func.distinct(Program.university_id)))
            .join(Source, Source.id == Program.source_id)
            .where(evidence.has_requirement_data(), evidence.citable_source())
        )
    assert f"收录了 {schools} 所学校" in update["refusal_text"]
    # The old text listed five Australian schools whatever the catalogue held.
    assert "新南威尔士大学、悉尼大学、蒙纳士大学" not in update["refusal_text"]


def test_a_school_without_the_subject_is_refused_by_name(catalogue):
    update = gate("帝国理工的法学硕士要求")
    assert update["refusal"] == "no_program_in_field"
    assert "帝国理工学院" in update["refusal_text"] and "法律与犯罪学" in update["refusal_text"]


def test_a_specific_subject_that_fits_only_uncollected_rows_is_refused(catalogue):
    """"港大 数据科学" where the only data-science row has no requirement data: the gate refuses rather
    than handing over the computer science row. The full local catalogue has HKU's real, collected
    Master of Data Science, so there the answer is that row; on the fixture alone (CI) it is the
    refusal."""
    update = gate("港大 数据科学")
    if update["evidence_strong"]:
        assert all("data" in p.name_en.lower() or "analytics" in p.name_en.lower() for p in cited(update))
        assert all(p.id not in catalogue for p in cited(update))
    else:
        assert update["refusal"] == "no_program_in_field"
        assert "还没有采到它们的官方录取要求" in update["refusal_text"]


def test_a_school_with_no_collected_programs_is_refused_as_not_collected(catalogue):
    update = gate("测试零项目大学的硕士要求")
    assert update["refusal"] == "school_not_collected"
    assert "测试零项目大学" in update["refusal_text"]


def test_a_named_school_without_evidence_is_flagged_in_a_comparison(catalogue):
    update = gate("港大和测试零项目大学的计算机")
    assert update["evidence_strong"] is True
    assert "测试零项目大学" in update["evidence"].splitlines()[-1]


def test_the_refusal_node_shows_the_gates_text():
    message = graph.refuse({"refusal": "no_school", "refusal_text": "按数据生成的拒答"})["messages"][0]
    assert message.content == "按数据生成的拒答"
    assert graph.refuse({})["messages"][0].content == graph.FALLBACK_REFUSAL


def test_the_gate_reads_a_bounded_number_of_rows_not_the_catalogue(catalogue):
    """Filtering runs in SQL: one question reads the universities table and a few program rows."""
    returned = []

    def count(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        if statement.lstrip().upper().startswith("SELECT") and cursor.rowcount > 0:
            returned.append(cursor.rowcount)

    with SessionLocal() as s:
        universities = s.scalar(select(func.count()).select_from(University))
        programs = s.scalar(select(func.count()).select_from(Program))
    event.listen(engine, "after_cursor_execute", count)
    try:
        gate("帝国理工学院计算机")
    finally:
        event.remove(engine, "after_cursor_execute", count)
    # universities + K candidates per school + K programs + their sources and prerequisites, plus each
    # program's deadlines (at most 8 per program in the collected data, 2026-10-30)
    assert sum(returned) <= universities + 4 * evidence.TOP_K + 8 * evidence.TOP_K
    assert max(returned) < programs or programs <= universities


def test_the_portfolio_search_tool_understands_short_forms(catalogue):
    result = search_programs.invoke({"keyword": "港大 计算机"})
    assert "Master of Science in Computer Science" in result
    assert "Master of Finance" not in result


def test_the_portfolio_search_tool_keeps_the_other_words(catalogue):
    """Review of PR #38: once a school was recognised the program's own name was ignored, so
    "<school> Juris Doctor" listed the school's first ten programs instead."""
    # "law" picks the area; "common" must then pick one of its two rows.
    result = search_programs.invoke({"keyword": "港大 Common Law"})
    assert "Master of Common Law" in result
    assert "Human Rights" not in result
    # Words that match no name ("硕士") are filler and do not empty the result.
    assert "Master of Science in Computer Science" in search_programs.invoke({"keyword": "港大 计算机 硕士"})


def test_an_evidence_line_carries_the_academic_requirement_and_the_deadlines():
    """The gate admits a row that states only these, so the model must see them; a past one says so."""
    from datetime import date
    from types import SimpleNamespace

    from app.agent.evidence import Hit, evidence_line

    program = SimpleNamespace(
        university=SimpleNamespace(name="测试大学"), name="数据科学硕士", name_en="MSc Data Science",
        minimum_mark=None, non_211_minimum_mark=None, english_requirement=None, prerequisites=[],
        academic_requirement="A 2:1 honours degree",
        deadlines=[
            SimpleNamespace(label="Round 1", deadline=date(2026, 10, 1), sort_order=0),
            SimpleNamespace(label="Round 2", deadline=date(2026, 10, 30), sort_order=1),
            SimpleNamespace(label=None, deadline=date(2027, 1, 31), sort_order=2),
        ],
    )
    source = SimpleNamespace(title="MSc Data Science", url="https://example.edu/msc", verified_at=None)
    line = evidence_line(1, Hit(program, source), today=date(2026, 10, 30))
    assert "｜学术要求：A 2:1 honours degree" in line
    assert "｜申请截止：Round 1 2026-10-01（已截止）；Round 2 2026-10-30；2027-01-31" in line

    bare = SimpleNamespace(**{**vars(program), "academic_requirement": None, "deadlines": []})
    line = evidence_line(1, Hit(bare, source), today=date(2026, 10, 30))
    assert "｜学术要求：未知" in line and "｜申请截止：未知" in line
