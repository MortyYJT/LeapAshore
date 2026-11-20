"""The words of a reminder email.

Red line: the email states nothing that is not in the applicant's own record. Every fact below is a
field of the record as 「我的申请」 serves it (school, name, round, deadline date, source link, whether
and when the applicant checked the date, whether the date came from the catalogue). "Checked" is the
applicant's own tick in 「我的申请」 (我已自行核对本轮截止日期与来源), and the email calls it that; it does
not say against what. The record has a
date and no time of day or zone, so the email gives none and sends the applicant to the official
page for them. The number of days is arithmetic on the stored date, counted between Beijing dates.

Two parts with the same content: plain text, and HTML with inline styles only. The HTML loads
nothing: no image, no font, no stylesheet, no tracking link.
"""

from dataclasses import dataclass
from datetime import date, datetime
from html import escape
from zoneinfo import ZoneInfo

BEIJING = ZoneInfo("Asia/Shanghai")
COLLECTED = "collected"


@dataclass(frozen=True)
class Entry:
    """One application in the email, as its record reads on the day of sending."""

    school: str
    name: str
    round: str | None
    deadline: date
    days_left: int
    source_url: str | None
    checked_at: datetime | None
    origin: str | None


def _line(value: str) -> str:
    """A stored name on one line: a line break in it would end a mail header early."""
    return " ".join(value.split())


def _title(entry: Entry) -> str:
    title = f"{_line(entry.school)} · {_line(entry.name)}"
    return f"{title}（{_line(entry.round)}）" if entry.round else title


def _when(entry: Entry) -> str:
    if entry.days_left == 0:
        return f"记录的截止日期：{entry.deadline.isoformat()}，就是今天。"
    return f"记录的截止日期：{entry.deadline.isoformat()}，还有 {entry.days_left} 天。"


def _checked(entry: Entry) -> str:
    collected = entry.origin == COLLECTED
    if entry.checked_at is not None:
        day = entry.checked_at.astimezone(BEIJING).date().isoformat()
        if collected:
            return f"这个日期来自学校库的采集，你在 {day} 自行核对过。"
        return f"你在 {day} 自行核对过这个日期和来源。"
    if collected:
        return "这个日期来自学校库的采集，你还没有核对。"
    return "这个日期你还没有核对。"


NO_SOURCE = "这条记录没有填来源链接。"
ZONE_NOTE = "天数按北京时间的日期计算。记录里只有日期，没有具体时间和时区。几点截止、按哪个时区算，请到学校官网确认。"
SETTINGS_NOTE = "提前几天提醒，可以登录后在「设置」的「提醒」里改。"
SENDER_NOTE = "这封邮件由鱼跃彼岸（LeapAshore）按你账号的提醒设置发出。"
UNSUBSCRIBE_NOTE = "打开这个链接就会退订，不用登录。"


def subject(entries: list[Entry]) -> str:
    nearest = entries[0]
    left = "今天" if nearest.days_left == 0 else f"还有 {nearest.days_left} 天"
    if len(entries) == 1:
        return f"申请截止提醒：{_line(nearest.school)} {_line(nearest.name)}，{left}"
    return f"申请截止提醒：{len(entries)} 个项目，最近的{'是今天' if nearest.days_left == 0 else left}"


def _intro(entries: list[Entry]) -> str:
    if len(entries) == 1:
        return "你记录的这个申请快到截止日期了。"
    return f"你记录的申请里，有 {len(entries)} 个项目快到截止日期了。"


def text(entries: list[Entry], applications_url: str, unsubscribe_page: str) -> str:
    lines = [_intro(entries), ""]
    for number, entry in enumerate(entries, 1):
        lines += [
            f"{number}. {_title(entry)}",
            f"   {_when(entry)}",
            f"   {_checked(entry)}",
            f"   来源：{entry.source_url}" if entry.source_url else f"   {NO_SOURCE}",
            "",
        ]
    lines += [
        ZONE_NOTE,
        "",
        f"查看或修改这些申请：{applications_url}",
        SETTINGS_NOTE,
        "",
        SENDER_NOTE,
        f"不想再收到提醒：{unsubscribe_page}",
        UNSUBSCRIBE_NOTE,
        "",
    ]
    return "\n".join(lines)


# Inline styles only; the colours are the design system's ink, secondary ink, rule and urgent red.
_FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif"
_INK, _INK_2, _RULE, _URGENT = "#111722", "#485263", "#e2e6ec", "#be222b"
_P = f"margin:0 0 6px;font-size:14px;line-height:1.6;color:{_INK_2};"
_LINK = f"color:{_INK};text-decoration:underline;"


def _html_entry(entry: Entry) -> str:
    days = "今天" if entry.days_left == 0 else f"还有 {entry.days_left} 天"
    when = (
        f'记录的截止日期：<strong style="color:{_INK};font-weight:600;">{entry.deadline.isoformat()}</strong>，'
        f'<strong style="color:{_URGENT};font-weight:600;">{"就是今天" if entry.days_left == 0 else days}</strong>。'
    )
    if entry.source_url:
        url = escape(entry.source_url, quote=True)
        source = f'来源：<a href="{url}" style="{_LINK}word-break:break-all;">{url}</a>'
    else:
        source = NO_SOURCE
    return (
        f'<div style="border-top:1px solid {_RULE};padding:14px 0 8px;">'
        f'<p style="margin:0 0 6px;font-size:15px;line-height:1.5;font-weight:600;color:{_INK};">'
        f"{escape(_title(entry))}</p>"
        f'<p style="{_P}">{when}</p>'
        f'<p style="{_P}">{escape(_checked(entry))}</p>'
        f'<p style="{_P}">{source}</p>'
        "</div>"
    )


def html(entries: list[Entry], applications_url: str, unsubscribe_page: str, title: str) -> str:
    items = "".join(_html_entry(entry) for entry in entries)
    applications = escape(applications_url, quote=True)
    unsubscribe = escape(unsubscribe_page, quote=True)
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(title)}</title></head>"
        '<body style="margin:0;padding:0;background:#ffffff;">'
        f'<div style="max-width:560px;margin:0 auto;padding:24px 20px 32px;font-family:{_FONT};color:{_INK};">'
        f'<p style="margin:0 0 16px;font-size:16px;line-height:1.5;font-weight:600;color:{_INK};">'
        f"{escape(_intro(entries))}</p>"
        f"{items}"
        f'<div style="border-top:1px solid {_RULE};padding-top:14px;">'
        f'<p style="{_P}">{ZONE_NOTE}</p>'
        f'<p style="margin:14px 0 6px;font-size:14px;line-height:1.6;">'
        f'<a href="{applications}" style="{_LINK}font-weight:600;">查看或修改这些申请</a></p>'
        f'<p style="{_P}">{SETTINGS_NOTE}</p>'
        f'<p style="margin:14px 0 0;font-size:12px;line-height:1.6;color:{_INK_2};">{SENDER_NOTE}不想再收到提醒：'
        f'<a href="{unsubscribe}" style="color:{_INK_2};text-decoration:underline;">退订</a>。{UNSUBSCRIBE_NOTE}</p>'
        "</div></div></body></html>"
    )
