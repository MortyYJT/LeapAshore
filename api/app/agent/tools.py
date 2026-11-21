"""The advisor's tools.

Write rules follow the product's two risk levels:

- automatic: updating a profile field is idempotent and the applicant can undo it, so it runs at once;
- confirmed: a change to the portfolio or to an application can overwrite choices the applicant made,
  so the tool stops the graph with ``interrupt`` and writes only after the applicant says yes. The
  portfolio's tool is here; the tools for one application are in ``app.agent.application_tools``.

Every tool takes the applicant's id from the run config, never from the model, so a prompt cannot
make the agent read or write someone else's rows.
"""

import json

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.types import interrupt
from pydantic import ValidationError
from sqlalchemy import case, or_, select
from sqlalchemy.orm import selectinload

from app.agent import catalog_match
from app.agent.application_tools import APPLICATION_TOOLS, applications_json
from app.agent.confirm import CHANGED, DECLINED, REFUSED, SAME, STATUS_LABELS, answer_of
from app.agent.confirm import change as _change
from app.agent.confirm import client_id as _client_id
from app.agent.confirm import status_label as _status_label
from app.agent.confirm import to_json as _json
from app.db import SessionLocal
from app.deps import load_or_create_profile
from app.models.application import Application, ApplicationStatus, ApplicationTier
from app.models.program import Program, University
from app.schemas.profile import ProfilePatch
from app.services.applications import InvalidApplicationPayload, replace_applications_based_on
from app.services.versions import StaleVersion


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
    named subject area, best name fit first. The keyword's other words ("Juris Doctor") must each
    appear in the program's name; when that leaves nothing, they were filler ("硕士") and are dropped.
    None when no school is named."""
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
    query = query.order_by(Program.name, Program.id).limit(SEARCH_LIMIT)
    words = parsed.rest.split()
    if words:
        named = query.where(*[or_(Program.name.ilike(f"%{w}%"), Program.name_en.ilike(f"%{w}%")) for w in words])
        rows = list(session.scalars(named))
        if rows:
            return rows
    return list(session.scalars(query))


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


# How a tool's answer starts when it wrote something (the profile, the portfolio, an application). The
# advisor tells the applicant those writes stand when the turn then fails (`routers.advisor`); read-only
# tools, a declined change and a refused one start otherwise.
PROFILE_UPDATED = "已更新档案："
PORTFOLIO_CHANGED = CHANGED


def wrote(message) -> bool:
    """Whether this tool reply is the answer of a tool that wrote something."""
    content = getattr(message, "content", None)
    return isinstance(content, str) and content.startswith((PROFILE_UPDATED, CHANGED))


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
    return f"{PROFILE_UPDATED}{_json(changes)}"


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


@tool
def get_my_applications(config: RunnableConfig) -> str:
    """读取当前申请者的全部申请（学校库项目和手动添加的项目）。每条有：id（修改这条申请时要用）、学校、项目、轮次、
    截止日期、日期来历（deadlineOrigin：collected 学校库采集 / entered 申请者自己填的）、申请者是否对照官网核对过
    （deadlineCheckedByApplicant）、来源链接、申请状态、材料和材料备注。学校库项目还带 catalogDeadlines：学校库
    采集到的各轮截止日期和它们的 id。
    材料：materials 是学校库从这个项目的官网页面采集到的材料要求，每项有 key（勾选时用）、name、份数 count、
    说明 note、官网原文 quote、出处 sourceUrl、申请者是否勾了备好 ready；说材料要求时只能说这里列出的，并给出处。
    materialsExtracted 为 false 表示学校库还没整理这个项目的材料清单（不是不需要材料），照实说，不要凭印象列。
    清单可能不全，提醒申请者以官网为准。customMaterials 是申请者自己列的清单。
    规划申请、梳理材料或修改任何一条申请之前先读取。采集的内容和申请者的自查都不等于学校官方已核验。此工具只读。"""
    return applications_json(config)


@tool
def propose_portfolio_change(
    program_id: str, action: str, config: RunnableConfig, tier: str = "稳", status: str = ""
) -> str:
    """修改选校组合（调用后界面出现确认卡片，申请者点确认才写入；信息齐全就直接调用，不要先用文字问是否确认）。action 取值：add（把学校库里的项目加入组合，也就是加入「我的申请」，
    需给 tier：冲/稳/保）、remove（移出）、set_primary（设为首选）。program_id 先用 search_programs 查到。
    改申请状态不用这个工具，用 propose_application_status；学校库没有收录的项目用 propose_manual_application。"""
    # `set_status` is still accepted, for a turn that was paused on one before the status moved to
    # `propose_application_status`; the description no longer offers it.
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
        stored = _portfolio(s, client_id)
        # The rows this run reads are the rows its replacement is built from, and it says so when it
        # writes: a row another device saves in between is then a refusal, not something replaced.
        base = {(r.id, r.version) for r in stored}
        current = {
            r.program_id: {
                "program_id": r.program_id,
                "tier": r.tier,
                "status": r.status,
                "is_primary": r.is_primary,
            }
            for r in stored
        }
        label = f"{program.university.name} {program.name}"
        target = {"programId": program_id, "school": program.university.name, "program": program.name}
        primary = next((r["program_id"] for r in current.values() if r["is_primary"]), None)
        primary_now = None
        if action == "set_primary" and primary and primary != program_id:
            held = s.get(Program, primary)
            primary_now = f"{held.university.name} {held.name}" if held else primary

    rows = {k: dict(v) for k, v in current.items()}
    before = current.get(program_id)
    # What the applicant is shown before anything is written: every stored value this change replaces,
    # beside the value it becomes. `before` is None for a value that does not exist yet.
    changes: list[dict] = []
    if action == "add":
        if before is None:
            changes.append(_change("选校组合", "不在组合里", "加入"))
        if before is None or before["tier"] != tier:
            changes.append(_change("档位", before and before["tier"], tier))
        if before is None or before["status"] != ApplicationStatus.CONSIDERING.value:
            # Adding a program again puts its status back to 考虑中; say so rather than let it pass unseen.
            changes.append(_change("申请状态", before and _status_label(before["status"]), STATUS_LABELS[ApplicationStatus.CONSIDERING]))
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
        kept = f"在组合里（{before['tier']}，{_status_label(before['status'])}）"
        changes.append(_change("选校组合", kept, "移出"))
        if before["is_primary"]:
            changes.append(_change("首选", "这个项目", "空缺"))
        summary = f"把「{label}」移出选校组合"
    elif action == "set_status":
        if program_id not in rows:
            return f"未执行：「{label}」不在选校组合里，先加入再改状态。"
        if before["status"] == status:
            return f"{SAME}「{label}」的申请状态已经是{STATUS_LABELS[ApplicationStatus(status)]}。"
        rows[program_id]["status"] = status
        changes.append(_change("申请状态", _status_label(before["status"]), STATUS_LABELS[ApplicationStatus(status)]))
        summary = f"把「{label}」的申请状态改为：{STATUS_LABELS[ApplicationStatus(status)]}"
    else:
        if program_id not in rows:
            return f"未执行：「{label}」不在选校组合里，先加入再设为首选。"
        if primary == program_id:
            return f"{SAME}「{label}」已经是首选。"
        for r in rows.values():
            r["is_primary"] = r["program_id"] == program_id
        changes.append(_change("首选", primary_now or "还没有设", label))
        summary = f"把「{label}」设为首选"

    # The graph stops here. Resuming re-runs this tool from the top, which is safe because nothing
    # above has written anything.
    if not changes:
        return f"{SAME}「{label}」已经在选校组合里，档位和状态都没有变化。"
    # `tool` names this tool, so the stream can tie the question to the step that asked it.
    answer = interrupt({
        "type": "confirm_portfolio", "tool": "propose_portfolio_change", "summary": summary,
        "target": target, "changes": changes,
    })
    approved, shown, _base = answer_of(answer)
    if not approved:
        return f"{DECLINED}{summary}。组合未改动。"
    if shown is not None and shown != changes:
        # The portfolio was edited between the question and the answer: what would be written now is
        # not what the applicant agreed to.
        return f"{REFUSED}「{label}」在确认之前已经被改过，和刚才列出的改动对不上。请重新提出这次修改。"
    with SessionLocal() as s:
        # A visitor who opened the advisor first has a cookie but no subject row yet, and the
        # portfolio's foreign key would refuse the write.
        load_or_create_profile(s, client_id)
        try:
            counts = replace_applications_based_on(s, client_id, list(rows.values()), base)
        except StaleVersion:
            return f"{REFUSED}别处改过了选校组合，这次没有写入，也没有覆盖别处的改动。请读取现在的组合后重新提出。"
        except InvalidApplicationPayload as exc:
            return f"{REFUSED}{exc}"
    return f"{PORTFOLIO_CHANGED}{summary}。变化：{_json(counts)}"


TOOLS = [
    search_programs, get_my_profile, update_my_profile, get_my_portfolio, get_my_applications,
    propose_portfolio_change, *APPLICATION_TOOLS,
]
