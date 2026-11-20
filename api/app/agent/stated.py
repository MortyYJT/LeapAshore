"""What the applicant wrote in the conversation, read by rule and not by the model.

The advisor never invents a deadline (CLAUDE.md, red lines). A date it proposes for an application is
either the catalogue's, looked up on the server, or one the applicant stated. For the second kind the
model's word is not taken: the tool reads the applicant's own messages here and writes the date only
when it finds it in them. A date the model wrote, or one a tool returned, is not the applicant's.

What counts as a written date is deliberately narrow, because a wrong match would let a made-up date
through as "stated":

- a full date: `2027-01-15`, `2027/1/15`, `2027.1.15`, `2027年1月15日`;
- a month and a day in Chinese, `1月15日`, `1 月 15 号`, `十二月一日`, optionally after 今年, 明年 or 后年;
- a month by its English name with a day, `Jan 15`, `15 January 2027`.

A month and a day without a year mean the next such day, today included. `1/15` and `1.15` are not
read (a day and a month in either order, or a mark), nor is anything relative (下周五, 月底).
"""

import re
import unicodedata
from collections.abc import Iterable
from datetime import date, datetime
from zoneinfo import ZoneInfo

from langchain_core.messages import HumanMessage

_CN_DIGITS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_NUMBER = r"[一二两三四五六七八九十]{1,3}"
_NUMBER = rf"(?:\d{{1,2}}|{_CN_NUMBER})"

_FULL = re.compile(r"(?<!\d)(20\d\d)\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})(?!\d)\s*[日号]?")
_MONTH_DAY = re.compile(rf"(今年|明年|后年)?\s*(?<![\d一二两三四五六七八九十])({_NUMBER})\s*月\s*({_NUMBER})\s*[日号]")
_MONTHS = {
    name: number
    for number, names in enumerate(
        (
            ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",),
            ("jun", "june"), ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"),
            ("oct", "october"), ("nov", "november"), ("dec", "december"),
        ),
        start=1,
    )
    for name in names
}
_MONTH_NAME = "|".join(sorted(_MONTHS, key=len, reverse=True))
_DAY = r"(\d{1,2})(?!\d)(?:st|nd|rd|th)?"
_YEAR = r"(?:\s*,?\s*(20\d\d)(?!\d))?"
_NAME_FIRST = re.compile(rf"(?<![a-z])({_MONTH_NAME})\b\.?\s*{_DAY}{_YEAR}", re.IGNORECASE)
_DAY_FIRST = re.compile(rf"(?<!\d){_DAY}\s+({_MONTH_NAME})\b\.?{_YEAR}", re.IGNORECASE)
_YEAR_WORDS = {"今年": 0, "明年": 1, "后年": 2}


def applicant_texts(state) -> list[str]:
    """The applicant's own messages in this conversation, oldest first."""
    messages = (state or {}).get("messages") or []
    return [m.content for m in messages if isinstance(m, HumanMessage) and isinstance(m.content, str)]


def _number(text: str) -> int | None:
    if text.isdigit():
        return int(text)
    if text == "十":
        return 10
    if "十" in text:
        tens, _, ones = text.partition("十")
        if (tens and tens not in _CN_DIGITS) or (ones and ones not in _CN_DIGITS):
            return None
        return (_CN_DIGITS[tens] if tens else 1) * 10 + (_CN_DIGITS[ones] if ones else 0)
    return _CN_DIGITS.get(text)


def _date(year: int, month: int | None, day: int | None) -> date | None:
    try:
        return date(year, month, day)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _next(month: int | None, day: int | None, today: date) -> date | None:
    """The next such day, today included (29 February: the next year that has one)."""
    for year in range(today.year, today.year + 9):
        found = _date(year, month, day)
        if found and found >= today:
            return found
    return None


def dates_in(texts: Iterable[str], today: date) -> set[date]:
    """Every date written out in `texts`."""
    found: set[date | None] = set()
    for raw in texts:
        text = unicodedata.normalize("NFKC", raw or "")

        def full(match: re.Match) -> str:
            found.add(_date(int(match[1]), int(match[2]), int(match[3])))
            return " " * len(match[0])

        def month_day(match: re.Match) -> str:
            month, day = _number(match[2]), _number(match[3])
            if match[1]:
                found.add(_date(today.year + _YEAR_WORDS[match[1]], month, day))
            else:
                found.add(_next(month, day, today))
            return " " * len(match[0])

        def named(month_name: str, day: str, year: str | None) -> None:
            month = _MONTHS[month_name.lower()]
            found.add(_date(int(year), month, int(day)) if year else _next(month, int(day), today))

        def name_first(match: re.Match) -> str:
            named(match[1], match[2], match[3])
            return " " * len(match[0])

        def day_first(match: re.Match) -> str:
            named(match[2], match[1], match[3])
            return " " * len(match[0])

        # A span that has been read is blanked, so a full date is not read a second time without its year.
        text = _FULL.sub(full, text)
        text = _MONTH_DAY.sub(month_day, text)
        text = _DAY_FIRST.sub(day_first, text)
        _NAME_FIRST.sub(name_first, text)
    return {d for d in found if d is not None}


def _folded(text: str) -> str:
    return "".join(unicodedata.normalize("NFKC", text or "").casefold().split())


def said(texts: Iterable[str], phrase: str) -> bool:
    """Whether the applicant wrote `phrase`: the same characters, whatever the case and spacing."""
    wanted = _folded(phrase)
    return bool(wanted) and any(wanted in _folded(text) for text in texts)


def today() -> date:
    """Today in Beijing, the day the rest of the app counts deadlines from."""
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()
