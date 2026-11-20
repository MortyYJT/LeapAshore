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
3. A `count` is stated in the quote, as a number standing on its own (not part of `1,000`, `2.5`,
   `2nd` or `A4`) or as an English number word.
4. A number written in `note`, in digits or as an English number word, is in the quote too, so a
   note cannot carry a figure the page does not.
5. An `other` entry has a `note`, because the type alone does not say what the page asks for.
6. The quote has words in it: at least `MIN_QUOTE` characters once spacing and invisible characters
   are folded away. A one-character quote is "found" on any page and proves nothing.

`note` is the extractor's own summary and is not otherwise checked: no model judges it yet. The
quote check is a substring check, so it cannot tell "references are required" from the same words
inside "no references are required"; that is what the labelled set measures.

A block can also be withdrawn (`"withdrawn": "<why>"`): the reading is taken back, and the program is
not extracted again.

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
MIN_QUOTE = 10
MAX_QUOTE = 1000
MAX_NOTE = 300
ITEM_KEYS = ("type", "count", "note", "quote", "source_sha256")
SHA = re.compile(r"^[0-9a-f]{64}$")

NUMBER_WORDS = (
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
    "nineteen", "twenty",
)
_WORD = "|".join(sorted(NUMBER_WORDS, key=len, reverse=True))
# A figure written in digits: `500`, `1,000`, `2.5`. Not the digits inside a word (`A4`, `2nd`).
_FIGURE = re.compile(r"(?<![\w.,])\d+(?:[.,]\d+)*(?![\w]|[.,]\d)")
_NUMBER_WORD = re.compile(rf"\b({_WORD})\b", re.IGNORECASE)
# A date written in digits (`3/1/2027`, `2027-01-15`): its parts are not counts of anything.
_NUMERIC_DATE = re.compile(r"(?<!\d)\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}(?!\d)")


def _figures(text: str) -> set[str]:
    """Every number a text states, as plain digits: `1,000` is `1000`, `two` is `2`, `2.5` is `2.5`.

    A number that is part of something else is not stated on its own: the `1` of `1,000`, the `2` of
    `2nd`, the `4` of `A4`, the day of `3/1/2027`. Hyphenated forms count (`2-page`, `two-page`)."""
    text = _NUMERIC_DATE.sub(" ", text)
    found = {match.group(0).replace(",", "") for match in _FIGURE.finditer(text)}
    found |= {str(NUMBER_WORDS.index(match.group(1).lower())) for match in _NUMBER_WORD.finditer(text)}
    return found


def _states_number(quote: str, value: int) -> bool:
    """Whether the quote writes this whole number on its own, in digits or as an English word."""
    return str(value) in _figures(quote)


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
    if not isinstance(quote, str) or not normalize(quote):
        return "no quote"
    if len(normalize(quote)) < MIN_QUOTE:
        return f"quote is shorter than {MIN_QUOTE} characters: quote the sentence that asks for the material"
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
    stated = _figures(quote)
    for figure in sorted(_figures(item.get("note") or "") - stated, key=lambda number: (len(number), number)):
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
    if block is None or block.get("withdrawn") or not isinstance(block.get("items"), list):
        return False
    items = block["items"]
    if any(passed(item) for item in items):
        return True
    return not items and not block.get("rejected")


def says_not_extracted(program: dict) -> bool:
    """Whether the file takes a position and it is "not extracted": a block that was withdrawn, or one
    left with refusals only. Different from a file with no block, which says nothing about materials
    (it may simply be older than the material pass)."""
    return block_of(program) is not None and not extracted(program)


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


def label(kind: str, count: int | None = None, note: str | None = None) -> str:
    """`推荐信 2 封`, `简历`: the words for a requirement, with its count when the page states one. An
    `other` entry is named by its note, which is the only thing that says what it is."""
    name = (note or "").strip() if kind == OTHER and (note or "").strip() else TYPE_LABELS.get(kind, kind)
    return name if count is None else f"{name} {count} {COUNT_UNITS.get(kind, DEFAULT_UNIT)}"


def display_names(entries: list[tuple[str, int | None, str | None, str]]) -> list[str]:
    """A name for each `(type, count, note, quote)` that tells it from the others in the same list.

    Two entries that would read alike (two statements, two `other` documents with one note) get their
    note, or else the start of their quote, in brackets: a confirm card must say which one it is about."""
    names = [label(kind, count, note) for kind, count, note, _quote in entries]
    out = []
    for name, (kind, _count, note, quote) in zip(names, entries):
        if names.count(name) > 1:
            more = (note or "").strip() if kind != OTHER else ""
            name = f"{name}（{more or quote.strip()[:40]}）"
        out.append(name)
    return out
