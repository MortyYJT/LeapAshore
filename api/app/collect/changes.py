"""Which requirement of a page changed between two collections (openspec/changes/archive/2026-10-30-collect-queue, D7).

Only values whose quote passed `verify` (`check == "ok"`) are compared, and what is compared is what
the page states, not how the model worded or cut it:

- A number (an IELTS/TOEFL minimum, a Chinese-degree mark) or a deadline date is compared as a value.
- Anything else (an academic requirement, a prerequisite, a text-only English requirement) has changed
  only when the page no longer states the old quote. The model quotes a different span of the same
  sentence from one run to the next; that is not a change.
- A value is `removed` only when its quote is no longer on the new page, and `added` only when its
  quote was not on the old page. A value the model simply missed this time is neither.

The page texts are normalised snapshot texts. The new one is always known; the old one is known where
its snapshot is kept, and otherwise the quotes are compared with each other instead.
"""

from app.collect.text import normalize
from app.collect.verify import FIELD_NAMES, LIST_FIELDS, NUMERIC_KEYS, SUMMARY_CHECK, SUMMARY_SHA


def _passed(item) -> bool:
    return isinstance(item, dict) and item.get("check") == "ok"


def _public(item: dict) -> dict:
    """The item as it is recorded in a change row: without the check bookkeeping."""
    return {key: value for key, value in item.items() if key not in ("check", SUMMARY_CHECK, SUMMARY_SHA)}


def _quote(item: dict) -> str:
    return normalize(item.get("quote") or "")


def _numbers(name: str, item: dict) -> tuple | None:
    if name == "deadlines":
        return (item.get("date"),)
    values = tuple(item.get(key) for key in NUMERIC_KEYS.get(name, ()))
    if not any(value is not None for value in values):
        return None
    return values + ((bool(item.get("recommended")),) if name in ("ielts", "toefl") else ())


def _stated(item: dict, text: str | None, quotes: list[str]) -> bool:
    """Whether the other side still states this item: its quote is on that page, or (without the page)
    it and one of that side's quotes contain each other."""
    quote = _quote(item)
    if not quote:
        return False
    if text is not None:
        return quote in text
    return any(quote in other or other in quote for other in quotes if other)


def has_verified_value(fields: dict | None) -> bool:
    for name, field in (fields or {}).items():
        for item in field if name in LIST_FIELDS else [field]:
            if _passed(item):
                return True
    return False


def diff_fields(old: dict | None, new: dict | None, old_text: str | None = None,
                new_text: str | None = None) -> list[dict]:
    """One entry per change: `{"field", "kind", "old", "new"}`, kind `added` / `removed` / `changed`."""
    old, new = old or {}, new or {}
    changes = []
    for name in FIELD_NAMES:
        before = [i for i in (old.get(name) or [] if name in LIST_FIELDS else [old.get(name)]) if _passed(i)]
        after = [i for i in (new.get(name) or [] if name in LIST_FIELDS else [new.get(name)]) if _passed(i)]
        old_quotes, new_quotes = [_quote(i) for i in before], [_quote(i) for i in after]
        if name not in LIST_FIELDS and before and after:
            a, b = before[0], after[0]
            if _numbers(name, a) is not None or _numbers(name, b) is not None:
                differs = _numbers(name, a) != _numbers(name, b)
            else:
                differs = not _stated(a, new_text, new_quotes)
            if differs:
                changes.append({"field": name, "kind": "changed", "old": _public(a), "new": _public(b)})
            continue
        if name == "deadlines":
            old_dates = {i.get("date") for i in before}
            new_dates = {i.get("date") for i in after}
            gone = [i for i in before if i.get("date") not in new_dates and not _stated(i, new_text, new_quotes)]
            came = [i for i in after if i.get("date") not in old_dates and not _stated(i, old_text, old_quotes)]
        else:
            gone = [i for i in before if not _stated(i, new_text, new_quotes)]
            came = [i for i in after if not _stated(i, old_text, old_quotes)]
        changes += [{"field": name, "kind": "removed", "old": _public(i), "new": None} for i in gone]
        changes += [{"field": name, "kind": "added", "old": None, "new": _public(i)} for i in came]
    return changes
