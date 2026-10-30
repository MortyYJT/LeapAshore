"""Check that a summary says only what its quote says (TASKS.md P1 「概括忠实度校验」).

    python -m app.collect.faithful [--apply] [--budget-cny 30] [--concurrency 8] [paths ...]
    python -m app.collect.faithful --forget FIELD [paths ...]   # after changing a field's claim wording

`verify` proves that a quote is on the page and that the numbers a field states are inside it. It
cannot tell whether the words the collector wrote around them are faithful: an academic summary that
adds "Bachelor's degree or comparable foreign degree" to a quote that only gives a GPA passes it (UT
Austin's MSCS, `tests/test_collect_faithful.py`). This module asks the advisor's chat model, for each
field, whether its quote on its own states the claim, and keeps the verdict on the item
(`summary_check`, `summary_sha`, see `app.collect.verify`). A claim the quote does not back is
downgraded, never deleted or edited: the value stays in the file with the reason, is not imported, and
its program is `待人工` until a person looks.

One request per program carries all its claims (temperature 0, function calling). A verdict the model
does not return, or an answer that cannot be read twice in a row, counts as not checked, which blocks
like an unfaithful one: a claim nobody checked is not passed. The same judge checks the advisor's
answers from page passages (`app.agent.answer.support_check`): each kept sentence against its quotes.

Run as a module it is the backfill over the requirement files: without `--apply` it only counts what
would be sent and estimates the cost; with it, it judges every usable item without a current verdict,
writes each school's file as it finishes, and stops sending once the spend reaches `--budget-cny`.
Nothing here writes `verified_at`.
"""

import argparse
import copy
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

from app.agent.llm import ACCOUNT, outage
from app.collect.verify import (
    LIST_FIELDS,
    SUMMARY_CHECK,
    SUMMARY_SHA,
    program_status,
    set_summary_verdict,
    summary_verdict,
)
from app.config import settings

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "requirements"
MAX_ATTEMPTS = 2
OK = "ok"
NOT_CHECKED = "not checked"
# The judge's reply is a short verdict per claim; a program has at most a few dozen claims.
JUDGE_MAX_TOKENS = 2000

PROMPT = """You check a database of university admission information. Each claim below was written by \
a model from quotes it copied from official pages. The quotes are verbatim page text, and code has \
already found every number and date of a claim inside its quotes. Decide, for each claim, whether its \
quotes on their own state what the claim says.

{context}

supported = false when the claim says something material that its quotes do not state, or contradicts them:
- an added condition, subject, degree, test, score, document, experience, date, round, intake or audience \
(for example "Bachelor's degree" when the quote only gives a GPA; "for international students" when the \
quote does not say who);
- a requirement where the quote only recommends, prefers or describes admitted students, or the reverse;
- a stronger or weaker statement than the quote ("required" for "may be required", "not accepted" for \
"not required", "only" or "all" the quote does not say);
- a number in the wrong role (a section minimum given as the overall score, a fee for another program);
- information said to be about a program or group when the quote's source is another program's page.
supported = true when the claim restates, translates, shortens or leaves out part of its quotes. Generic \
words that only name what the field is ("Application deadline", "Minimum IELTS", "Prerequisite") and \
date formats (2027-01-12 for "January 12, 2027") are fine, and "985/211" and "Double First-Class" name \
one group of Chinese universities.
Judge meaning, not wording: flag only what would tell an applicant something the quotes do not. The \
field name only says where a value is filed; it is not part of the claim. Judge each claim only on its \
own quotes. Do not use what you know about the school.
Return one verdict per claim id. When supported is false, `unsupported` names the words of the claim \
that the quotes do not back, in a few words.

Claims:
{claims}"""


class Verdict(BaseModel):
    id: int = Field(description="The claim's id")
    # Optional so that one verdict with a missing flag does not void the others: it is read below.
    supported: bool | None = Field(None, description="True when the quotes on their own state everything the claim says")
    unsupported: str | None = Field(None, description="When not supported: what the claim says that the quotes do not, in a few words")


class Verdicts(BaseModel):
    """One verdict per claim."""

    verdicts: list[Verdict] = Field(default_factory=list)


@dataclass
class Claim:
    id: int
    statement: str
    quotes: list[tuple[str | None, str]]  # (source name or None, verbatim quote)
    field: str | None = None


@dataclass
class Judgement:
    verdicts: dict[int, str]  # claim id -> "ok" or the reason; a missing id was not judged
    usage: dict = field(default_factory=dict)
    model: str | None = None
    attempts: int = 0
    error: str | None = None
    raw: list[dict | None] = field(default_factory=list)  # each attempt's arguments (None: unreadable)


def _usage(raw) -> dict:
    meta = getattr(raw, "usage_metadata", None) or {}
    details = meta.get("input_token_details") or {}
    return {"input_tokens": meta.get("input_tokens", 0), "output_tokens": meta.get("output_tokens", 0),
            "cache_read_tokens": details.get("cache_read", 0) or 0}


def cost_cny(usage: dict) -> float:
    """The upper-bound cost of reported usage at the configured prices (DeepSeek's peak price)."""
    hit = usage.get("cache_read_tokens", 0) or 0
    miss = (usage.get("input_tokens", 0) or 0) - hit
    out = usage.get("output_tokens", 0) or 0
    return (hit * settings.collect_price_cache_hit + miss * settings.collect_price_cache_miss
            + out * settings.collect_price_output) / 1e6


def render_claims(claims: list[Claim]) -> str:
    blocks = []
    for claim in claims:
        lines = [f"[{claim.id}]" + (f" field: {claim.field}" if claim.field else ""), f"claim: {claim.statement}"]
        for source, quote in claim.quotes:
            lines.append(f"quote{f' (from {source})' if source else ''}: \"\"\"{quote}\"\"\"")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def prompt_for(claims: list[Claim], context: str) -> str:
    return PROMPT.format(context=context, claims=render_claims(claims))


def _read(answer: dict, claims: list[Claim]) -> dict[int, str]:
    known = {c.id for c in claims}
    verdicts: dict[int, str] = {}
    for v in answer["parsed"].verdicts:
        if v.id not in known or v.id in verdicts:
            continue
        reason = (v.unsupported or "").strip()
        if v.supported is None and not reason:
            continue  # no verdict for this claim: it stays not checked
        if v.supported:
            verdicts[v.id] = OK
        else:  # false, or no flag but a list of what the quotes do not back
            verdicts[v.id] = f"unsupported: {reason or 'the quote does not state the claim'}"[:300]
    return verdicts


def _note(result: Judgement, answer: dict) -> bool:
    raw = answer["raw"]
    result.attempts += 1
    result.model = (raw.response_metadata or {}).get("model_name") or result.model
    for key, value in _usage(raw).items():
        result.usage[key] = result.usage.get(key, 0) + value
    if not answer.get("parsing_error") and answer.get("parsed") is not None:
        calls = getattr(raw, "tool_calls", None) or []
        result.raw.append(calls[0]["args"] if calls else answer["parsed"].model_dump())
        result.error = None
        return True
    result.raw.append(None)
    why = answer.get("parsing_error") or "no function call"
    result.error = f"no usable answer: {str(why)[:300]}"
    return False


def _structured(model: BaseChatModel):
    return model.with_structured_output(Verdicts, method="function_calling", include_raw=True)


def judge(claims: list[Claim], context: str, model: BaseChatModel | None = None) -> Judgement:
    """Ask the model whether each claim's quotes state it. A malformed answer is asked for once more."""
    result = Judgement(verdicts={})
    if not claims:
        return result
    if model is None:
        from app.agent.llm import get_chat_model

        model = get_chat_model(temperature=0, max_tokens=JUDGE_MAX_TOKENS)
    structured = _structured(model)
    prompt = prompt_for(claims, context)
    for _ in range(MAX_ATTEMPTS):
        answer = structured.invoke(prompt)
        if _note(result, answer):
            result.verdicts = _read(answer, claims)
            break
    return result


async def ajudge(claims: list[Claim], context: str, model: BaseChatModel) -> Judgement:
    """`judge` for the advisor's event loop. One attempt: a turn does not wait for a second call."""
    result = Judgement(verdicts={})
    if not claims:
        return result
    answer = await _structured(model).ainvoke(prompt_for(claims, context))
    if _note(result, answer):
        result.verdicts = _read(answer, claims)
    return result


# --- Requirement fields ------------------------------------------------------------------------------


def _number(value) -> str:
    return f"{value:g}" if isinstance(value, (int, float)) else str(value)


def statement(name: str, item: dict) -> str | None:
    """What the field claims, in words; None when it claims nothing beyond its own quote."""
    text = (item.get("text") or "").strip()
    if name == "academic":
        return text or None
    if name == "china_requirement":
        # No "for applicants with Chinese degrees" and no "985/211": the field says whom it is for, and
        # the quote is often the school's page for China in its own tier words (a first backfill with
        # those words in the claim blocked 74% of these fields for them; see TASKS.md P1 #6).
        parts = [text] if text else []
        if item.get("min_mark_211") is not None:
            parts.append(f"minimum average {_number(item['min_mark_211'])}% for the higher group of universities")
        if item.get("min_mark_other") is not None:
            parts.append(f"minimum average {_number(item['min_mark_other'])}% for the other universities")
        return "; ".join(parts) or None
    if name in ("ielts", "toefl"):
        test = "IELTS" if name == "ielts" else "TOEFL iBT"
        kind = "Recommended (not a minimum)" if item.get("recommended") else "Minimum"
        parts = []
        if item.get("overall") is not None:
            parts.append(f"overall {_number(item['overall'])}")
        if item.get("min_band") is not None:
            parts.append(f"no section below {_number(item['min_band'])}")
        if text:
            parts.append(text)
        return f"{kind} {test}: {', '.join(parts)}" if parts else None
    if name == "prerequisites":
        return text or None
    if name == "deadlines":
        label = (item.get("label") or "").strip()
        return f"Application deadline{f' ({label})' if label else ''}: {item.get('date')}"
    return None


def needs_judgement(item: dict) -> bool:
    """A usable-so-far item with no current verdict, or one whose last check did not happen."""
    if not isinstance(item, dict) or item.get("check") != "ok":
        return False
    verdict = summary_verdict(item)
    return verdict is None or verdict.startswith(NOT_CHECKED)


def _items(program: dict):
    for name, value in program.get("fields", {}).items():
        for item in value if name in LIST_FIELDS else [value]:
            yield name, item


def program_claims(program: dict, *, recheck: bool = False) -> tuple[list[Claim], dict[int, dict], list[dict]]:
    """The claims to send for one program, the item each claim id stands for, and the items that need
    no model (a prerequisite with no summary is its own quote)."""
    claims, items, trivial = [], {}, []
    for name, item in _items(program):
        if not (needs_judgement(item) or (recheck and item.get("check") == "ok")):
            continue
        said = statement(name, item)
        if said is None:
            trivial.append(item)
            continue
        claim_id = len(claims) + 1
        claims.append(Claim(id=claim_id, statement=said, quotes=[(None, item["quote"])], field=name))
        items[claim_id] = item
    return claims, items, trivial


def program_context(program: dict, school_name: str) -> str:
    return (f"School: {school_name}. Program: {program.get('name')}. The school and program are context, "
            "not evidence: a claim is backed only by its quote.")


def check_program(program: dict, school_name: str, model: BaseChatModel | None = None,
                  *, recheck: bool = False) -> Judgement:
    """Judge every item of `program` that needs it, record the verdicts on the items and its status."""
    claims, items, trivial = program_claims(program, recheck=recheck)
    for item in trivial:
        set_summary_verdict(item, OK)
    result = judge(claims, program_context(program, school_name), model) if claims else Judgement(verdicts={})
    for claim_id, item in items.items():
        if claim_id in result.verdicts:
            set_summary_verdict(item, result.verdicts[claim_id])
        else:
            set_summary_verdict(item, f"{NOT_CHECKED}: {result.error or 'the judge returned no verdict'}"[:300])
    if claims or trivial:
        program["status"] = program_status(program)
    return result


# --- Backfill over the requirement files ---------------------------------------------------------------


def requirement_files(directory: Path = DATA_DIR) -> list[Path]:
    return sorted(p for p in directory.glob("*.json") if not p.name.startswith("_"))


def _summarise(data: dict) -> None:
    summary = {"programs": 0, "机器核对": 0, "待人工": 0}
    for program in data["programs"]:
        summary["programs"] += 1
        summary[program_status(program)] += 1
    data["verification"] = summary


def estimate(paths: list[Path]) -> dict:
    """What the backfill would send: programs, claims, prompt characters, and a cost upper bound."""
    programs = claims = chars = 0
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        for program in data["programs"]:
            found, _, _ = program_claims(program)
            if found:
                programs += 1
                claims += len(found)
                chars += len(prompt_for(found, program_context(program, data["school_name_en"])))
    # Measured on UT Austin's 18 programs (2026-10-30): about 2.8 characters per input token, and about
    # 25 output tokens per claim. Every input token is priced as a cache miss: an upper bound.
    tokens_in, tokens_out = int(chars / 2.8), claims * 25
    usage = {"input_tokens": tokens_in, "output_tokens": tokens_out}
    return {"programs": programs, "claims": claims, "prompt_chars": chars, "est_input_tokens": tokens_in,
            "est_output_tokens": tokens_out, "est_cost_cny": round(cost_cny(usage), 4)}


def forget(paths: list[Path], field_name: str) -> int:
    """Remove every verdict on `field_name`, so the next backfill judges it again (for a changed claim
    template: the old verdicts answered a different question). Returns how many were removed."""
    removed = 0
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        changed = False
        for program in data["programs"]:
            for name, item in _items(program):
                if name == field_name and item.get(SUMMARY_CHECK) is not None:
                    item.pop(SUMMARY_CHECK, None)
                    item.pop(SUMMARY_SHA, None)
                    removed += 1
                    changed = True
            if changed:
                program["status"] = program_status(program)
        if changed:
            _summarise(data)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return removed


def backfill(paths: list[Path], budget_cny: float, concurrency: int = 8, model_factory=None,
             log=print) -> dict:
    """Judge every program that needs it, file by file, until `budget_cny` is spent."""
    lock = threading.Lock()
    totals = {"programs": 0, "claims": 0, "blocked": 0, "not_checked": 0, "files_written": 0,
              "usage": {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0}, "models": set(),
              "stopped_at_budget": False, "stopped_at_model_unavailable": None}
    spent = [0.0]

    def make_model():
        if model_factory is not None:
            return model_factory()
        from app.agent.llm import get_chat_model

        return get_chat_model(temperature=0, max_tokens=JUDGE_MAX_TOKENS)

    model = make_model()

    def one(program: dict, school_name: str) -> bool:
        """Judge one program; True when its verdicts were recorded. A failure leaves it as it was."""
        with lock:
            if spent[0] >= budget_cny:
                totals["stopped_at_budget"] = True
                return False
            if totals["stopped_at_model_unavailable"]:
                return False
        # Judged on a copy, so a call that fails leaves no half-written verdicts behind.
        work = copy.deepcopy(program)
        for attempt in range(3):
            try:
                result = check_program(work, school_name, model)
                break
            except Exception as error:  # noqa: BLE001 - transport errors: wait and try again, then leave it unjudged
                if outage(error) == ACCOUNT:
                    # Out of money or a refused key: every further call would fail the same way.
                    with lock:
                        totals["stopped_at_model_unavailable"] = (
                            totals["stopped_at_model_unavailable"] or f"{type(error).__name__}: {str(error)[:200]}")
                    return False
                if attempt == 2:
                    log(json.dumps({"program": program.get("name"), "error": str(error)[:200]}, ensure_ascii=False))
                    return False
                time.sleep(5 * (attempt + 1))
        program.clear()
        program.update(work)
        with lock:
            spent[0] += cost_cny(result.usage)
            totals["programs"] += 1
            for key, value in result.usage.items():
                totals["usage"][key] = totals["usage"].get(key, 0) + value
            if result.model:
                totals["models"].add(result.model)
            for _, item in _items(program):
                verdict = summary_verdict(item)
                if verdict is None or item.get(SUMMARY_CHECK) is None:
                    continue
                if verdict.startswith(NOT_CHECKED):
                    totals["not_checked"] += 1
                elif verdict != OK:
                    totals["blocked"] += 1
        return True

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for path in paths:
            if spent[0] >= budget_cny:
                totals["stopped_at_budget"] = True
                break
            if totals["stopped_at_model_unavailable"]:
                break
            data = json.loads(path.read_text(encoding="utf-8"))
            todo = [p for p in data["programs"] if program_claims(p)[0] or program_claims(p)[2]]
            if not todo:
                continue
            totals["claims"] += sum(len(program_claims(p)[0]) for p in todo)
            judged = list(pool.map(lambda p: one(p, data["school_name_en"]), todo))
            if not any(judged):
                continue
            _summarise(data)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            totals["files_written"] += 1
            log(json.dumps({"school": data["school_key"], "programs": len(todo), "spent_cny": round(spent[0], 4)}))
    totals["models"] = sorted(totals["models"])
    totals["cost_cny"] = round(spent[0], 4)
    return totals


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--apply", action="store_true", help="call the model and write the verdicts")
    parser.add_argument("--budget-cny", type=float, default=30.0)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--forget", metavar="FIELD", help="remove the verdicts on one field (no model call)")
    args = parser.parse_args(argv)
    paths = args.paths or requirement_files()
    if args.forget:
        print(json.dumps({"forgotten": forget(paths, args.forget), "field": args.forget}))
        return 0
    if not args.apply:
        print(json.dumps(estimate(paths), ensure_ascii=False))
        return 0
    started = time.time()
    totals = backfill(paths, args.budget_cny, args.concurrency)
    totals["seconds"] = round(time.time() - started)
    print(json.dumps(totals, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
