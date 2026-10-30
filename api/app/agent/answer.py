"""Answer from official page passages, then check every quote (openspec snapshot-rag D8, D9).

The model is asked for sentences, each with the passages it relies on and the exact words it copied from
each. Nothing it writes is shown before `verify` has run:

- every sentence cites at least one passage, by a number the model was given;
- every quote is at least `MIN_QUOTE_CHARS` long and appears verbatim in the stored chunk, compared
  after the same folding the collectors' `verify` uses (Unicode form, quotes, dashes, spacing, case);
- every number the sentence states (an amount, a count, a year) is in one of its quotes; English
  number words and month names count as their numbers.

A sentence that fails any check is removed, with the reason kept in the trace. When no sentence is
left, the advisor refuses and lists the pages it read; it never states what it could not source.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime

from pydantic import BaseModel, Field

from app.agent.llm import get_chat_model
from app.agent.passages import Passage
from app.collect.text import normalize

MIN_QUOTE_CHARS = 12

PROMPT = """你是鱼跃彼岸的留学申请顾问。只能依据下面编号的学校官方页面摘录回答用户的问题。

规则：
1. 每句话都必须引用至少一段摘录：给出摘录编号，和从该摘录中逐字复制的原文（一个字都不改，不翻译，不省略中间的词，不把不相邻的句子拼在一起，至少 12 个字符）。
2. 用中文回答。句子里写出的金额、数字、年份必须在所引原文里出现。
3. 摘录没有写的内容一律不写：不推测，不补充常识，不写"页面没有提到"之类的话。
4. 摘录来自哪个项目的页面，就说明是哪个项目的信息；不要把别的项目的信息说成用户问的项目。学校通用页面的信息要说明是学校通用的规定。
5. 不提供签证、移民等法律建议。回答简洁，一般 2 到 5 句。

用户的问题：{question}

官方页面摘录：
{passages}"""


class Quote(BaseModel):
    passage: int = Field(description="摘录编号")
    quote: str = Field(description="从该摘录逐字复制的原文")


class CitedSentence(BaseModel):
    text: str = Field(description="一句中文回答")
    citations: list[Quote] = Field(default_factory=list)


class PassageAnswer(BaseModel):
    sentences: list[CitedSentence] = Field(default_factory=list)


@dataclass
class Checked:
    text: str
    passages: list[int]  # 1-based numbers of the passages it cites, in order
    ok: bool
    reasons: list[str] = field(default_factory=list)


@dataclass
class Verification:
    sentences: list[Checked]
    quotes: int = 0
    quotes_passed: int = 0

    @property
    def kept(self) -> list[Checked]:
        return [s for s in self.sentences if s.ok]

    def summary(self) -> dict:
        reasons: dict[str, int] = {}
        for s in self.sentences:
            for r in s.reasons:
                reasons[r] = reasons.get(r, 0) + 1
        return {"sentences": len(self.sentences), "kept": len(self.kept), "quotes": self.quotes,
                "quotes_passed": self.quotes_passed, "reasons": reasons}


# ---- numbers ------------------------------------------------------------------------------------

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_WORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8",
    "nine": "9", "ten": "10", "eleven": "11", "twelve": "12", "single": "1", "both": "2", "twice": "2",
    # Not "may": the modal verb is on every admissions page and would vouch for any 5 (review of #60).
    "january": "1", "february": "2", "march": "3", "april": "4", "june": "6", "july": "7",
    "august": "8", "september": "9", "october": "10", "november": "11", "december": "12",
    "jan": "1", "feb": "2", "mar": "3", "apr": "4", "jun": "6", "jul": "7", "aug": "8", "sep": "9", "sept": "9",
    "oct": "10", "nov": "11", "dec": "12",
}
_WORD = re.compile(r"[a-z]+")
_MARKER = re.compile(r"\s*[\[［【]\d+[\]］】]")


def _canonical(number: str) -> str:
    """A number without thousands separators or a trailing ".0": 53,000 and 53000 are one number."""
    text = number.replace(",", "")
    if "." in text:
        text = text.rstrip("0").rstrip(".") or "0"
    return text.lstrip("0") or "0"


# A Chinese number before a measure word or a currency states a count, a length or an amount ("两封推荐信",
# "三十天", "十二个月", "二〇二六年", "三万五千美元"). The whole run of numerals is read, so 三十 is 30, not 10. A lone 一 is left out: before a
# measure word it is as often the article ("一次额外面试" is "an additional interview") as the number. A
# run after 第 is an ordinal ("第十二轮").
_CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8,
              "九": 9}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000}
_CN_CHARS = "零〇一二两三四五六七八九十百千万"
_CHINESE_COUNT = re.compile(
    rf"(?<![第\d{_CN_CHARS}])([{_CN_CHARS}]+)(?=(?:封|位|名|个|轮|次|份|门|年|学期|个月|周|天|小时|分钟|学分|(?:美|欧|澳|加|港|新)?元|英?镑))"
)


def _chinese_value(run: str) -> int:
    if not any(c in _CN_UNITS or c == "万" for c in run):
        return int("".join(str(_CN_DIGITS[c]) for c in run))  # read digit by digit: 二〇二六
    total = section = digit = 0
    for c in run:
        if c in _CN_DIGITS:
            digit = _CN_DIGITS[c]
        elif c in _CN_UNITS:
            section += (digit or (1 if c == "十" else 0)) * _CN_UNITS[c]
            digit = 0
        elif c == "万":
            total += (section + digit) * 10000
            section = digit = 0
    return total + section + digit


def numbers_in(text: str) -> set[str]:
    """The numbers a sentence states: Arabic ones, and Chinese numerals that count something."""
    counts = {str(_chinese_value(run)) for run in _CHINESE_COUNT.findall(text) if run != "一"}
    return {_canonical(n) for n in _NUMBER.findall(text)} | counts


def numbers_quoted(quotes: list[str]) -> set[str]:
    out: set[str] = set()
    for quote in quotes:
        out |= numbers_in(quote)
        # "53.000 €" in a European page is 53000 too.
        out |= {_canonical(n.replace(".", "")) for n in re.findall(r"\d{1,3}(?:\.\d{3})+", quote)}
        out |= {_WORDS[w] for w in _WORD.findall(quote.lower()) if w in _WORDS}
    return out


# ---- checks ---------------------------------------------------------------------------------------


def verify(answer: PassageAnswer, chunk_texts: list[str]) -> Verification:
    """Check every sentence of `answer` against the passages it was given (`chunk_texts`, 1-based)."""
    folded = [normalize(t) for t in chunk_texts]
    out = Verification(sentences=[])
    for sentence in answer.sentences:
        reasons: list[str] = []
        cited: list[int] = []
        quotes: list[str] = []
        # The reply adds its own markers; a marker the model wrote is not a number it states.
        text = _MARKER.sub("", sentence.text or "").strip()
        if not text:
            continue
        if not sentence.citations:
            reasons.append("no_citation")
        for citation in sentence.citations:
            out.quotes += 1
            quote = normalize(citation.quote or "")
            if not 1 <= citation.passage <= len(folded):
                reasons.append("unknown_passage")
            elif len(quote) < MIN_QUOTE_CHARS:
                reasons.append("quote_too_short")
            elif quote not in folded[citation.passage - 1]:
                reasons.append("quote_not_in_passage")
            else:
                out.quotes_passed += 1
                quotes.append(citation.quote)
                if citation.passage not in cited:
                    cited.append(citation.passage)
        if not reasons:
            missing = numbers_in(text) - numbers_quoted(quotes)
            if missing:
                reasons.append("number_not_in_quotes")
        out.sentences.append(Checked(text=text, passages=cited, ok=not reasons, reasons=list(dict.fromkeys(reasons))))
    return out


# ---- the reply -------------------------------------------------------------------------------------


def render(checked: Verification, passages: list[dict]) -> tuple[str, list[dict]]:
    """The reply the applicant sees and its citations, numbered in order of first use."""
    numbers: dict[int, int] = {}
    lines = []
    for s in checked.kept:
        marks = ""
        for n in s.passages:
            numbers.setdefault(n, len(numbers) + 1)
            marks += f"[{numbers[n]}]"
        lines.append(s.text.rstrip() + marks)
    citations = []
    for original, shown in sorted(numbers.items(), key=lambda kv: kv[1]):
        p = passages[original - 1]
        citations.append({
            "n": shown, "programId": "", "program": p.get("program") or p["school"],
            "title": p.get("program") or p.get("title") or p["url"], "url": p["url"], "status": "待核验",
            "fetchedAt": p.get("fetched_at"),
        })
    dates = sorted({(p.get("fetched_at") or "")[:10] for p in (passages[o - 1] for o in numbers) if p.get("fetched_at")})
    when = f"（抓取于 {'、'.join(dates)}）" if dates else ""
    reply = "".join(lines)
    reply += f"\n\n以上摘自学校官方页面{when}，数据待核验，请以官网最新信息为准。"
    dropped = len(checked.sentences) - len(checked.kept)
    if dropped:
        reply += f"另有 {dropped} 句没能逐字核对到原文，已删去。"
    return reply, citations


def refusal_after_check(passages: list[dict]) -> str:
    urls = list(dict.fromkeys(p["url"] for p in passages))[:3]
    pages = "\n".join(f"- {u}" for u in urls)
    return ("我找到了相关的官方页面段落，但没能写出每句都能逐字核对到原文的回答，所以不作判断，"
            f"以免你照着不准确的信息去申请。你可以直接查看这些官方页面：\n{pages}")


def prompt_for(question: str, passages: list[dict]) -> str:
    blocks = []
    for n, p in enumerate(passages, 1):
        header = Passage(chunk_id=p["chunk_id"], text=p["text"], url=p["url"], title=p.get("title"),
                         school=p["school"], program=p.get("program"),
                         fetched_at=datetime.fromisoformat(p["fetched_at"]) if p.get("fetched_at") else None).header(n)
        blocks.append(f"{header}\n{p['text']}")
    return PROMPT.format(question=question, passages="\n\n".join(blocks))


@dataclass
class Generated:
    answer: PassageAnswer  # empty when the model's reply could not be read: nothing to show
    usage: dict
    model: str | None
    error: str | None = None


def _usage(raw) -> dict:
    meta = getattr(raw, "usage_metadata", None) or {}
    details = meta.get("input_token_details") or {}
    return {"input_tokens": meta.get("input_tokens", 0), "output_tokens": meta.get("output_tokens", 0),
            "cache_read_tokens": details.get("cache_read", 0) or 0}


async def generate(question: str, passages: list[dict], model=None) -> Generated:
    """One function-calling request at temperature 0. A reply that cannot be parsed is an empty answer,
    which the caller turns into a refusal: an unreadable answer is not retried with the same passages."""
    model = model or get_chat_model(temperature=0)
    structured = model.with_structured_output(PassageAnswer, method="function_calling", include_raw=True)
    out = await structured.ainvoke(prompt_for(question, passages))
    raw = out["raw"]
    parsed = out.get("parsed")
    error = str(out["parsing_error"])[:300] if out.get("parsing_error") else None
    if parsed is None and error is None:
        error = "no function call"
    return Generated(answer=parsed or PassageAnswer(), usage=_usage(raw),
                     model=(raw.response_metadata or {}).get("model_name"), error=error)
