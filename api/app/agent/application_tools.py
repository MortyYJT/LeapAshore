"""The advisor's tools for the applicant's own applications (`docs/product/PRD-multi-device.md`, 3.6).

One read, and four changes that are each proposed first and written only after the applicant confirms:
adding an application by hand, setting a round or a deadline, changing the status, and the material
self-check. There is one tool per kind of change, because each kind has its own few arguments and its
own rule, and a call that can only carry a status cannot also carry a date.

What a change may write:

- A deadline or a round is never the model's. It is either the catalogue's, named by the id of a
  collected deadline of that exact program and read here from the catalogue with its source, or one
  the applicant wrote in the conversation, which `app.agent.stated` looks for in their own messages.
  Either way the date is stored unchecked: only the applicant marks a date as checked, in 「我的申请」.
- A material note is the applicant's own words, for the same reason: a note is where an invented
  requirement would otherwise be kept as if the applicant had written it.

How a change is written:

- Through `app.services.application_records`, the code the HTTP routes use, so the rules are the same.
- Based on the version the confirm card was drawn from. If the record has moved since (another device,
  another conversation), nothing is written and the reply says what moved.
- Once. An update whose base version has gone is refused, so a confirmed change run a second time
  writes nothing; an added application carries a key made from the conversation and the call, and a
  second run with that key finds the first run's record.

Every tool takes the applicant from the run's config, never from the model: an application id that is
somebody else's is "no such application".
"""

import hashlib
from datetime import date
from typing import Annotated
from urllib.parse import urlsplit

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import interrupt
from pydantic import ValidationError
from sqlalchemy import select

from app.agent import stated
from app.agent.confirm import (
    ALREADY,
    CHANGED,
    DECLINED,
    REFUSED,
    SAME,
    STATUS_LABELS,
    answer_of,
    change,
    client_id,
    status_label,
    to_json,
)
from app.db import SessionLocal
from app.models.application import ApplicationStatus
from app.models.program import ProgramDeadline
from app.services import application_records as records
from app.services.application_records import COLLECTED, ENTERED, RecordCreate, RecordPatch
from app.services.versions import StaleVersion

CONFIRM_TYPE = "confirm_application"
NO_SUCH_APPLICATION = f"{REFUSED}没有这个申请。\napplication_id 要用 get_my_applications 返回的 id。"

READY, NOT_READY = "已就绪（自查）", "准备中"
UNCHECKED = "待核对"
ORIGIN_LABELS = {COLLECTED: "学校库采集", ENTERED: "你自己填的"}
# The one material tick an application has today: all of its materials at once. A tick per material
# (PRD 3.7) adds keys beside this one; the tool, its card and its wording already speak of ticks.
ALL_MATERIALS = "all"
NOTE_LIMIT = 500


# ---------------------------------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------------------------------


def read_for_advisor(client: str) -> list[dict]:
    """The applicant's applications as the model reads them: every field a change can touch, in the
    applicant's words where there are any, and for a catalogue program the deadlines the catalogue
    collected, each with the id a proposed deadline names."""
    with SessionLocal() as session:
        rows = records.read_records(client, session)
        programs = [row["programId"] for row in rows if row["programId"]]
        collected: dict[str, list[ProgramDeadline]] = {}
        if programs:
            query = (
                select(ProgramDeadline)
                .where(ProgramDeadline.program_id.in_(programs))
                .order_by(ProgramDeadline.sort_order, ProgramDeadline.deadline, ProgramDeadline.id)
            )
            for row in session.scalars(query):
                collected.setdefault(row.program_id, []).append(row)
        today = stated.today()
        out = []
        for row in rows:
            item = {
                "id": row["id"],
                "kind": "catalog" if row["programId"] else "manual",
                "programId": row["programId"],
                "school": row["school"],
                "name": row["name"],
                "round": row["round"],
                "status": row["status"],
                "statusLabel": status_label(row["status"]),
                "deadline": row["deadline"],
                "deadlineOrigin": row["deadlineOrigin"],
                "deadlineCheckedByApplicant": row["checkedAt"] is not None,
                "sourceUrl": row["sourceUrl"],
                "materialsReady": row["materialsReady"],
                "materialNotes": row["materialNotes"],
            }
            if row["programId"]:
                item["catalogDeadlines"] = [
                    {"id": d.id, "round": d.label, "date": d.deadline, "sourceUrl": d.source_url,
                     "passed": d.deadline < today}
                    for d in collected.get(row["programId"], [])
                ]
            out.append(item)
        return out


# ---------------------------------------------------------------------------------------------------
# What a card and a reply say about a record
# ---------------------------------------------------------------------------------------------------


def _name(record: dict) -> str:
    return f"{record['school']} {record['name']}"


def _target(record: dict) -> dict:
    return {"applicationId": record["id"], "programId": record["programId"], "school": record["school"],
            "program": record["name"]}


def _iso(value) -> str | None:
    return value.isoformat() if isinstance(value, date) else value


def _ready(value: bool) -> str:
    return READY if value else NOT_READY


def _seen(record: dict) -> dict:
    """The record as the card was drawn from it, kept with the question so a stale answer can say what
    moved. The note is kept as a digest: whether it moved is enough."""
    return {
        "school": record["school"],
        "name": record["name"],
        "round": record["round"],
        "deadline": _iso(record["deadline"]),
        "sourceUrl": record["sourceUrl"],
        "status": record["status"],
        "materialsReady": record["materialsReady"],
        "notes": hashlib.sha256((record["materialNotes"] or "").encode()).hexdigest()[:12],
        "checked": record["checkedAt"] is not None,
    }


def _moved(seen: dict | None, current: dict) -> list[str]:
    """What differs between the record the card showed and the record as it is stored now."""
    if not seen:
        return []
    now = _seen(current)
    lines = []

    def line(key: str, label: str, words=lambda value: value or "未填") -> None:
        if seen.get(key) != now[key]:
            lines.append(f"{label}：{words(seen.get(key))} → {words(now[key])}")

    line("school", "学校")
    line("name", "项目")
    line("round", "轮次")
    line("deadline", "截止日期")
    line("sourceUrl", "来源链接", lambda value: value or "没有")
    line("status", "申请状态", status_label)
    line("materialsReady", "材料", _ready)
    line("checked", "核对状态", lambda value: "你核对过" if value else UNCHECKED)
    if seen.get("notes") != now["notes"]:
        lines.append("材料备注：改过")
    return lines


def _stale(record_name: str, seen: dict | None, current: dict) -> str:
    """The reply to a confirm that arrived after the record had moved. What moved comes first, so the
    step's one line still carries it when it is cut short."""
    moved = "；".join(_moved(seen, current)) or "这条申请在选校组合里的那一行有改动"
    return (
        f"{REFUSED}别处改过了（{moved}），这次没有写入，也没有覆盖别处的改动。\n"
        f"「{record_name}」的卡片是按改动之前的内容列的。读取现在的内容后重新提出。"
    )


def _host(url: str | None) -> str:
    return urlsplit(url or "").hostname or "来源页面"


# ---------------------------------------------------------------------------------------------------
# The shared path of a proposed update
# ---------------------------------------------------------------------------------------------------


def _propose_update(tool_name: str, config: RunnableConfig, application_id: str, build) -> str:
    """Ask the applicant about one change to one record, and write it when they say yes.

    `build(record, session)` returns a refusal, or `(summary, changes, fields)`: the sentence, the
    lines of the card and the fields to write. Nothing is written before the answer, so the graph can
    run this again from the top when the applicant answers.
    """
    client = client_id(config)
    with SessionLocal() as session:
        try:
            record = records.read_record(session, client, str(application_id or ""))
        except records.RecordNotFound:
            return NO_SUCH_APPLICATION
        built = build(record, session)
    if isinstance(built, str):
        return built
    summary, changes, fields = built
    answer = interrupt({
        "type": CONFIRM_TYPE, "tool": tool_name, "summary": summary, "target": _target(record), "changes": changes,
        # The version the card is drawn from, and the values it showed. The answer brings them back.
        "base": {"version": record["version"], "seen": _seen(record)},
    })
    approved, shown, base = answer_of(answer)
    if not approved:
        return f"{DECLINED}{summary}。没有改动。"
    seen = (base or {}).get("seen")
    based_on = (base or {}).get("version") or record["version"]
    if based_on != record["version"]:
        # The record moved between the card and the answer: the applicant agreed to a change to a
        # record that is no longer the stored one.
        return _stale(_name(record), seen, record)
    if shown is not None and shown != changes:
        # The record is the same, so what moved is the catalogue the change reads from.
        return f"{REFUSED}学校库里的这条日期在确认之前变了，和卡片上列的对不上，这次没有写入。\n读取现在的内容后重新提出。"
    try:
        payload = RecordPatch(**fields, base_version=based_on)
        with SessionLocal() as session:
            records.update_record(session, client, record["id"], payload)
    except ValidationError as exc:
        return f"{REFUSED}内容不合法（{exc.errors()[0].get('msg', exc.__class__.__name__)}）。"
    except records.RecordNotFound:
        return NO_SUCH_APPLICATION
    except StaleVersion as exc:
        return _stale(_name(record), seen or _seen(record), exc.current)
    except records.InvalidRecord as exc:
        return f"{REFUSED}{exc}"
    return f"{CHANGED}{summary}。"


# ---------------------------------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------------------------------


@tool
def propose_application_status(application_id: str, status: str, config: RunnableConfig) -> str:
    """提议修改一条申请的状态（必须经申请者确认后才写入）。application_id 取自 get_my_applications。
    status 取值：considering 考虑中 / applying 准备中 / submitted 已提交 / offered 收到录取 / rejected 未录取 /
    excluded 已放弃。"""
    try:
        wanted = ApplicationStatus(status)
    except ValueError:
        return f"{REFUSED}没有这种申请状态。\nstatus 只能是 " + "、".join(s.value for s in ApplicationStatus) + "。"

    def build(record: dict, session):
        label = STATUS_LABELS[wanted]
        if record["status"] == wanted.value:
            return f"{SAME}「{_name(record)}」的申请状态已经是{label}，没有要写入的改动。"
        summary = f"把「{_name(record)}」的申请状态改为{label}"
        return summary, [change("申请状态", status_label(record["status"]), label)], {"status": wanted}

    return _propose_update("propose_application_status", config, application_id, build)


# ---------------------------------------------------------------------------------------------------
# Round and deadline
# ---------------------------------------------------------------------------------------------------


def _schedule_changes(record: dict, fields: dict, origin: str, origin_after: str) -> list[dict]:
    """The card's lines for a round, a date and its source, against what the record holds. `origin` is
    where the new date comes from, and `origin_after` the words for it."""
    changes = []
    if "round" in fields and fields["round"] != record["round"]:
        changes.append(change("轮次", record["round"], fields["round"] or "不填"))
    date_moves = "deadline" in fields and fields["deadline"] != record["deadline"]
    source_moves = "source_url" in fields and fields["source_url"] != record["sourceUrl"]
    if date_moves:
        changes.append(change("截止日期", _iso(record["deadline"]), _iso(fields["deadline"])))
    if date_moves or source_moves:
        # Where the date comes from, so the applicant can tell a collected date from their own. The
        # old origin is shown only when it is the other kind: collected to collected is not a change.
        held = record["deadlineOrigin"] if record["deadline"] else None
        changes.append(change("日期来源", ORIGIN_LABELS.get(held) if held != origin else None, origin_after))
        if source_moves and fields["source_url"] is None:
            changes.append(change("来源链接", record["sourceUrl"], "不保留"))
    if changes and record["checkedAt"] is not None:
        # Any of the three resets the applicant's own check (`application_records.apply_patch`).
        changes.append(change("核对状态", "你核对过", UNCHECKED))
    return changes


@tool
def propose_application_deadline(
    application_id: str,
    config: RunnableConfig,
    state: Annotated[dict, InjectedState],
    catalog_deadline_id: str = "",
    stated_deadline: str = "",
    stated_round: str = "",
) -> str:
    """提议设置或修改一条申请的轮次、截止日期（必须经申请者确认后才写入）。application_id 取自 get_my_applications。
    日期只有两种来历，二选一：
    1. 学校库采集的：传 catalog_deadline_id，即这条申请 catalogDeadlines 里某一项的 id。日期、轮次名和来源链接
       由系统从学校库取，你不要自己写日期。
    2. 申请者在对话里亲口说的：传 stated_deadline（YYYY-MM-DD，必须是申请者写出的那一天）和/或 stated_round
       （照抄申请者说的轮次原话）。
    两种来历都没有时不要调用，更不要猜：告诉申请者学校库没有采集到这个日期，请他在官网查到后告诉你。
    写入后的日期一律是「待核对」；是否核对过只能由申请者自己在「我的申请」里确认。"""
    catalog_deadline_id, stated_deadline, stated_round = (
        str(value or "").strip() for value in (catalog_deadline_id, stated_deadline, stated_round)
    )
    texts = stated.applicant_texts(state)

    def build(record: dict, session):
        name = _name(record)
        if catalog_deadline_id and (stated_deadline or stated_round):
            return f"{REFUSED}一次只能用一种来历的日期。\ncatalog_deadline_id 和 stated_deadline、stated_round 不能同时传。"
        if catalog_deadline_id:
            if not record["programId"]:
                return f"{REFUSED}「{name}」是手动添加的申请，学校库里没有它的日期。\n请申请者在官网查到后在对话里写出来。"
            row = session.get(ProgramDeadline, catalog_deadline_id)
            if row is None or row.program_id != record["programId"]:
                return (f"{REFUSED}学校库里没有「{name}」的这条截止日期。\ncatalog_deadline_id 只能用 "
                        "get_my_applications 里这条申请的 catalogDeadlines 列出的 id。")
            fields = {"round": row.label, "deadline": row.deadline, "source_url": row.source_url}
            if all(fields[key] == record[shown] for key, shown in (("round", "round"), ("deadline", "deadline"), ("source_url", "sourceUrl"))):
                return f"{SAME}「{name}」的轮次和截止日期已经是学校库的这一条，没有要写入的改动。"
            origin = f"学校库采集（{_host(row.source_url)}），{UNCHECKED}"
            summary = f"把「{name}」的截止日期设为学校库采集的 {row.deadline.isoformat()}" + (f"（{row.label}）" if row.label else "")
            return summary, _schedule_changes(record, fields, COLLECTED, origin), fields

        fields = {}
        parts = []
        if stated_deadline:
            try:
                wanted = date.fromisoformat(stated_deadline)
            except ValueError:
                return f"{REFUSED}这不是一个日期。\nstated_deadline 要写成 YYYY-MM-DD，而且必须是申请者在对话里写出的那一天。"
            if wanted not in stated.dates_in(texts):
                return (f"{REFUSED}对话里没有写出 {wanted.isoformat()} 这个日期，顾问不能自己定日期。\n"
                        "请申请者直接写出截止日期（例如 2027-01-15 或 1 月 15 日；没写年份时按下一个这一天算）。")
            fields["deadline"] = wanted
            if record["deadlineOrigin"] == COLLECTED and record["sourceUrl"]:
                # The catalogue's page was the source of the catalogue's date, not of this one.
                fields["source_url"] = None
            parts.append(f"截止日期记为 {wanted.isoformat()}")
        if stated_round:
            if len(stated_round) > 120 or not stated.said(texts, stated_round):
                return f"{REFUSED}对话里没有出现「{stated_round[:40]}」这个轮次，顾问不能自己定轮次。\nstated_round 要照抄申请者写过的原话。"
            fields["round"] = stated_round
            parts.append(f"轮次记为 {stated_round}")
        if not fields:
            return f"{REFUSED}没有给出要写的轮次或日期。\n传 catalog_deadline_id，或申请者说过的 stated_deadline、stated_round。"
        changes = _schedule_changes(record, fields, ENTERED, f"你在对话里说的，{UNCHECKED}")
        if not changes:
            return f"{SAME}「{name}」的轮次和截止日期已经是这样，没有要写入的改动。"
        return f"把「{name}」的" + "、".join(parts) + "（你说的）", changes, fields

    return _propose_update("propose_application_deadline", config, application_id, build)


# ---------------------------------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------------------------------


@tool
def propose_material_tick(
    application_id: str,
    config: RunnableConfig,
    state: Annotated[dict, InjectedState],
    ready: bool | None = None,
    add_note: str = "",
) -> str:
    """提议勾选或取消一条申请的材料自查，或往材料备注里加一行（必须经申请者确认后才写入）。application_id 取自
    get_my_applications。现在每条申请只有一个勾，表示这条申请的全部材料是否就绪：ready=true 勾上，ready=false 取消。
    申请者只说某一样材料备好了（例如推荐信）时不要勾，可以用 add_note 把他的原话加进材料备注。add_note 必须照抄
    申请者在对话里说过的话，不要改写，也不要写你自己知道的材料要求。"""
    note = str(add_note or "").strip()
    texts = stated.applicant_texts(state)
    ticks = {} if ready is None else {ALL_MATERIALS: bool(ready)}

    def build(record: dict, session):
        name = _name(record)
        if not ticks and not note:
            return f"{REFUSED}没有给出要改的内容。\n传 ready 勾选或取消，或传 add_note 加一行备注。"
        fields, changes, parts = {}, [], []
        for _material, wanted in ticks.items():
            if record["materialsReady"] != wanted:
                fields["materials_ready"] = wanted
                changes.append(change("材料", _ready(record["materialsReady"]), _ready(wanted)))
                parts.append("材料标为已就绪（自查）" if wanted else "材料改回准备中")
        if note:
            if len(note) > NOTE_LIMIT:
                return f"{REFUSED}一次加的备注最长 {NOTE_LIMIT} 字。"
            if not stated.said(texts, note):
                return f"{REFUSED}对话里没有出现这句话，备注只能记申请者自己写过的话。\nadd_note 要照抄原话，不要改写。"
            existing = record["materialNotes"] or ""
            if note not in existing.splitlines():
                fields["material_notes"] = f"{existing.rstrip()}\n{note}" if existing.strip() else note
                changes.append(change("材料备注", None, f"加一行：{note}"))
                parts.append("材料备注加一行")
        if not changes:
            return f"{SAME}「{name}」的材料已经是这样（{_ready(record['materialsReady'])}），没有要写入的改动。"
        return f"把「{name}」的" + "，".join(parts), changes, fields

    return _propose_update("propose_material_tick", config, application_id, build)


# ---------------------------------------------------------------------------------------------------
# Adding an application by hand
# ---------------------------------------------------------------------------------------------------


def _create_key(config: RunnableConfig, call_id: str) -> str:
    """The key of the one record this call may create: the conversation and the model's call id, both
    kept in the checkpoint, so the step run again after a crash asks for the same record."""
    thread = (config.get("configurable") or {}).get("thread_id") or ""
    return "adv-" + hashlib.sha256(f"{thread}:{call_id}".encode()).hexdigest()[:40]


@tool
def propose_manual_application(
    school: str,
    name: str,
    config: RunnableConfig,
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> str:
    """提议往「我的申请」里手动加一个学校库没有收录的项目（必须经申请者确认后才写入）。先用 search_programs 搜；
    学校库里搜得到的项目不要用这个工具，用 propose_portfolio_change 的 add。school 和 name 要照抄申请者在对话里
    写的学校和项目名称，不要翻译、补全或加别的内容。轮次和截止日期不在这里填：加好以后拿返回的申请 id，另用
    propose_application_deadline。"""
    client = client_id(config)
    try:
        payload = RecordCreate(school=school or "", name=name or "")
    except ValidationError:
        return f"{REFUSED}学校和项目名称都要填（学校最长 200 字，项目名称最长 300 字）。"
    texts = stated.applicant_texts(state)
    for what, value in (("学校", payload.school), ("项目名称", payload.name)):
        # A name is free text, so it is held to the applicant's own words like a note: otherwise a
        # date or a round nobody stated could be written into it.
        if not stated.said(texts, value):
            return f"{REFUSED}对话里没有出现「{value[:40]}」这个{what}，顾问不能自己写。\nschool 和 name 要照抄申请者写过的原话。"
    label = f"{payload.school} {payload.name}"
    key = _create_key(config, tool_call_id)
    duplicate = f"{REFUSED}「我的申请」里已经有「{label}」，没有再加一条。"
    with SessionLocal() as session:
        # Only a first run looks for a duplicate: a second run of the same call would find its own record.
        if records.find_created(session, client, key) is None and records.same_named(session, client, payload):
            return duplicate
    summary = f"把「{label}」加入我的申请（手动添加）"
    answer = interrupt({
        "type": CONFIRM_TYPE, "tool": "propose_manual_application", "summary": summary,
        "target": {"applicationId": None, "programId": None, "school": payload.school, "program": payload.name},
        "changes": [
            change("我的申请", None, "加入（手动添加）"),
            change("申请状态", None, STATUS_LABELS[ApplicationStatus.CONSIDERING]),
            change("截止日期", None, "待确认"),
        ],
    })
    approved, _shown, _base = answer_of(answer)
    if not approved:
        return f"{DECLINED}{summary}。没有改动。"
    try:
        with SessionLocal() as session:
            # Looked for again under the subject's lock: another conversation may have added it meanwhile.
            record, created = records.create_record(session, client, payload, key, unless_same_named=True)
    except records.InvalidRecord:
        return duplicate
    if not created:
        return f"{ALREADY}「{label}」之前已经加入我的申请，这次没有重复写入。申请 id：{record['id']}。"
    return f"{CHANGED}{summary}。申请 id：{record['id']}。轮次和截止日期还没有填。"


def applications_json(config: RunnableConfig) -> str:
    return to_json(read_for_advisor(client_id(config)))


APPLICATION_TOOLS = [
    propose_manual_application,
    propose_application_deadline,
    propose_application_status,
    propose_material_tick,
]
