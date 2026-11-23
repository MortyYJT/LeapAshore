"""What the advisor's model sees of a long conversation: three tiers, computed for every model step.

The stored thread (the checkpoint, and what the applicant reads) is never changed. Only the copy
handed to the model is shortened:

- **Recent** — the current turn and the turn before it, whatever their size, then older turns while
  they fit `RECENT_BUDGET`, all in full: tool calls, tool replies, everything. A turn is cut only at a human
  message, so a tool call is never separated from its reply.
- **Middle** — the turns before that, while their short form fits `MIDDLE_BUDGET`. The applicant's
  messages are kept word for word; the advisor's reply is cut to its first `REPLY_SENTENCES`
  sentences. Calls of read-only tools are dropped (their replies are snapshots of data that may have
  changed since, and the model can read again); a change the advisor proposed or made is kept as one
  line with its outcome: written, declined, refused, or never answered.
- **Far** — everything older, as text in the system prompt: a summary written by the chat model
  (`refresh`), stored in the graph state and extended a few turns at a time, then the turns the
  summary does not cover yet, cut to their first sentences, and a ledger of the changes the advisor
  proposed or made, written by this module and not by a model, so a summary that drops one does not
  lose it: every change written and every proposal nobody answered stays in it.

Sizes are counted with `estimate_tokens`, a character-class estimate calibrated against tiktoken's
`cl100k_base` (docs/measurements.md, "Advisor memory tiers"): the runtime has no tokenizer of its own
and must not download one.

A turn's tier is decided by the turns before the current one only, so tiers do not move within a turn
however long its tool replies are. Turns move from recent to middle to far as the conversation grows,
never back.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langgraph.constants import TAG_NOSTREAM

from app.agent import confirm, steps
from app.agent.tools import wrote

logger = logging.getLogger(__name__)

# --- sizes, in estimated tokens (docs/measurements.md, "Advisor memory tiers") ---
# The recent tier, beyond the current turn and the one before it, which are kept whatever their size.
RECENT_BUDGET = 3_000
RECENT_MIN_TURNS = 2
# The middle tier's short form.
MIDDLE_BUDGET = 1_500
# The far turns no summary covers yet: once their short form passes this, the model summarises them.
SUMMARY_TRIGGER = 1_200
# At most this much goes into one summary call; the rest waits for the next turn.
SUMMARY_INPUT_BUDGET = 4_000
# The summary call's output cap, and how long the turn waits for it. A call still running then is not
# cancelled: it finishes and is charged (as `app.agent.halt` does for a stopped turn), its answer unused.
SUMMARY_MAX_TOKENS = 600
SUMMARY_TIMEOUT_SECONDS = 30.0
# After a summary that failed, how many turns pass before the next try.
SUMMARY_RETRY_TURNS = 3
# The far turns shown sentence by sentence (not summarised yet, or the summary failed): newest first.
# Above the trigger, so nothing is left out while summaries succeed.
FALLBACK_BUDGET = 1_600
# Ledger entries for changes that came to nothing (declined, refused, already so): the newest only.
# Changes written and proposals nobody answered are always kept.
LEDGER_IDLE_MAX = 10
# The intent router's view of the conversation (`intent_history`), and how much of one of the
# applicant's messages it keeps.
INTENT_BUDGET = 400
INTENT_USER_CHARS = 300

# How much of an advisor reply the middle tier keeps, and how much a far line keeps.
REPLY_SENTENCES = 2
REPLY_CHARS = 160
FAR_CHARS = 100
USER_FAR_CHARS = 160

CUT = "……"
CODE = "（代码从略）"

# --- token estimate ---

# Han, kana, CJK punctuation and full-width forms: about one cl100k token or more each.
_WIDE = re.compile(r"[⺀-〿぀-ヿ㐀-䶿一-鿿豈-﫿＀-￯]")
# Calibrated on the representative threads (docs/measurements.md): rounded up, so the estimate errs high.
WIDE_TOKENS = 1.2
OTHER_CHARS_PER_TOKEN = 3.0
# What a chat message costs beyond its text (role and separators).
MESSAGE_OVERHEAD = 4


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    wide = len(_WIDE.findall(text))
    return math.ceil(wide * WIDE_TOKENS + (len(text) - wide) / OTHER_CHARS_PER_TOKEN)


def _text(message: AnyMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(part if isinstance(part, str) else str(part.get("text", "")) for part in content
                       if isinstance(part, (str, dict)))
    return str(content)


def message_tokens(message: AnyMessage) -> int:
    total = MESSAGE_OVERHEAD + estimate_tokens(_text(message))
    for call in getattr(message, "tool_calls", None) or []:
        total += estimate_tokens(call.get("name", "") + json.dumps(call.get("args") or {}, ensure_ascii=False))
    return total


def messages_tokens(messages: Sequence[AnyMessage]) -> int:
    return sum(message_tokens(m) for m in messages)


# --- sentences ---

_FENCE = re.compile(r"```.*?(?:```|\Z)", re.S)
# A list marker or heading at the start of a line: part of the first sentence, never an end of one.
_MARKER = re.compile(r"^\s*(?:#{1,6}\s+|[-*+•·]\s+|\d{1,3}[.)、．]\s*|[（(]\d{1,3}[)）]\s*)")
# A sentence end: Chinese or full-width marks, an ellipsis, or `.`, `!`, `?` before a space or the end
# of the line. Closing quotes and brackets, and citation marks like [1], stay with their sentence.
_END = re.compile(r"(?:[。！？!?]+|…+|\.{3}|(?<!\.)\.(?=\s|$))[”’\"'」』）)\]]*(?:\s*\[\d+\])*")
# Words whose period is not a sentence end.
_ABBREVIATIONS = ("e.g.", "i.e.", "etc.", "vs.", "Dr.", "Mr.", "Ms.", "Mrs.", "No.", "St.", "Prof.", "approx.")


def _period_is_end(line: str, end: int) -> bool:
    """Whether the `.` ending at `end` ends a sentence: not after an abbreviation or a single letter (U.S.)."""
    before = line[:end]
    if before.endswith(_ABBREVIATIONS):
        return False
    word = re.search(r"(\S+)$", before)
    return not (word and re.fullmatch(r"(?:[A-Za-z]\.)+", word.group(1)))


def sentences(text: str) -> list[str]:
    """The sentences of `text`, in order. A line is always a boundary (lists, headings, short lines); a
    fenced code block is one sentence, `CODE`."""
    text = _FENCE.sub(f"\n{CODE}\n", text or "")
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        marker = _MARKER.match(line)
        start = 0
        search_from = marker.end() if marker else 0
        for match in _END.finditer(line, search_from):
            mark = match.group(0)
            if mark.startswith(".") and not mark.startswith("...") and not _period_is_end(line, match.start() + 1):
                continue
            piece = line[start:match.end()].strip()
            if piece:
                out.append(piece)
            start = match.end()
        rest = line[start:].strip()
        if rest:
            out.append(rest)
    return out


def _join(parts: Sequence[str]) -> str:
    text = ""
    for part in parts:
        if text and not _WIDE.search(text[-1]) and not _WIDE.search(part[0]):
            text += " "
        text += part
    return text


def first_sentences(text: str, count: int = REPLY_SENTENCES, limit: int = REPLY_CHARS) -> str:
    """The first `count` sentences of `text`, at most `limit` characters, marked with `CUT` when anything
    was left out."""
    found = sentences(text)
    kept = _join(found[:count])
    cut = len(found) > count
    if len(kept) > limit:
        kept, cut = kept[: limit - 1].rstrip(), True
    return kept + CUT if cut and kept else kept


# --- turns and tiers ---

Turn = list[AnyMessage]


def turns(messages: Sequence[AnyMessage]) -> list[Turn]:
    """The thread cut before every human message. Anything before the first one joins the first turn."""
    out: list[Turn] = []
    for message in messages:
        if isinstance(message, HumanMessage) or not out:
            out.append([message])
        else:
            out[-1].append(message)
    return out


def _is_action(name: str) -> bool:
    """A tool that changes something: every `propose_` tool waits for a confirm, and the tools that
    write at once (`steps.WRITES_DIRECTLY`)."""
    return name.startswith("propose_") or name in steps.WRITES_DIRECTLY


UNANSWERED = "申请者没有回应，未执行"


def _lasting(reply: ToolMessage | None) -> bool:
    """Whether a change's outcome must stay in view: it wrote, or nobody answered it."""
    return reply is None or wrote(reply) or _text(reply).startswith(confirm.ALREADY)


def _actions(turn: Turn) -> list[tuple[str, bool]]:
    """Each change in the turn as (line, lasting)."""
    replies = {m.tool_call_id: m for m in turn if isinstance(m, ToolMessage)}
    out = []
    for message in turn:
        if not isinstance(message, AIMessage):
            continue
        for call in message.tool_calls:
            if not _is_action(call["name"]):
                continue
            title = steps.title(call["name"]) or call["name"]
            reply = replies.get(call["id"])
            if reply is not None:
                out.append((f"〔{title}〕{_text(reply).split(chr(10), 1)[0].strip()}", _lasting(reply)))
            else:
                args = "，".join(f"{row['label']}：{row['value']}" for row in steps.call_args(call["name"], call.get("args")))
                out.append((f"〔{title}〕{args + ' → ' if args else ''}{UNANSWERED}", True))
    return out


def actions(turn: Turn) -> list[str]:
    """One line per change the advisor proposed or made in this turn, with how it ended. A tool's reply
    names what it changed, so the call's arguments are shown only when there is no reply."""
    return [line for line, _ in _actions(turn)]


def _human(turn: Turn) -> HumanMessage | None:
    return turn[0] if turn and isinstance(turn[0], HumanMessage) else None


def _reply(turn: Turn) -> str:
    """The advisor's answer in this turn: its last message with words (an earlier one is a preamble to
    a tool call, "我先查一下")."""
    for message in reversed(turn):
        if isinstance(message, AIMessage) and _text(message).strip():
            return _text(message)
    return ""


def compact(turn: Turn) -> list[AnyMessage]:
    """The middle tier's form of a turn: the applicant's message as it is, then one advisor message
    with the changes it proposed or made and the first sentences of its reply. No tool calls."""
    out: list[AnyMessage] = []
    human = _human(turn)
    if human is not None:
        out.append(human)
    lines = actions(turn)
    reply = _reply(turn)
    if reply:
        lines.append(first_sentences(reply))
    if lines:
        out.append(AIMessage(content="\n".join(lines)))
    return out


def far_lines(turn: Turn) -> list[str]:
    """A far turn sentence by sentence: the applicant's first sentences and the advisor's first one.
    Its changes are in the ledger."""
    lines = []
    human = _human(turn)
    if human is not None:
        lines.append("申请者：" + first_sentences(_text(human), 3, USER_FAR_CHARS))
    reply = _reply(turn)
    if reply:
        lines.append("顾问：" + first_sentences(reply, 1, FAR_CHARS))
    return lines


def _full_cost(turn: Turn) -> int:
    return messages_tokens(turn)


def _compact_cost(turn: Turn) -> int:
    return messages_tokens(compact(turn))


@dataclass
class Tiers:
    turns: list[Turn]
    middle_start: int  # turns[:middle_start] are far
    recent_start: int  # turns[middle_start:recent_start] are middle, the rest recent

    @property
    def far(self) -> list[Turn]:
        return self.turns[: self.middle_start]

    @property
    def middle(self) -> list[Turn]:
        return self.turns[self.middle_start : self.recent_start]

    @property
    def recent(self) -> list[Turn]:
        return self.turns[self.recent_start :]


def tiers(messages: Sequence[AnyMessage], covered: int = 0) -> Tiers:
    """Split the thread into the three tiers. The last `RECENT_MIN_TURNS` turns are always recent and do
    not count against the budget; `covered` turns from the start are summarised already and are never put
    back in the middle tier."""
    split = turns(messages)
    n = len(split)
    recent_start = max(0, n - RECENT_MIN_TURNS)
    used = 0
    while recent_start > 0 and used + _full_cost(split[recent_start - 1]) <= RECENT_BUDGET:
        recent_start -= 1
        used += _full_cost(split[recent_start])
    middle_start, used = recent_start, 0
    while middle_start > 0 and used + _compact_cost(split[middle_start - 1]) <= MIDDLE_BUDGET:
        middle_start -= 1
        used += _compact_cost(split[middle_start])
    covered = max(0, min(covered, recent_start))
    return Tiers(split, max(middle_start, covered), recent_start)


# --- what the model is shown ---

FAR_HEADING = "\n\n## 更早的对话（已压缩）\n以下是这段对话较早部分的压缩，只供参考：其中的申请数据可能已经变了，改动前先用工具读取现在的内容。\n"
SUMMARY_HEADING = "摘要：\n"
LEDGER_HEADING = "顾问提议或做过的改动（按时间，系统记录）：\n"
LINES_HEADING = "摘要之后的对话（每句只留开头）：\n"


def ledger(far: Sequence[Turn]) -> list[str]:
    """Every change written and every proposal nobody answered, in order; of the changes that came to
    nothing, the newest `LEDGER_IDLE_MAX`."""
    entries = [entry for turn in far for entry in _actions(turn)]
    idle = [i for i, (_, lasting) in enumerate(entries) if not lasting]
    dropped = set(idle[: max(0, len(idle) - LEDGER_IDLE_MAX)])
    lines = [line for i, (line, _) in enumerate(entries) if i not in dropped]
    return [f"（更早的 {len(dropped)} 项没有改动的提议从略）", *lines] if dropped else lines


def _lines_cost(lines: Sequence[str]) -> int:
    return sum(estimate_tokens(line) + 1 for line in lines)


def _newest_within(lines: list[str], budget: int) -> list[str]:
    kept: list[str] = []
    used = 0
    for line in reversed(lines):
        cost = _lines_cost([line])
        if used + cost > budget:
            break
        kept.append(line)
        used += cost
    kept.reverse()
    if len(kept) < len(lines):
        kept.insert(0, "（更早的从略）")
    return kept


def far_text(t: Tiers, summary: str, covered: int) -> str:
    """The far tier as a section of the system prompt; empty while there is no far tier."""
    far = t.far
    if not far:
        return ""
    parts = []
    if summary and covered:
        parts.append(SUMMARY_HEADING + summary.strip())
    pending = [line for turn in far[min(covered, len(far)):] for line in far_lines(turn)]
    if pending:
        parts.append(LINES_HEADING + "\n".join(_newest_within(pending, FALLBACK_BUDGET)))
    entries = ledger(far)
    if entries:
        parts.append(LEDGER_HEADING + "\n".join(entries))
    return FAR_HEADING + "\n\n".join(parts) if parts else ""


@dataclass
class View:
    far: str  # appended to the system prompt
    history: list[AnyMessage]  # the middle tier's short form, then the recent tier in full


def view(messages: Sequence[AnyMessage], summary: str = "", covered: int = 0) -> View:
    t = tiers(messages, covered)
    history: list[AnyMessage] = [m for turn in t.middle for m in compact(turn)]
    history += [m for turn in t.recent for m in turn]
    return View(far_text(t, summary, covered), history)


def intent_history(messages: Sequence[AnyMessage], covered: int = 0) -> str:
    """The router's view: the middle and recent tiers before the current message, one line per message,
    the advisor's replies cut as in the middle tier, no tool output, newest lines within
    `INTENT_BUDGET`; the applicant's messages up to `INTENT_USER_CHARS` each. The far tier is left
    out: the router only needs to know what "it" refers to."""
    t = tiers(messages, covered)
    lines = []
    for turn in [*t.middle, *t.recent][:-1]:
        human = _human(turn)
        if human is not None and _text(human).strip():
            lines.append(f"用户：{first_sentences(_text(human), 1_000, INTENT_USER_CHARS)}")
        reply = _reply(turn)
        if reply:
            lines.append(f"顾问：{first_sentences(reply)}")
    return "\n".join(_newest_within(lines, INTENT_BUDGET)) if lines else ""


# --- the summary ---

SUMMARY_PROMPT = """你在为留学申请顾问压缩一段较早的对话，供顾问之后参考。把「已有摘要」和「新的对话」合并成一份新的摘要。

要求：
- 中文，分条，不超过 400 字。
- 必须保留：讨论过的学校和项目（写全名）；申请者确认、拒绝或没有回应的提议；已经写入申请者记录的改动（背景、选校组合、申请、截止日期、材料）；申请者亲口说的日期、成绩、偏好和顾虑。
- 只写对话里出现过的内容，不补充、不推测录取要求或日期。
- 只输出摘要本身。

已有摘要：
{summary}

新的对话：
{dialogue}"""


def _summary_input(turn: Turn) -> list[str]:
    """A turn as the summariser reads it: the applicant whole, the advisor's first sentences, the changes."""
    lines = []
    human = _human(turn)
    if human is not None:
        lines.append("申请者：" + _text(human).strip())
    lines += [f"顾问操作：{line}" for line in actions(turn)]
    reply = _reply(turn)
    if reply:
        lines.append("顾问：" + first_sentences(reply, 4, 400))
    return lines


@dataclass
class Refresh:
    """What a turn's summary step did: the state to store (if any) and a word for the trace."""

    update: dict
    outcome: str  # "none" (nothing due), "updated", or "failed: <why>" (the old summary stays)


# Summary calls the turn stopped waiting for, kept referenced until they finish (and are charged).
_late: set[asyncio.Future] = set()


def _settled(call: asyncio.Future) -> None:
    """Forget a finished call, and read its error so asyncio never logs it: an error from an
    applicant's provider can repeat their key, and this may run after the turn's log scrubbing ended."""
    _late.discard(call)
    if not call.cancelled():
        call.exception()


async def refresh(
    messages: Sequence[AnyMessage], summary: str, covered: int, model: Callable[[], object], failed_at: int = 0
) -> Refresh:
    """Extend the stored summary when the far turns it does not cover have grown past `SUMMARY_TRIGGER`.

    `model` builds the chat model (the applicant's own when the turn runs on their key). Never raises:
    a failure (no model, an error, an empty answer, `SUMMARY_TIMEOUT_SECONDS`) keeps the old summary,
    the uncovered turns go on being shown sentence by sentence, and the next try waits
    `SUMMARY_RETRY_TURNS` turns (`failed_at` is the turn count of the last failure, 0 for none).
    """
    t = tiers(messages, covered)
    covered = max(0, min(covered, len(t.far)))
    pending = t.far[covered:]
    if not pending or _lines_cost([line for turn in pending for line in far_lines(turn)]) < SUMMARY_TRIGGER:
        return Refresh({}, "none")
    if failed_at and len(t.turns) < failed_at + SUMMARY_RETRY_TURNS:
        return Refresh({}, "none")
    take, lines, used = 0, [], 0
    for turn in pending:
        block = _summary_input(turn)
        cost = _lines_cost(block)
        if take and used + cost > SUMMARY_INPUT_BUDGET:
            break
        take, used = take + 1, used + cost
        lines += block
    prompt = SUMMARY_PROMPT.format(summary=summary.strip() or "（无）", dialogue="\n".join(lines))
    failed = {"memory_failed_at": len(t.turns)}
    try:
        # Kept out of the stream: the applicant reads the answer, never the summary.
        summariser = model().with_config(tags=[TAG_NOSTREAM])
        call = asyncio.ensure_future(summariser.ainvoke(prompt))
        _late.add(call)
        call.add_done_callback(_settled)
        # `wait` does not cancel the call when the turn stops waiting, or when this step is cancelled.
        await asyncio.wait({call}, timeout=SUMMARY_TIMEOUT_SECONDS)
        if not call.done():
            logger.warning("advisor memory summary still running after %.0f s; not waiting", SUMMARY_TIMEOUT_SECONDS)
            return Refresh(failed, "failed: timeout")
        reply = call.result()
        text = _text(reply).strip() if isinstance(reply, AIMessage) else ""
    except asyncio.CancelledError:
        raise
    except Exception as error:  # noqa: BLE001 - a summary must never fail the applicant's turn
        logger.warning("advisor memory summary failed: %s", type(error).__name__)
        return Refresh(failed, f"failed: {type(error).__name__}")
    if not text:
        return Refresh(failed, "failed: empty")
    return Refresh({"memory_summary": text, "memory_turns": covered + take, "memory_failed_at": 0}, "updated")
