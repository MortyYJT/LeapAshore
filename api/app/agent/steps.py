"""How a turn is described to the applicant, one step at a time.

The advisor's stream tells the interface what the agent is doing as `step` events: the intent router,
a retrieval, each tool call. This module holds the words for them, and decides what an event may carry.

What goes into an event, and what never does:

- A tool call's arguments are summarised as labelled values. They come from the model, which wrote them
  from the applicant's own message, so the applicant has seen them already.
- A tool's reply is never copied into an event. It is reduced to a status and one line: how many rows
  came back, that a write was saved, why a change was refused. A read of the profile or of the
  applications reports counts only; catalogue rows (public data) may be named.
- A tool this module does not know is still shown, by its name, with its arguments cut short and a
  generic outcome, so a tool added later needs no change in the interface. Adding it to `TITLES` and
  `_RESULTS` gives it better words.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field

from langchain_core.messages import ToolMessage

from app.agent import confirm
from app.agent.confirm import STATUS_LABELS as _STATUS_LABELS
from app.agent.tools import PROFILE_UPDATED, wrote

# Step kinds.
INTENT, RETRIEVAL, TOOL = "intent", "retrieval", "tool"

# Step statuses. `running` opens a step; every other status closes it (a `waiting` step is closed for
# this stream and opened again when the applicant answers).
RUNNING, DONE, EMPTY, FAILED, WAITING, DECLINED, STOPPED = (
    "running", "done", "empty", "failed", "waiting", "declined", "stopped",
)

TITLES = {
    "classify_intent": "判断问题类型",
    "retrieve_requirements": "检索学校库",
    "retrieve_passages": "检索官方页面",
    "answer_passages": "核对引文",
    "search_programs": "搜索项目",
    "get_my_profile": "读取背景",
    "update_my_profile": "更新背景",
    "get_my_portfolio": "读取选校组合",
    "get_my_applications": "读取申请",
    "propose_portfolio_change": "提议改组合",
    "propose_manual_application": "提议加申请",
    "propose_application_deadline": "提议改日期",
    "propose_application_status": "提议改状态",
    "propose_material_tick": "提议改材料",
}
# The step a confirmed change is written in.
WRITE_TITLE = "写入"

# Tools that write without asking first; a step of one is marked `write` from its start.
WRITES_DIRECTLY = {"update_my_profile"}

INTENT_LABELS = {
    "规划": "选校规划",
    "官方要求核验": "官方要求",
    "资料补充": "补充背景",
    "业务操作": "修改申请",
    "通用问答": "一般问题",
}
ROUTE_NOTES = {
    "requirements": "先查学校库再回答",
    "passages": "到官方页面的原文里找",
    "agent": "交给顾问处理",
}

PROFILE_LABELS = {
    "current_education_level": "当前学历",
    "school_origin": "院校所在地",
    "school_name": "学校",
    "domestic_tier": "院校层次",
    "overseas_band": "海外院校档次",
    "major": "专业",
    "gpa_score": "均分",
    "gpa_scale": "满分",
    "target_degree_level": "目标学位",
    "target_field": "目标方向",
    "intake": "入学时间",
    "english_score": "语言成绩",
    "annual_budget_cny": "年预算（元）",
}
ACTION_LABELS = {"add": "加入组合", "remove": "移出组合", "set_primary": "设为首选", "set_status": "改申请状态"}
TICK_LABELS = {True: "勾上（全部就绪）", False: "取消勾选"}
STATUS_LABELS = {status.value: label for status, label in _STATUS_LABELS.items()}

WAITING_FOR_ANSWER = "等你确认"
CONFIRMED = "你已确认"
SAVED = "已保存"
DECLINED_NOTE = "已取消，没有改动"
ALREADY_SAVED = "之前已经写入，这次没有重复写"
TOOL_BROKE = "这一步出错了，没有结果"
HALTED = "已停止，没有执行"
OUT_OF_STEPS = "这一轮的步骤数到了上限，没有执行"
INTERRUPTED = "这一轮出错了，这一步没有完成"

_VALUE_LIMIT = 80
_ARGUMENT_LIMIT = 6
_NAMES_SHOWN = 5


def title(name: str) -> str | None:
    return TITLES.get(name)


def _short(value, limit: int = _VALUE_LIMIT) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _row(label: str, value) -> dict:
    return {"label": label, "value": _short(value)}


def intent_result(intent: str, route: str | None) -> str:
    label = INTENT_LABELS.get(intent, intent)
    note = ROUTE_NOTES.get(route or "")
    return f"归为「{label}」，{note}" if note else f"归为「{label}」"


def call_args(
    name: str,
    args: dict | None,
    *,
    program_name: Callable[[str], str | None] | None = None,
    named: dict[str, str] | None = None,
) -> list[dict]:
    """A tool call's arguments as labelled values.

    The model names a program, an application or a collected deadline by its id; the applicant reads
    what it is. `named` gives the words for the id arguments the caller could resolve (by argument
    name), and `program_name` turns a program id into its name; an id nobody resolved is shown as it is.
    """
    args = args or {}
    named = named or {}
    if name == "search_programs":
        return [_row("关键词", args.get("keyword", ""))]
    if name == "update_my_profile":
        try:
            fields = json.loads(args.get("fields_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            return []
        if not isinstance(fields, dict):
            return []
        return [_row(PROFILE_LABELS.get(key, key), value) for key, value in list(fields.items())[:_ARGUMENT_LIMIT * 2]]
    if name == "propose_portfolio_change":
        program_id = str(args.get("program_id", ""))
        resolved = named.get("program_id") or (program_name(program_id) if program_name and program_id else None)
        rows = [_row("项目", resolved or program_id), _row("操作", ACTION_LABELS.get(args.get("action"), args.get("action", "")))]
        if args.get("action") == "add" and args.get("tier"):
            rows.append(_row("档位", args["tier"]))
        if args.get("action") == "set_status" and args.get("status"):
            rows.append(_row("状态", STATUS_LABELS.get(args["status"], args["status"])))
        return rows
    if name == "propose_manual_application":
        return [_row("学校", args.get("school", "")), _row("项目", args.get("name", ""))]
    if name in ("propose_application_status", "propose_application_deadline", "propose_material_tick"):
        rows = [_row("申请", named.get("application_id") or args.get("application_id", ""))]
        if name == "propose_application_status":
            rows.append(_row("状态", STATUS_LABELS.get(args.get("status"), args.get("status", ""))))
        elif name == "propose_application_deadline":
            if args.get("catalog_deadline_id"):
                rows.append(_row("学校库的日期", named.get("catalog_deadline_id") or args["catalog_deadline_id"]))
            if args.get("stated_deadline"):
                rows.append(_row("日期", args["stated_deadline"]))
            if args.get("stated_round"):
                rows.append(_row("轮次", args["stated_round"]))
        else:
            if isinstance(args.get("ready"), bool):
                rows.append(_row("材料", TICK_LABELS[args["ready"]]))
            if args.get("add_note"):
                rows.append(_row("备注", args["add_note"]))
        return rows
    if name in TITLES:
        return []
    return [_row(key, value) for key, value in list(args.items())[:_ARGUMENT_LIMIT]]


@dataclass
class Outcome:
    """How a tool call ended, in the applicant's words."""

    status: str
    result: str
    # Names worth listing under the result (catalogue rows only).
    items: list[str] = field(default_factory=list)
    write: bool = False

    def fields(self) -> dict:
        out: dict = {"result": self.result}
        if self.items:
            out["items"] = self.items
        if self.write:
            out["write"] = True
        return out


def _parsed(content: str):
    try:
        return json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return None


def _refused(content: str) -> Outcome | None:
    """The tools' own wording for a call that did nothing: `未执行：…`, `未更新：…`."""
    for prefix in (confirm.REFUSED, "未更新："):
        if content.startswith(prefix):
            # The first line is the reason, in the applicant's words; lines after it tell the model
            # how to call the tool, and stay out of the event.
            return Outcome(FAILED, _short("没有执行：" + content[len(prefix):].split("\n", 1)[0], 120))
    return None


def _search(content: str) -> Outcome:
    rows = _parsed(content)
    if not isinstance(rows, list) or not rows:
        return Outcome(EMPTY, "学校库里没有找到")
    names = [f"{r.get('school', '')} {r.get('program', '')}".strip() for r in rows if isinstance(r, dict)]
    return Outcome(DONE, f"找到 {len(rows)} 个项目", items=names[:_NAMES_SHOWN])


def _profile(content: str) -> Outcome:
    data = _parsed(content)
    if not isinstance(data, dict):
        return Outcome(DONE, "已读取")
    filled = sum(1 for value in data.values() if value is not None)
    return Outcome(DONE, f"已填 {filled} 项，未填 {len(data) - filled} 项")


def _profile_update(content: str) -> Outcome:
    if content.startswith(PROFILE_UPDATED):
        saved = _parsed(content[len(PROFILE_UPDATED):])
        count = len(saved) if isinstance(saved, dict) else 0
        return Outcome(DONE, f"已保存 {count} 项" if count else SAVED, write=True)
    return _refused(content) or Outcome(FAILED, "没有保存")


def _portfolio(content: str) -> Outcome:
    rows = _parsed(content)
    if not isinstance(rows, list) or not rows:
        return Outcome(EMPTY, "组合里还没有项目")
    return Outcome(DONE, f"组合里有 {len(rows)} 个项目")


def _applications(content: str) -> Outcome:
    rows = _parsed(content)
    if not isinstance(rows, list) or not rows:
        return Outcome(EMPTY, "还没有申请")
    return Outcome(DONE, f"读到 {len(rows)} 个申请")


def _change(content: str) -> Outcome:
    """A change that asked first: written, written by an earlier run of the same call, declined or refused."""
    if content.startswith(confirm.CHANGED):
        return Outcome(DONE, SAVED, write=True)
    if content.startswith(confirm.ALREADY):
        return Outcome(DONE, ALREADY_SAVED)
    if content.startswith(confirm.SAME):
        # Nothing to ask or write: a hollow stop, not a failure (see `confirm.SAME`).
        return Outcome(EMPTY, _short(content[len(confirm.SAME):].split("\n", 1)[0], 120))
    if content.startswith(confirm.DECLINED):
        return Outcome(DECLINED, DECLINED_NOTE)
    return _refused(content) or Outcome(FAILED, "没有执行")


def _unknown(content: str) -> Outcome:
    refused = _refused(content)
    if refused:
        return refused
    if wrote(ToolMessage(content=content, tool_call_id="")):
        return Outcome(DONE, SAVED, write=True)
    data = _parsed(content)
    if isinstance(data, list):
        return Outcome(DONE if data else EMPTY, f"返回 {len(data)} 条")
    return Outcome(DONE, "已完成")


_RESULTS: dict[str, Callable[[str], Outcome]] = {
    "search_programs": _search,
    "get_my_profile": _profile,
    "update_my_profile": _profile_update,
    "get_my_portfolio": _portfolio,
    "get_my_applications": _applications,
    "propose_portfolio_change": _change,
    "propose_manual_application": _change,
    "propose_application_deadline": _change,
    "propose_application_status": _change,
    "propose_material_tick": _change,
}


def call_result(name: str, message: ToolMessage) -> Outcome:
    """Reduce a tool's reply to a status and one line. The reply itself stays out of the event."""
    if getattr(message, "status", None) == "error":
        return Outcome(FAILED, TOOL_BROKE)
    content = message.content if isinstance(message.content, str) else ""
    return _RESULTS.get(name, _unknown)(content)


def requirements_result(update: dict) -> Outcome:
    """The catalogue retrieval: how many programs came back with a citable source, and which."""
    citations = update.get("citations") or []
    if not update.get("evidence_strong") or not citations:
        return Outcome(EMPTY, "没有可引用的官方来源")
    return Outcome(DONE, f"找到 {len(citations)} 个有官方来源的项目",
                   items=[c.get("program", "") for c in citations][:_NAMES_SHOWN])


def passages_result(update: dict) -> Outcome:
    found = update.get("passages") or []
    if not update.get("evidence_strong") or not found:
        return Outcome(EMPTY, "官方页面里没有找到相关段落")
    pages = len({p.get("url") for p in found})
    return Outcome(DONE, f"找到 {len(found)} 段原文，来自 {pages} 个官方页面")


def check_result(update: dict) -> Outcome:
    """The quote check of an answer written from official pages (openspec snapshot-rag D8, D9)."""
    summary = (update.get("trace") or {}).get("citation_check") or {}
    kept, total = summary.get("kept", 0), summary.get("sentences", 0)
    if not update.get("citations"):
        return Outcome(EMPTY, "没有一句能和原文核对上")
    dropped = total - kept
    return Outcome(DONE, f"{kept} 句和原文核对上了" + (f"，删去 {dropped} 句" if dropped > 0 else ""))
