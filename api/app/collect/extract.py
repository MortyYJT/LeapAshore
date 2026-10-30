"""Extract one program's admission requirements from a stored snapshot with the advisor's chat model.

    python -m app.collect.extract <school_key> <sha256> [--name "Master of X"]

The model reads the snapshot's text and returns the requirement fields of
`api/data/requirements/README.md` through a function call (structured output), each value with a
quote it says it copied from the page. Nothing it returns is trusted: every value then goes through
`app.collect.verify` against the same snapshot, and a value whose quote is not on the page, or whose
number is not inside its quote, is dropped and its reason recorded in `rejected`. A value is never
edited to make it pass. The values that pass then go to `app.collect.faithful`, which asks the same
model whether each quote on its own states what the summary says; a value it does not back stays,
marked (`summary_check`), is listed in `downgraded`, and makes the program `待人工`.

The output is one program in the requirement-file shape (`name`, `url`, `snapshot_sha256`, `fields`,
`status`). Unknown stays unknown: a field the page does not state is left out, never written as an
empty string or a zero, and nothing here writes `verified_at`.

The model is the advisor's (`CHAT_BASE_URL`, `CHAT_MODEL`, `CHAT_API_KEY`); the model name the API
reports back is kept in `model`, with the call's token usage, so a run can be costed.
"""

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field, field_validator

from app.agent.llm import get_chat_model
from app.collect.faithful import check_program
from app.collect.snapshot import SNAPSHOT_ROOT
from app.collect.verify import LIST_FIELDS, MACHINE_CHECKED, NEEDS_HUMAN, drop_failing, usable, verify
from app.config import settings

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "requirements"
# A malformed function call is asked for once more; a second malformed one is reported as an error.
MAX_ATTEMPTS = 2
TOEFL_TWO_SCALES = "TOEFL stated on 0-120 and 1-6 scales"

# A page longer than this is cut down to the lines around requirement words before it is sent. The
# quotes are still checked against the full page, so the cut can lose a value but never pass a wrong one.
MAX_INPUT_CHARS = 60_000
CONTEXT_LINES = 3
KEYWORDS = re.compile(
    r"ielts|toefl|pte|duolingo|english|language|average|gpa|wam|grade|class|honou?rs|degree|bachelor"
    r"|equivalent|china|chinese|211|985|prerequisite|require|deadline|closing|close|apply by|application"
    r"|admission|entry|intake|semester",
    re.IGNORECASE,
)


# --- What the model fills in. Every field is optional: a page that does not state it leaves it null. ---


class Academic(BaseModel):
    text: str = Field(description="The academic entry requirement in one short English sentence.")
    quote: str = Field(description="The page's own words for it, copied character for character.")


class ChinaRequirement(BaseModel):
    text: str = Field(description="The requirement for applicants with a Chinese degree, in short English.")
    quote: str = Field(description="Copied character for character; it must contain every number given below.")
    min_mark_211: float | None = Field(
        None, description="Minimum average in percent for 985/211 (or Double First-Class) graduates, only if the page states it as a percentage for Chinese degrees.")
    min_mark_other: float | None = Field(
        None, description="Minimum average in percent for graduates of other Chinese universities, same rule.")


class Ielts(BaseModel):
    overall: float | None = Field(None, description="Minimum overall IELTS band as stated, e.g. 6.5.")
    min_band: float | None = Field(None, description="Minimum in every band (or the lowest band stated), e.g. 6.0.")
    recommended: bool = Field(False, description="True when the page only recommends, prefers or suggests the score.")
    text: str | None = Field(None, description="Short English summary, when the requirement is not a plain minimum.")
    quote: str = Field(description="Copied character for character; it must contain every number given.")


class Toefl(BaseModel):
    overall: float | None = Field(None, description="Minimum TOEFL iBT total on the 0-120 scale. A 1-6 band score alone goes in text, not here.")
    min_band: float | None = Field(None, description="Minimum section score, when stated.")
    recommended: bool = Field(False, description="True when the page only recommends, prefers or suggests the score.")
    two_scales: bool = Field(False, description="True when the page states the minimum on both the 0-120 and the 1-6 scale.")
    text: str | None = Field(None, description="Short English summary, when the requirement is not a plain minimum.")
    quote: str = Field(description="Copied character for character; it must contain every number given.")


class Prerequisite(BaseModel):
    text: str = Field(description="One prerequisite in short English: a subject studied, a non-English language certificate, work experience.")
    quote: str = Field(description="Copied character for character.")


class Deadline(BaseModel):
    label: str = Field(description="Which round or intake, e.g. 'Round 1, Fall 2027'.")
    date: str = Field(description="The closing date as YYYY-MM-DD.")
    quote: str = Field(description="Copied character for character; it must state the day, the month and the year.")


class ProgramRequirements(BaseModel):
    """The admission requirements one official program page states. Leave out anything it does not state."""

    academic: list[Academic] = Field(
        default_factory=list, description="One entry per alternative academic route the page states, in page order.")
    china_requirement: ChinaRequirement | None = None
    ielts: Ielts | None = None
    toefl: Toefl | None = None
    prerequisites: list[Prerequisite] = Field(default_factory=list)
    deadlines: list[Deadline] = Field(default_factory=list)

    @field_validator("academic", "prerequisites", "deadlines", mode="before")
    @classmethod
    def _lists_accept_null_and_one_object(cls, value):
        # The prompt says "leave it null (or the list empty)": a null list is nothing stated, and one
        # object where a list was asked for is a list of one. Neither should throw the answer away.
        if value is None:
            return []
        return [value] if isinstance(value, dict) else value


PROMPT = """You extract the admission requirements of one taught master's program from the text of its \
official web page, for a database where every value is checked against the page word for word.

School: {school} ({country})
Program: {program}
Page URL: {url}

Rules:
1. Report only what this page states. If it does not state a field, leave it null (or the list empty). \
Never infer, calculate, convert or assume a value, and never use what you know about the school.
2. Every `quote` is copied character for character from the page text below: same words, same order, \
no ellipsis, no paraphrase, no added words. Keep it short (one or two sentences) but complete enough to \
contain every number the field states.
3. Numbers must appear inside their own quote (overall 6.5 needs "6.5" in the quote).
4. A score the page only recommends, prefers or suggests is still given, with recommended = true. \
Averages of admitted students are not requirements: leave them out. A score that only exempts an \
admitted student from an English course is not an admission requirement: give it as text without overall.
5. TOEFL: put the 0-120 value in overall. If the page also states a 1-6 band value, keep both in the \
quote and set two_scales = true. A 1-6 value alone goes in text, without overall.
6. china_requirement: only a requirement the page states for applicants with Chinese degrees. Fill \
min_mark_211 / min_mark_other only with a percentage the page states for Chinese degrees. A GPA on a \
4.0 scale, a German or Dutch grade, or a conversion table is never a percentage: keep it in academic text.
7. Deadlines are application closing dates. The quote itself must state the day, the month and the \
year; a year taken from a heading or another part of the page is an inference: leave that deadline out. \
Read numeric dates in the school's own order (month first in the United States, day first elsewhere).
8. prerequisites are what an applicant must have studied, hold or have done: subjects or courses, \
work experience, and language requirements other than English (German C1, TestDaF, DELF B2, TOPIK 4, \
JLPT N1), which are never translated into an IELTS score. Application documents and steps \
(statements, references, CV, transcripts, transcript evaluations, interviews, fees) are not prerequisites.
9. Quote pages in their own language; write `text` and `label` in English.
10. academic is a list: one entry per alternative route, each with its own quote. china_requirement, \
ielts and toefl are one object each: when the page lists several, give the main (first) one. Other \
English tests (PTE, MUET, Duolingo) are left out.

Page text:
<<<
{text}
>>>"""


@dataclass
class ExtractResult:
    program: dict
    rejected: list[dict] = field(default_factory=list)
    model: str | None = None
    usage: dict = field(default_factory=dict)
    truncated: bool = False
    attempts: int = 0
    # Values the model returned that the file format has no place for: not checked, not rejected.
    unused: list[dict] = field(default_factory=list)
    # Values whose quote passed but whose summary the faithfulness check did not back: kept, not usable.
    downgraded: list[dict] = field(default_factory=list)
    error: str | None = None


def page_excerpt(text: str, limit: int = MAX_INPUT_CHARS) -> tuple[str, bool]:
    """The page as sent to the model: whole when short, else the lines around requirement words."""
    if len(text) <= limit:
        return text, False
    lines = text.split("\n")
    keep = sorted({j for i, line in enumerate(lines) if KEYWORDS.search(line)
                   for j in range(max(0, i - CONTEXT_LINES), min(len(lines), i + CONTEXT_LINES + 1))})
    parts, last = [], None
    for i in keep:
        if last is not None and i != last + 1:
            parts.append("[...]")
        parts.append(lines[i])
        last = i
    excerpt = "\n".join(parts)
    return excerpt[:limit], True


def _clean(value):
    """Strings stripped; an empty string is no value."""
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


# The range a stated minimum can take, per field. A TOEFL total or section score of 6 or less is on
# the 1-6 band scale (since January 2026), which the file keeps as text, never as a number.
RANGES = {
    ("ielts", "overall"): (0, 9), ("ielts", "min_band"): (0, 9),
    ("toefl", "overall"): (6, 120), ("toefl", "min_band"): (6, 30),
    ("china_requirement", "min_mark_211"): (0, 100), ("china_requirement", "min_mark_other"): (0, 100),
}


def _number_problem(name: str, item: dict, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = item.get(key)
        if value is None:
            continue
        low, high = RANGES[(name, key)]
        if not low < value <= high:
            return f"{key}={value:g} is outside ({low:g}, {high:g}]"
    return None


def _states_a_band_score(quote: str) -> bool:
    """Whether the quote states a score between 1 and 6, the range of the TOEFL band scale."""
    return any(1 <= float(number) <= 6 for number in re.findall(r"(?<![\d.])\d+(?:\.\d+)?(?!\.?\d)", quote))


def to_fields(parsed: ProgramRequirements) -> tuple[dict, list[dict], list[dict]]:
    """The model's answer in the requirement-file shape, the items refused before the quote check, and
    the academic routes after the first, which the file's single `academic` field has no room for.

    Null and empty values are left out rather than written. An item that cannot be a stated value (no
    quote, a zero or negative mark, a date that is not a date, a score with neither a number nor a
    text) is refused whole: refusing it is a reason recorded, never an edit.
    """
    fields: dict = {}
    rejected: list[dict] = []
    unused: list[dict] = []

    def refuse(name: str, item: dict, reason: str) -> None:
        rejected.append({"field": name, "value": item, "reason": reason})

    def single(name: str, item: dict, numbers: tuple[str, ...] = ()) -> None:
        item = {key: _clean(value) for key, value in item.items()}
        item = {key: value for key, value in item.items() if value is not None and value is not False}
        if not item.get("quote"):
            return refuse(name, item, "no quote")
        if problem := _number_problem(name, item, numbers):
            return refuse(name, item, problem)
        if name in ("ielts", "toefl") and not any(item.get(key) is not None for key in (*numbers, "text")):
            return refuse(name, item, "no value: neither a number nor a text")
        if name in LIST_FIELDS:
            if name == "deadlines":
                try:
                    item["date"] = date.fromisoformat(item.get("date") or "").isoformat()
                except ValueError:
                    return refuse(name, item, f"date {item.get('date')!r} is not an ISO date")
            fields.setdefault(name, []).append(item)
        else:
            fields[name] = item

    # The model is asked for a list because, told to give one object, it wrote a second route after
    # the first and broke the JSON (8 of 95 pages, 2026-10-30). The file holds one route: the first.
    for route in parsed.academic:
        if "academic" not in fields:
            single("academic", route.model_dump())
        else:
            unused.append({"field": "academic", "value": route.model_dump(),
                           "reason": "another academic route; the requirement file holds one"})
    if parsed.china_requirement:
        single("china_requirement", parsed.china_requirement.model_dump(), ("min_mark_211", "min_mark_other"))
    if parsed.ielts:
        single("ielts", parsed.ielts.model_dump(), ("overall", "min_band"))
    if parsed.toefl:
        toefl = parsed.toefl.model_dump()
        # The note is a claim about the quote, so it is written only when the quote also states a
        # number on the 1-6 scale; otherwise the model's flag is not repeated.
        if toefl.pop("two_scales") and _states_a_band_score(toefl.get("quote") or ""):
            toefl["scale_note"] = TOEFL_TWO_SCALES
        single("toefl", toefl, ("overall", "min_band"))
    for item in parsed.prerequisites:
        single("prerequisites", item.model_dump())
    for item in parsed.deadlines:
        single("deadlines", item.model_dump())
    return fields, rejected, unused


def check_fields(program: dict, school_key: str, school_name: str, country: str | None,
                 root: Path = SNAPSHOT_ROOT) -> tuple[dict, list[dict]]:
    """Run `verify` on one program; drop the values that fail and say why. Returns (program, rejected)."""
    data = {"school_key": school_key, "school_name_en": school_name, "country": country, "programs": [program]}
    checked = verify(data, root)["programs"][0]
    rejected = []
    for name, value in checked["fields"].items():
        for item in value if name in LIST_FIELDS else [value]:
            if item["check"] != "ok":
                rejected.append({"field": name, "value": {k: v for k, v in item.items() if k != "check"},
                                 "reason": item["check"]})
    data = verify(drop_failing(data), root)
    return data["programs"][0], rejected


def _usage(raw) -> dict:
    meta = getattr(raw, "usage_metadata", None) or {}
    details = meta.get("input_token_details") or {}
    return {
        "input_tokens": meta.get("input_tokens", 0),
        "output_tokens": meta.get("output_tokens", 0),
        "cache_read_tokens": details.get("cache_read", 0) or 0,
    }


def extract_snapshot(school_key: str, sha256: str, *, program_name: str, school_name: str,
                     country: str | None, url: str | None = None, model: BaseChatModel | None = None,
                     judge_model: BaseChatModel | None = None, root: Path = SNAPSHOT_ROOT) -> ExtractResult:
    """Extract, then check, the requirements one snapshot states. `model` defaults to the advisor's;
    `judge_model`, which checks the summaries, defaults to `model`."""
    folder = root / school_key
    text = (folder / f"{sha256}.txt").read_text(encoding="utf-8")
    meta_path = folder / f"{sha256}.json"
    if url is None and meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        url = meta.get("final_url") or meta.get("requested_url")
    if not url:
        # Every value cites its page; a snapshot with no recorded address cannot be cited.
        raise ValueError(f"no URL for snapshot {sha256}: pass url=")
    excerpt, truncated = page_excerpt(text)
    program = {"name": program_name, "url": url, "snapshot_sha256": sha256, "fields": {}}

    if model is None:
        model = get_chat_model(temperature=0, max_tokens=settings.extract_max_tokens)
    structured = model.with_structured_output(ProgramRequirements, method="function_calling", include_raw=True)
    prompt = PROMPT.format(school=school_name, country=country or "unknown", program=program_name,
                           url=url, text=excerpt)
    result = ExtractResult(program=program, truncated=truncated)
    answer = None
    for _ in range(MAX_ATTEMPTS):
        answer = structured.invoke(prompt)
        raw = answer["raw"]
        result.attempts += 1
        result.model = (raw.response_metadata or {}).get("model_name") or result.model
        for key, value in _usage(raw).items():
            result.usage[key] = result.usage.get(key, 0) + value
        if not answer.get("parsing_error") and answer.get("parsed") is not None:
            break
        # A malformed function call (invalid JSON, a cut-off answer) says nothing about the page.
        finish = (raw.response_metadata or {}).get("finish_reason")
        why = answer.get("parsing_error") or next(
            (call.get("error") for call in getattr(raw, "invalid_tool_calls", []) or []), None) or "no function call"
        result.error = f"no usable answer (finish_reason={finish}): {str(why)[:300]}"
    else:
        program["status"] = NEEDS_HUMAN
        return result
    result.error = None

    fields, refused, result.unused = to_fields(answer["parsed"])
    program["fields"] = fields
    checked, failed = check_fields(program, school_key, school_name, country, root)
    judgement = check_program(checked, school_name, judge_model or model)
    for key, value in judgement.usage.items():
        result.usage[key] = result.usage.get(key, 0) + value
    for name, value in checked["fields"].items():
        for item in value if name in LIST_FIELDS else [value]:
            if item.get("check") == "ok" and not usable(item):
                result.downgraded.append({"field": name, "value": {k: v for k, v in item.items() if k != "check"},
                                          "reason": item["summary_check"]})
    result.program = checked
    result.rejected = refused + failed
    return result


def _school(school_key: str) -> dict:
    """The school's name and country, from `_schools.json` or its requirement file."""
    for row in json.loads((DATA_DIR / "_schools.json").read_text(encoding="utf-8")):
        if row["school_key"] == school_key:
            return {"name": row["name_en"], "country": row.get("country")}
    path = DATA_DIR / f"{school_key}.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        return {"name": data["school_name_en"], "country": data.get("country")}
    raise SystemExit(f"unknown school {school_key!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("school_key")
    parser.add_argument("sha256")
    parser.add_argument("--name", help="program name (default: the name the school's file gives this snapshot)")
    args = parser.parse_args(argv)
    school = _school(args.school_key)
    name = args.name
    if name is None:
        path = DATA_DIR / f"{args.school_key}.json"
        programs = json.loads(path.read_text(encoding="utf-8"))["programs"] if path.exists() else []
        name = next((p["name"] for p in programs if p["snapshot_sha256"] == args.sha256), None)
        if name is None:
            parser.error("this snapshot is not in the school's file; pass --name")
    result = extract_snapshot(args.school_key, args.sha256, program_name=name,
                              school_name=school["name"], country=school["country"])
    print(json.dumps(asdict(result), ensure_ascii=False, indent=1))
    return 0 if result.error is None else 1


if __name__ == "__main__":
    sys.exit(main())
