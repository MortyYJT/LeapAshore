"""The advisor's tools.

Write rules follow the product's two risk levels:

- automatic: updating a profile field is idempotent and the applicant can undo it, so it runs at once;
- confirmed: a portfolio change can overwrite choices the applicant made, so the tool stops the graph
  with ``interrupt`` and writes only after the applicant says yes.

Every tool takes the applicant's id from the run config, never from the model, so a prompt cannot
make the agent read or write someone else's rows.
"""

import json
from decimal import Decimal

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.types import interrupt
from pydantic import ValidationError
from sqlalchemy import case, or_, select
from sqlalchemy.orm import selectinload

from app.agent import catalog_match
from app.db import SessionLocal
from app.deps import load_or_create_profile
from app.models.application import Application, ApplicationStatus, ApplicationTier
from app.models.program import Program, University
from app.schemas.profile import ProfilePatch
from app.services.applications import InvalidApplicationPayload, replace_applications


def _client_id(config: RunnableConfig) -> str:
    return config["configurable"]["client_id"]


def _json(value) -> str:
    def default(o):
        return float(o) if isinstance(o, Decimal) else str(o)

    return json.dumps(value, ensure_ascii=False, default=default)


@tool
def search_programs(keyword: str) -> str:
    """按学校名或项目名搜索已收录的硕士项目，返回项目 id、学校、项目名和数据状态。关键词可以是中文或英文，
    学校可以用简称（港大、帝国理工、UCL），多个词用空格分开，例如"悉尼大学 计算机"。"""
    with SessionLocal() as s:
        rows = _search_by_school(s, keyword)
        if rows is None:
            rows = _search_by_words(s, keyword)
        if not rows:
            return "没有找到。该学校或项目暂未收录，录取要求待采集。"
        return _json(
            [
                {"id": p.id, "school": p.university.name, "program": p.name, "status": p.data_status}
                for p in rows
            ]
        )


SEARCH_LIMIT = 10


def _search_by_school(session, keyword: str) -> list[Program] | None:
    """When the keyword names a school (any spelling the advisor knows), that school's programs in the
    named subject area, best name fit first. None when no school is named."""
    index = catalog_match.school_index(
        [tuple(r) for r in session.execute(select(University.id, University.name, University.name_en))]
    )
    parsed = catalog_match.parse(index, keyword)
    if not parsed.schools:
        return None
    query = (
        select(Program)
        .options(selectinload(Program.university))
        .where(Program.university_id.in_(parsed.schools))
    )
    if parsed.fields:
        query = query.where(Program.field.in_(parsed.fields))
    if parsed.name_pattern:
        # CASE rather than the bare match: a row with no English name would sort first under DESC.
        query = query.order_by(case((Program.name_en.regexp_match(parsed.name_pattern, "i"), 1), else_=0).desc())
    return list(session.scalars(query.order_by(Program.name, Program.id).limit(SEARCH_LIMIT)))


def _search_by_words(session, keyword: str) -> list[Program]:
    # Each word must match some column, so "Sydney Computer" finds the program whose school matches
    # the first word and whose name matches the second.
    words = keyword.split() or [""]
    conditions = [
        or_(
            Program.name.ilike(f"%{w}%"),
            Program.name_en.ilike(f"%{w}%"),
            Program.field.ilike(f"%{w}%"),
            University.name.ilike(f"%{w}%"),
            University.name_en.ilike(f"%{w}%"),
        )
        for w in words
    ]
    return list(session.scalars(
        select(Program)
        .join(University)
        .options(selectinload(Program.university))
        .where(*conditions)
        .order_by(Program.name, Program.id)
        .limit(SEARCH_LIMIT)
    ))


@tool
def get_my_profile(config: RunnableConfig) -> str:
    """读取当前申请人的背景档案（学校、均分、专业、语言成绩、目标、预算等）。未填写的字段为 null。"""
    with SessionLocal() as s:
        profile = load_or_create_profile(s, _client_id(config))
        fields = ProfilePatch.model_fields.keys()
        return _json({f: getattr(profile, f, None) for f in fields})


@tool
def update_my_profile(fields_json: str, config: RunnableConfig) -> str:
    """更新申请人档案（低风险，直接执行）。参数是 JSON 对象，只放用户明确说出的字段，例如
    {"school_name": "武汉大学", "gpa_score": 85, "gpa_scale": 100, "major": "计算机科学", "english_score": "IELTS 7.0"}。
    可用字段：current_education_level, school_name, domestic_tier, major, gpa_score, gpa_scale,
    target_degree_level, target_field, intake, english_score, annual_budget_cny。"""
    try:
        patch = ProfilePatch.model_validate(json.loads(fields_json))
    except (json.JSONDecodeError, ValidationError) as exc:
        return f"未更新：字段不合法（{exc.__class__.__name__}）。请只使用列出的字段名。"
    changes = patch.model_dump(exclude_unset=True)
    if not changes:
        return "未更新：没有可写入的字段。"
    with SessionLocal() as s:
        profile = load_or_create_profile(s, _client_id(config))
        for name, value in changes.items():
            setattr(profile, name, value)
        s.commit()
    return f"已更新档案：{_json(changes)}"


def _portfolio(session, client_id: str) -> list[Application]:
    return list(session.scalars(select(Application).where(Application.client_id == client_id)))


@tool
def get_my_portfolio(config: RunnableConfig) -> str:
    """读取当前申请人的选校组合：每个项目的档位（冲/稳/保）、申请状态和是否首选。"""
    with SessionLocal() as s:
        rows = _portfolio(s, _client_id(config))
        if not rows:
            return "选校组合为空。"
        return _json(
            [
                {"programId": r.program_id, "tier": r.tier, "status": r.status, "isPrimary": r.is_primary}
                for r in rows
            ]
        )


# The applicant's words for each stored status, so a confirm question never shows a raw value.
STATUS_LABELS = {
    ApplicationStatus.CONSIDERING: "考虑中",
    ApplicationStatus.APPLYING: "申请中",
    ApplicationStatus.SUBMITTED: "已提交",
    ApplicationStatus.OFFERED: "已获 offer",
    ApplicationStatus.REJECTED: "被拒",
    ApplicationStatus.EXCLUDED: "不考虑",
}


@tool
def propose_portfolio_change(
    program_id: str, action: str, config: RunnableConfig, tier: str = "稳", status: str = ""
) -> str:
    """修改选校组合（高风险，必须经用户确认后才执行）。action 取值：add（加入，需给 tier：冲/稳/保）、
    remove（移出）、set_primary（设为首选）、set_status（改申请状态，需给 status：considering 考虑中 /
    applying 申请中 / submitted 已提交 / offered 已获 offer / rejected 被拒 / excluded 不考虑）。
    program_id 先用 search_programs 查到。"""
    if action not in ("add", "remove", "set_primary", "set_status"):
        return "未执行：action 只能是 add、remove、set_primary 或 set_status。"
    if action == "add" and tier not in {t.value for t in ApplicationTier}:
        return "未执行：tier 只能是 冲、稳 或 保。"
    if action == "set_status" and status not in {s.value for s in ApplicationStatus}:
        return "未执行：status 只能是 " + "、".join(s.value for s in ApplicationStatus) + "。"
    client_id = _client_id(config)
    with SessionLocal() as s:
        program = s.get(Program, program_id)
        if program is None:
            return f"未执行：没有 id 为 {program_id} 的项目。"
        current = {
            r.program_id: {
                "program_id": r.program_id,
                "tier": r.tier,
                "status": r.status,
                "is_primary": r.is_primary,
            }
            for r in _portfolio(s, client_id)
        }
        label = f"{program.university.name} {program.name}"

    rows = {k: dict(v) for k, v in current.items()}
    if action == "add":
        rows[program_id] = {
            "program_id": program_id,
            "tier": tier,
            "status": ApplicationStatus.CONSIDERING.value,
            "is_primary": rows.get(program_id, {}).get("is_primary", False),
        }
        summary = f"把「{label}」加入选校组合，档位：{tier}"
    elif action == "remove":
        if program_id not in rows:
            return f"未执行：「{label}」不在选校组合里。"
        rows.pop(program_id)
        summary = f"把「{label}」移出选校组合"
    elif action == "set_status":
        if program_id not in rows:
            return f"未执行：「{label}」不在选校组合里，先加入再改状态。"
        rows[program_id]["status"] = status
        summary = f"把「{label}」的申请状态改为：{STATUS_LABELS[ApplicationStatus(status)]}"
    else:
        if program_id not in rows:
            return f"未执行：「{label}」不在选校组合里，先加入再设为首选。"
        for r in rows.values():
            r["is_primary"] = r["program_id"] == program_id
        summary = f"把「{label}」设为首选"

    # The graph stops here. Resuming re-runs this tool from the top, which is safe because nothing
    # above has written anything.
    approved = interrupt({"type": "confirm_portfolio", "summary": summary})
    if not approved:
        return f"用户取消了操作：{summary}。组合未改动。"
    with SessionLocal() as s:
        # A visitor who opened the advisor first has a cookie but no subject row yet, and the
        # portfolio's foreign key would refuse the write.
        load_or_create_profile(s, client_id)
        try:
            counts = replace_applications(s, client_id, list(rows.values()))
        except InvalidApplicationPayload as exc:
            return f"未执行：{exc}"
    return f"已执行：{summary}。变化：{_json(counts)}"


TOOLS = [search_programs, get_my_profile, update_my_profile, get_my_portfolio, propose_portfolio_change]
