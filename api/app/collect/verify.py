"""Check a school's requirement file against the snapshots it cites.

    python -m app.collect.verify api/data/requirements/<school-key>.json [--write]

A field passes when (1) its `quote` appears verbatim, after `normalize`, in the text of the snapshot
it cites, and (2) every number the field states (a mark, an IELTS score, a deadline's day) appears
inside that quote. A program is `机器核对` when it reports at least one field and every reported
field passes; otherwise it is `待人工` and goes to the human queue. With `--write` the result is
stored back into the file; without it the file is only checked.
"""

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

from app.collect.snapshot import SNAPSHOT_ROOT
from app.collect.text import normalize

MACHINE_CHECKED = "机器核对"
NEEDS_HUMAN = "待人工"
SHA = re.compile(r"^[0-9a-f]{64}$")
FIELD_NAMES = ("academic", "china_requirement", "ielts", "toefl", "prerequisites", "deadlines")
LIST_FIELDS = ("prerequisites", "deadlines")
NUMERIC_KEYS = {
    "china_requirement": ("min_mark_211", "min_mark_other"),
    "ielts": ("overall", "min_band"),
    "toefl": ("overall", "min_band"),
}


class SchemaError(ValueError):
    pass


def _number_forms(value: float) -> set[str]:
    """The ways a stated number can be written: 6.5, 6.50; 65, 65.0, 65%."""
    forms = {f"{value:g}"}
    if float(value).is_integer():
        forms |= {str(int(value)), f"{int(value)}.0"}
    else:
        forms.add(f"{value:.2f}")
    return forms


MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september",
          "october", "november", "december")


def _mentions_month(quote: str, month: int) -> bool:
    """The month by name or abbreviation, as 5月, or inside a numeric date (2026-05-31, 31/05/2026)."""
    low = quote.lower()
    name = MONTHS[month - 1]
    if re.search(rf"\b({name}|{name[:3]})\b", low) or re.search(rf"(?<!\d){month}\s*月", quote):
        return True
    return bool(re.search(rf"\d{{4}}[-/.]0?{month}[-/.]\d{{1,2}}|\d{{1,2}}[-/.]0?{month}[-/.]\d{{2,4}}", quote))


def _contains_number(quote: str, value: float) -> bool:
    # Not inside a longer number either way: 6 must not match the 6 of 6.5, nor 5 the 5 of 65.
    return any(re.search(rf"(?<![\d.]){re.escape(form)}(?![\d]|\.\d)", quote) for form in _number_forms(value))


NUMERIC_DATES = re.compile(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})|(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})")


# Countries whose official pages write a numeric date month first (12/01/2026 = 1 December).
MONTH_FIRST = {"United States", "US", "USA", "United States of America", "Philippines"}
# Countries whose pages use both orders: a numeric date counts only when both readings agree.
EITHER_ORDER = {"Canada"}


def _numeric_dates(quote: str, month_first: bool = False) -> list[date]:
    found = []
    for match in NUMERIC_DATES.finditer(quote):
        try:
            if match.group(1):
                found.append(date(int(match.group(1)), int(match.group(2)), int(match.group(3))))
            elif month_first:
                found.append(date(int(match.group(6)), int(match.group(4)), int(match.group(5))))
            else:  # day/month/year, the order everywhere in scope except the US
                found.append(date(int(match.group(6)), int(match.group(5)), int(match.group(4))))
        except ValueError:
            continue
    return found


def validate(data: dict) -> None:
    """Raise SchemaError when the file is not in the agreed shape."""
    for key in ("school_key", "school_name_en", "programs"):
        if key not in data:
            raise SchemaError(f"missing top-level key {key!r}")
    if not isinstance(data["programs"], list):
        raise SchemaError("programs must be a list")
    for i, program in enumerate(data["programs"]):
        where = f"programs[{i}]"
        for key in ("name", "url", "snapshot_sha256"):
            if not program.get(key):
                raise SchemaError(f"{where} missing {key!r}")
        # A page that states no requirement is still a program: it reports nothing and is queued.
        if not isinstance(program.get("fields"), dict):
            raise SchemaError(f"{where}.fields must be an object")
        if not SHA.match(program["snapshot_sha256"]):
            raise SchemaError(f"{where}.snapshot_sha256 is not a sha256")
        fields = program["fields"]
        unknown = set(fields) - set(FIELD_NAMES)
        if unknown:
            raise SchemaError(f"{where} has unknown fields {sorted(unknown)}")
        for name, field in fields.items():
            items = field if name in LIST_FIELDS else [field]
            if name in LIST_FIELDS and not isinstance(field, list):
                raise SchemaError(f"{where}.{name} must be a list")
            for item in items:
                if not isinstance(item, dict) or not str(item.get("quote", "")).strip():
                    raise SchemaError(f"{where}.{name} needs a non-empty quote")
                if "source_sha256" in item and not SHA.match(item["source_sha256"]):
                    raise SchemaError(f"{where}.{name}.source_sha256 is not a sha256")
                if name == "deadlines":
                    try:
                        date.fromisoformat(item["date"])
                    except (KeyError, TypeError, ValueError) as error:
                        raise SchemaError(f"{where}.deadlines needs an ISO date") from error
                if "recommended" in item and not isinstance(item["recommended"], bool):
                    raise SchemaError(f"{where}.{name}.recommended must be true or false")
                for key in NUMERIC_KEYS.get(name, ()):
                    if item.get(key) is not None and not isinstance(item[key], (int, float)):
                        raise SchemaError(f"{where}.{name}.{key} must be a number")


def check_item(name: str, item: dict, text: str, month_first: bool = False, either_order: bool = False) -> list[str]:
    """The reasons this item fails; empty when it passes."""
    problems = []
    quote = item["quote"]
    if normalize(quote) not in text:
        problems.append("quote not found in snapshot")
    for key in NUMERIC_KEYS.get(name, ()):
        value = item.get(key)
        if value is not None and not _contains_number(quote, value):
            problems.append(f"{key}={value:g} not in quote")
    if name == "deadlines":
        when = date.fromisoformat(item["date"])
        numeric = _numeric_dates(quote, month_first)
        if either_order:
            # Keep only the dates that read one way: the other order is invalid, or gives the same day.
            numeric = []
            for match in NUMERIC_DATES.finditer(quote):
                readings = set(_numeric_dates(match.group(0), True)) | set(_numeric_dates(match.group(0), False))
                if len(readings) == 1:
                    numeric += readings
            if NUMERIC_DATES.search(quote) and when not in numeric:
                problems.append(f"deadline {when.isoformat()}: the numeric date in the quote reads two ways")
                return problems
        if numeric:
            # A quote that writes the date in digits has to write this date.
            if when not in numeric:
                problems.append(f"deadline {when.isoformat()} is not the date the quote states")
            return problems
        if not re.search(rf"(?<![\d.\-/])0?{when.day}(?![\d\-/])", quote):
            problems.append(f"deadline day {when.day} not in quote")
        # The year and month have to be stated too: a year read off another part of the page
        # ("31 May of the previous year") is an inference, not a quote.
        if str(when.year) not in quote:
            problems.append(f"deadline year {when.year} not in quote")
        if not _mentions_month(quote, when.month):
            problems.append(f"deadline month {when.month} not in quote")
    return problems


def verify(data: dict, root: Path = SNAPSHOT_ROOT) -> dict:
    """Return a copy of `data` with each item's `check` and each program's `status` filled in."""
    validate(data)
    school = data["school_key"]
    cache: dict[str, str | None] = {}

    def snapshot_text(sha: str) -> str | None:
        if sha not in cache:
            path = root / school / f"{sha}.txt"
            cache[sha] = normalize(path.read_text(encoding="utf-8")) if path.exists() else None
        return cache[sha]

    month_first = data.get("country") in MONTH_FIRST
    either_order = data.get("country") in EITHER_ORDER
    summary = {"programs": 0, MACHINE_CHECKED: 0, NEEDS_HUMAN: 0}
    for program in data["programs"]:
        all_ok, reported = True, 0
        for name, field in program["fields"].items():
            for item in field if name in LIST_FIELDS else [field]:
                reported += 1
                text = snapshot_text(item.get("source_sha256") or program["snapshot_sha256"])
                if item.get("source_sha256"):
                    # Record which page the quote is on, so an import can cite that page, not the
                    # programme page (the snapshot store itself is not published).
                    meta = root / school / f"{item['source_sha256']}.json"
                    if meta.exists():
                        item["source_url"] = json.loads(meta.read_text(encoding="utf-8")).get("final_url") or item.get("source_url")
                problems = ["snapshot missing"] if text is None else check_item(name, item, text, month_first, either_order)
                item["check"] = "ok" if not problems else "; ".join(problems)
                all_ok = all_ok and not problems
        program["status"] = MACHINE_CHECKED if reported and all_ok else NEEDS_HUMAN
        summary["programs"] += 1
        summary[program["status"]] += 1
    data["verification"] = summary
    return data


def drop_failing(data: dict) -> dict:
    """Remove the values that failed their check, keeping the ones that passed."""
    for program in data["programs"]:
        kept = {}
        for name, field in program["fields"].items():
            if name in LIST_FIELDS:
                items = [item for item in field if item.get("check") == "ok"]
                if items:
                    kept[name] = items
            elif field.get("check") == "ok":
                kept[name] = field
        program["fields"] = kept
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("path", type=Path)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--drop-failing", action="store_true",
                        help="remove every value whose check fails (never edit one to make it pass)")
    args = parser.parse_args(argv)
    data = json.loads(args.path.read_text(encoding="utf-8"))
    try:
        result = verify(data)
        if args.drop_failing:
            result = verify(drop_failing(result))
    except SchemaError as error:
        print(json.dumps({"schema_error": str(error)}, ensure_ascii=False))
        return 3
    if args.write:
        args.path.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    failing = [
        {"program": p["name"], "problems": [f"{n}: {i['check']}" for n, f in p["fields"].items()
                                            for i in (f if n in LIST_FIELDS else [f]) if i["check"] != "ok"]}
        for p in result["programs"] if p["status"] != MACHINE_CHECKED
    ]
    print(json.dumps({"summary": result["verification"], "failing": failing[:20]}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
