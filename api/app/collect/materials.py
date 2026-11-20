"""The application materials a program's official page asks for (`docs/product/PRD-multi-device.md`, 3.7).

A program in a requirement file may carry a `materials` block beside its `fields`:

    "materials": {
      "snapshot_sha256": "<the snapshot the extractor read>",
      "extractor": "<who read it>",
      "extracted_at": "2026-11-21",
      "rejected": 0,
      "items": [
        {"type": "recommendation", "count": 2, "note": "academic referees",
         "quote": "<verbatim from the snapshot>", "check": "ok"}
      ]
    }

- No block: nobody has read the page for materials yet. That is "not extracted", never "nothing asked".
- A block with no items and `rejected` 0: the page was read and lists no material.
- A block whose every proposed entry was rejected says nothing either way, and counts as not extracted.

An entry is kept or refused whole; nothing here edits a value. The rules:

1. `type` is one of `MATERIAL_TYPES`.
2. `quote` is verbatim in the snapshot it cites (`source_sha256`, else the block's snapshot).
3. A `count` is stated in the quote, as digits or as an English number word.
4. A number written in `note` is in the quote too, so a note cannot carry a figure the page does not.
5. An `other` entry has a `note`, because the type alone does not say what the page asks for.

`note` is the extractor's own summary and is not otherwise checked: no model judges it yet.

This module has no database and no model in it. `app.collect.verify` runs these checks on a file,
`app.collect.importer` writes the entries that passed, and `app.collect.material_extract` is the
command line an extracting agent uses.
"""

import hashlib
import re

from app.collect.text import normalize

MATERIAL_TYPES = (
    "cv",
    "personal_statement",
    "recommendation",
    "transcript",
    "language_score",
    "test_score",
    "portfolio",
    "writing_sample",
    "other",
)
OTHER = "other"

# The words the interface and the advisor use for a type, and the measure word of its count.
TYPE_LABELS = {
    "cv": "简历",
    "personal_statement": "个人陈述",
    "recommendation": "推荐信",
    "transcript": "成绩单",
    "language_score": "语言成绩",
    "test_score": "标化考试成绩",
    "portfolio": "作品集",
    "writing_sample": "写作样本",
    "other": "其他材料",
}
COUNT_UNITS = {"recommendation": "封", "personal_statement": "篇", "writing_sample": "篇"}
DEFAULT_UNIT = "份"

MAX_COUNT = 20
MAX_QUOTE = 1000
MAX_NOTE = 300
ITEM_KEYS = ("type", "count", "note", "quote", "source_sha256")
SHA = re.compile(r"^[0-9a-f]{64}$")

NUMBER_WORDS = (
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
    "nineteen", "twenty",
)
_DIGITS = re.compile(r"(?<![\d.,])\d+(?:[.,]\d+)*(?![\d])")


def _states_number(quote: str, value: int) -> bool:
    """Whether the quote writes this whole number, in digits (not inside a longer number) or as a word."""
    if re.search(rf"(?<![\d.]){value}(?![\d]|\.\d)", quote):
        return True
    return value < len(NUMBER_WORDS) and bool(re.search(rf"\b{NUMBER_WORDS[value]}\b", quote, re.IGNORECASE))


def _note_numbers(note: str) -> list[str]:
    """The figures a note writes in digits, each without its thousands separators."""
    return [match.group(0).replace(",", "") for match in _DIGITS.finditer(note)]


def _quote_has_figure(quote: str, figure: str) -> bool:
    plain = quote.replace(",", "")
    if re.search(rf"(?<![\d.]){re.escape(figure)}(?![\d]|\.\d)", plain):
        return True
    return figure.isdigit() and int(figure) < len(NUMBER_WORDS) and bool(
        re.search(rf"\b{NUMBER_WORDS[int(figure)]}\b", quote, re.IGNORECASE)
    )


def shape_problem(item) -> str | None:
    """Why this entry is not a material entry at all; None when its shape is right.

    The check before any snapshot is read: a wrong type, a missing quote, a count that is not a small
    whole number. It never repairs anything.
    """
    if not isinstance(item, dict):
        return "not an object"
    if item.get("type") not in MATERIAL_TYPES:
        return f"type {item.get('type')!r} is not one of {', '.join(MATERIAL_TYPES)}"
    quote = item.get("quote")
    if not isinstance(quote, str) or not quote.strip():
        return "no quote"
    if len(quote) > MAX_QUOTE:
        return f"quote is longer than {MAX_QUOTE} characters: quote the sentence that asks for the material"
    count = item.get("count")
    if count is not None:
        if isinstance(count, bool) or not isinstance(count, int):
            return "count must be a whole number, or left out"
        if not 1 <= count <= MAX_COUNT:
            return f"count={count} is outside 1..{MAX_COUNT}"
    note = item.get("note")
    if note is not None:
        if not isinstance(note, str):
            return "note must be text, or left out"
        if len(note) > MAX_NOTE:
            return f"note is longer than {MAX_NOTE} characters"
    if item["type"] == OTHER and not (note or "").strip():
        return "an `other` entry needs a note that names the material"
    source = item.get("source_sha256")
    if source is not None and not (isinstance(source, str) and SHA.match(source)):
        return "source_sha256 is not a sha256"
    return None


def check_material(item: dict, text: str | None) -> list[str]:
    """The reasons this entry fails against the normalised text of its snapshot; empty when it passes."""
    problem = shape_problem(item)
    if problem:
        return [problem]
    if text is None:
        return ["snapshot missing"]
    problems = []
    quote = item["quote"]
    if normalize(quote) not in text:
        problems.append("quote not found in snapshot")
    count = item.get("count")
    if count is not None and not _states_number(quote, count):
        problems.append(f"count={count} not in quote")
    for figure in _note_numbers(item.get("note") or ""):
        if not _quote_has_figure(quote, figure):
            problems.append(f"note states {figure}, which is not in the quote")
    return problems


def clean(item: dict) -> dict:
    """The entry as the file keeps it: known keys in a fixed order, strings stripped, empty values left
    out. Nothing is corrected: a value that is wrong stays wrong and is refused by the checks."""
    out = {}
    for key in ITEM_KEYS:
        value = item.get(key)
        if isinstance(value, str):
            value = value.strip()
        if value is None or value == "":
            continue
        out[key] = value
    return out


def passed(item) -> bool:
    return isinstance(item, dict) and item.get("check") == "ok"


def block_of(program: dict) -> dict | None:
    block = program.get("materials")
    return block if isinstance(block, dict) else None


def extracted(program: dict) -> bool:
    """Whether the file says what this program's page asks for: entries that passed, or a page that was
    read and lists none. A block left with nothing but refusals does not."""
    block = block_of(program)
    if block is None:
        return False
    items = block.get("items") or []
    if any(passed(item) for item in items):
        return True
    return not items and not block.get("rejected")


def accepted_items(program: dict) -> list[dict]:
    """The entries the catalogue may show, in the file's order."""
    block = block_of(program)
    if block is None or not extracted(program):
        return []
    return [item for item in block.get("items") or [] if passed(item)]


def keys_for(items: list[dict]) -> list[str]:
    """One key per entry, the name a tick is stored under: the type, then `type-2`, `type-3` for
    further entries of the same type, in order."""
    seen: dict[str, int] = {}
    keys = []
    for item in items:
        seen[item["type"]] = seen.get(item["type"], 0) + 1
        keys.append(item["type"] if seen[item["type"]] == 1 else f"{item['type']}-{seen[item['type']]}")
    return keys


def digest(kind: str, count: int | None, note: str | None, quote: str) -> str:
    """What a tick was given for: the requirement as stated. A tick whose digest no longer matches the
    stored entry was given for an earlier wording, and no longer counts."""
    stated = f"{kind}|{'' if count is None else count}|{(note or '').strip()}|{normalize(quote)}"
    return hashlib.sha256(stated.encode()).hexdigest()[:12]


def label(kind: str, count: int | None = None) -> str:
    """`推荐信 2 封`, `简历`: the words for a requirement, with its count when the page states one."""
    name = TYPE_LABELS.get(kind, kind)
    return name if count is None else f"{name} {count} {COUNT_UNITS.get(kind, DEFAULT_UNIT)}"
