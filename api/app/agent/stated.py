"""What the applicant wrote in the conversation, read by rule and not by the model.

The advisor never invents a deadline (CLAUDE.md, red lines). A date it proposes for an application is
either the catalogue's, looked up on the server, or one the applicant stated. For the second kind the
model's word is not taken: the tool reads the applicant's own messages here and writes the date only
when it finds it in them. A date the model wrote, or one a tool returned, is not the applicant's.

What counts as a written date is deliberately narrow, because a wrong match would let a made-up date
through as "stated":

- a full date: `2027-01-15`, `2027/1/15`, `2027.1.15`, `2027年1月15日`, `January 15, 2027`, `15 Jan 2027`;
- a month and a day without a year, `1月15日`, `1 月 15 号`, `十二月一日`, `Jan 15`: the next such day
  counted from the day the message was sent, or the year 今年, 明年 or 后年 names in front of it.

A month and a day are not read when the year cannot be told: the message has no known date of its own
(one stored before messages carried one), or it mentions a year somewhere else (`1月15日（2028年）`,
`去年12月1日`, `Jan 15, 28`). An English month must be capitalised (`may 5` is a verb and a number),
and the day-first form needs its year and must not follow a word (`Round 2 Jan 15` is January 15).
`1/15` and `1.15` are not read (a day and a month in either order, or a mark), nor is anything
relative (下周五, 月底), nor a date inside a link.

This proves where a date came from, not what it is the date of: a date the applicant wrote about
something else is still one they wrote. The confirm card is where they see what it would be recorded as.
"""

import re
import unicodedata
from collections.abc import Iterable
from datetime import date, datetime
from zoneinfo import ZoneInfo

from langchain_core.messages import HumanMessage

# Where a message keeps the day it was sent (`HumanMessage.additional_kwargs`).
SAID_ON = "said_on"

_CN_DIGITS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_NUMBER = r"[一二两三四五六七八九十]{1,3}"
_NUMBER = rf"(?:\d{{1,2}}|{_CN_NUMBER})"

_LINK = re.compile(r"https?://\S+")
_FULL = re.compile(r"(?<!\d)(20\d\d)\s*(?:[-/.]|年的?)\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})(?!\d)\s*[日号]?")
_MONTH_DAY = re.compile(rf"(?:(今年|明年|后年)的?)?\s*(?<![\d一二两三四五六七八九十])({_NUMBER})\s*月\s*({_NUMBER})\s*[日号]")
_MONTHS = {
    name: number
    for number, names in enumerate(
        (
            ("Jan", "January"), ("Feb", "February"), ("Mar", "March"), ("Apr", "April"), ("May",),
            ("Jun", "June"), ("Jul", "July"), ("Aug", "August"), ("Sep", "Sept", "September"),
            ("Oct", "October"), ("Nov", "November"), ("Dec", "December"),
        ),
        start=1,
    )
    for name in names
}
_MONTHS |= {name.upper(): number for name, number in _MONTHS.items()}
_MONTH_NAME = "|".join(sorted(_MONTHS, key=len, reverse=True))
_DAY = r"(\d{1,2})(?!\d)(?:st|nd|rd|th)?"
_NAME_FIRST = re.compile(rf"(?<![A-Za-z])({_MONTH_NAME})(?![A-Za-z])\.?\s*{_DAY}(?:\s*,?\s*(20\d\d)(?!\d))?")
_DAY_FIRST = re.compile(rf"(?<![A-Za-z] )(?<![\dA-Za-z]){_DAY} ({_MONTH_NAME})(?![A-Za-z])\.?\s*,?\s*(20\d\d)(?!\d)")
# A year the patterns above did not take: the date beside it cannot be given a year by rule.
_STRAY_YEAR = re.compile(r"(?<!\d)(?:19|20)\d\d(?!\d)|\d\d\s*年|去年|前年")
_SHORT_YEAR_AFTER = re.compile(r"\s*,?\s*'?\d\d(?!\d)")
_YEAR_WORDS = {"今年": 0, "明年": 1, "后年": 2}

Said = tuple[str, date | None]


def today() -> date:
    """Today in Beijing, the day the rest of the app counts deadlines from."""
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


def stamp() -> dict:
    """What a new applicant message carries so its dates can be read later: the day it was sent."""
    return {SAID_ON: today().isoformat()}


def applicant_texts(state) -> list[Said]:
    """The applicant's own messages in this conversation, oldest first, each with the day it was sent
    (None for a message stored before messages carried one)."""
    out: list[Said] = []
    for message in (state or {}).get("messages") or []:
        if not isinstance(message, HumanMessage) or not isinstance(message.content, str):
            continue
        try:
            sent = date.fromisoformat(str((message.additional_kwargs or {}).get(SAID_ON)))
        except ValueError:
            sent = None
        out.append((message.content, sent))
    return out


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


def _next(month: int | None, day: int | None, since: date) -> date | None:
    """The next such day, `since` included (29 February: the next year that has one)."""
    for year in range(since.year, since.year + 9):
        found = _date(year, month, day)
        if found and found >= since:
            return found
    return None


def _split(item, fallback: date | None) -> Said:
    return (item, fallback) if isinstance(item, str) else item


def dates_in(texts: Iterable[str | Said], today: date | None = None) -> set[date]:
    """Every date written out in `texts`. An item is a message with the day it was sent; a bare string
    is taken as sent on `today`."""
    found: set[date | None] = set()
    for item in texts:
        raw, sent = _split(item, today)
        text = " ".join(_LINK.sub(" ", unicodedata.normalize("NFKC", raw or "")).split())

        def full(match: re.Match) -> str:
            found.add(_date(int(match[1]), int(match[2]), int(match[3])))
            return " " * len(match[0])

        def named_with_year(match: re.Match, month: str, day: str) -> str:
            found.add(_date(int(match[3]), _MONTHS[month], int(day)))
            return " " * len(match[0])

        # A span that has been read is blanked, so a full date is not read a second time without its year.
        text = _FULL.sub(full, text)
        text = _DAY_FIRST.sub(lambda m: named_with_year(m, m[2], m[1]), text)
        text = _NAME_FIRST.sub(lambda m: named_with_year(m, m[1], m[2]) if m[3] else m[0], text)
        if sent is None or _STRAY_YEAR.search(text):
            continue
        for match in _MONTH_DAY.finditer(text):
            month, day = _number(match[2]), _number(match[3])
            found.add(_date(sent.year + _YEAR_WORDS[match[1]], month, day) if match[1] else _next(month, day, sent))
        for match in _NAME_FIRST.finditer(text):
            if not _SHORT_YEAR_AFTER.match(text, match.end()):
                found.add(_next(_MONTHS[match[1]], int(match[2]), sent))
    return {d for d in found if d is not None}


def _folded(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text or "").casefold().split())


def said(texts: Iterable[str | Said], phrase: str) -> bool:
    """Whether the applicant wrote `phrase`: the same characters, whatever the case and the amount of
    spacing, and as whole words where it starts or ends with a letter or a digit (`around 12` does not
    say `Round 1`)."""
    wanted = _folded(phrase)
    if not wanted:
        return False
    pattern = re.compile(
        ("(?<![a-z0-9])" if wanted[0].isascii() and wanted[0].isalnum() else "")
        + re.escape(wanted).replace(r"\ ", r"\s*")
        + ("(?![a-z0-9])" if wanted[-1].isascii() and wanted[-1].isalnum() else "")
    )
    return any(pattern.search(_folded(_split(item, None)[0])) for item in texts)
