"""Recognise the schools and subjects a question names, from data rather than from code.

A question names a school by its catalogue name (simplified or traditional Chinese, English), by an
abbreviation inside its English name ("(UCL)"), or by a short form applicants use ("帝国理工", "港大").
The first two come from the `universities` rows; the short forms come from
`data/advisor/university_aliases.json`, keyed by university id. Nothing here knows any school by name.

Subjects come from `data/advisor/subjects.json`: each entry maps applicant words ("计算机", "CS") to a
`Program.field` study area, plus a name pattern used only to rank the rows inside that area.

Both the question and the vocabulary are folded the same way (NFKC, lower case, traditional to
simplified through OpenCC's character table in `data/advisor/zh_t2s.json`), so "香港大学" finds
"香港大學". Overlapping matches keep the longest: "西悉尼大学" is Western Sydney University, not the
University of Sydney, and "伦敦政治经济学院" does not also ask about economics.
"""

import json
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "advisor"
ALIASES_FILE = DATA_DIR / "university_aliases.json"
SUBJECTS_FILE = DATA_DIR / "subjects.json"
T2S_FILE = DATA_DIR / "zh_t2s.json"

_CJK = r"㐀-鿿"
_JOINERS = re.compile(rf"(?<=[{_CJK}])[\s·・\-–—]+(?=[{_CJK}])")
_SPACES = re.compile(r"\s+")
# A Chinese name's trailing qualifier, "纽卡斯尔大学（英国）", and an English name's parenthesis,
# "University College London (UCL)". NFKC has already turned the full-width brackets into ASCII ones.
_PARENS = re.compile(r"\s*\(([^()]*)\)\s*")


@lru_cache(maxsize=1)
def _t2s() -> dict[int, str]:
    table = json.loads(T2S_FILE.read_text(encoding="utf-8"))["map"]
    return str.maketrans(table)


def normalize(text: str) -> str:
    """Fold width, case, script and separators, so the same name written two ways compares equal."""
    text = unicodedata.normalize("NFKC", text or "").lower().translate(_t2s())
    text = text.replace("’", "'").replace("‘", "'")
    text = _JOINERS.sub("", text)
    return _SPACES.sub(" ", text).strip()


def _is_ascii(term: str) -> bool:
    return all(ord(c) < 128 for c in term)


def _find(text: str, term: str) -> list[tuple[int, int]]:
    """Every occurrence of `term`; a Latin term must stand as whole words ("mit" is not in "submit")."""
    if not term:
        return []
    if _is_ascii(term):
        pattern = rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])"
        return [(m.start(), m.end()) for m in re.finditer(pattern, text)]
    spans, start = [], text.find(term)
    while start != -1:
        spans.append((start, start + len(term)))
        start = text.find(term, start + 1)
    return spans


def _longest_matches(text: str, vocabulary: dict[str, set]) -> list[tuple[tuple[int, int], set]]:
    """Matches of the vocabulary in `text`, longest first, dropping any that overlap a longer one.

    Two terms matching exactly the same span (one school's Chinese name shared by two rows) are kept
    together, so an ambiguous name returns every school it can mean.
    """
    found: dict[tuple[int, int], set] = {}
    for term, targets in vocabulary.items():
        for span in _find(text, term):
            found.setdefault(span, set()).update(targets)
    kept: list[tuple[tuple[int, int], set]] = []
    for span in sorted(found, key=lambda s: (s[0] - s[1], s[0])):
        if any(span[0] < e and s < span[1] for (s, e), _ in kept):
            continue
        kept.append((span, found[span]))
    return sorted(kept)


def _blank(text: str, spans: list[tuple[int, int]]) -> str:
    chars = list(text)
    for start, end in spans:
        chars[start:end] = " " * (end - start)
    return "".join(chars)


# ---- schools ----------------------------------------------------------------------------------


@lru_cache(maxsize=1)
def curated_aliases() -> dict[str, list[str]]:
    return json.loads(ALIASES_FILE.read_text(encoding="utf-8"))["aliases"]


def names_for(university_id: str, name: str | None, name_en: str | None) -> set[str]:
    """Every folded spelling a university row answers to."""
    out: set[str] = set()
    for raw in (name, name_en):
        folded = normalize(raw or "")
        if not folded:
            continue
        out.add(folded)
        base = _PARENS.sub(" ", folded).strip()
        out.add(base)
        if base.startswith("the "):
            out.add(base[4:])
        for inner in _PARENS.findall(folded):
            # "(MIT)", "(NTU Singapore)" are other names for the school; "(Sydney, Australia)" is a
            # place, and "（英国）" only tells two same-named schools apart.
            inner = inner.strip()
            if inner and "," not in inner and _is_ascii(inner):
                out.add(inner)
    out.update(normalize(a) for a in curated_aliases().get(university_id, ()))
    return {n for n in out if len(n) >= 2}


# A Chinese school name ends with one of these; text running on into one after a match is a longer
# name the catalogue does not hold ("牛津布鲁克斯大学" is not 牛津).
_SCHOOL_SUFFIXES = ("大学", "学院")
# Characters that end a name in running text, so "牛津和剑桥大学" is two names, not one unknown one.
_NAME_STOPS = set("的和与及跟或同对比在里、")
_SUFFIX_REACH = 8


def _cjk(ch: str) -> bool:
    return "㐀" <= ch <= "鿿"


class SchoolIndex:
    """Folded name -> university ids, built from the catalogue's rows and the curated aliases."""

    def __init__(self, rows: list[tuple[str, str | None, str | None]]):
        self.names: dict[str, str] = {uid: (name or name_en or uid) for uid, name, name_en in rows}
        self.vocabulary: dict[str, set[str]] = {}
        # The catalogue's own Chinese names per school, to tell an abbreviation from a broken-off
        # copy of the full name ("港大" inside "香港大湾区").
        self.full_names: dict[str, set[str]] = {}
        for uid, name, name_en in rows:
            for term in names_for(uid, name, name_en):
                self.vocabulary.setdefault(term, set()).add(uid)
            folded = normalize(name or "")
            self.full_names[uid] = {folded, _PARENS.sub(" ", folded).strip()} - {""}

    def _incomplete_full_name(self, text: str, start: int, end: int, uids: set[str]) -> bool:
        """The match sits where one of its schools' full names starts, but the full name does not
        follow: "香港大湾区" holds 港大 at the place 香港大学 would have it."""
        term = text[start:end]
        for uid in uids:
            for full in self.full_names.get(uid, ()):
                i = full.find(term)
                if i > 0 and start - i >= 0 and text[start - i:start] == full[:i] \
                        and text[start - i:start - i + len(full)] != full:
                    return True
        return False

    @staticmethod
    def _runs_into_unknown_name(text: str, start: int, end: int, others: list[tuple[int, int]]) -> bool:
        """Chinese text that carries on into 大学 or 学院 right after the match, with no break and no
        other name or subject in between, is a longer school name: "牛津布鲁克斯大学", "圣地亚哥大学"
        (which holds 哥大)."""
        term = text[start:end]
        if not term or not _cjk(term[-1]) or term.endswith(_SCHOOL_SUFFIXES):
            return False
        window_end = min(len(text), end + _SUFFIX_REACH)
        for suffix in _SCHOOL_SUFFIXES:
            at = text.find(suffix, max(start + 1, end - len(suffix) + 1), window_end)
            if at == -1 or at + len(suffix) <= end:
                continue
            between = text[end:at]
            if any(not _cjk(c) or c in _NAME_STOPS for c in between):
                continue
            if any(end <= s < at for s, _ in others):
                continue
            if _longest_matches(between, _subject_vocabulary()):
                continue
            return True
        return False

    def match(self, text: str) -> tuple[list[str], list[tuple[int, int]]]:
        """University ids named in `text` (folded), in the order they appear, and their spans."""
        found = _longest_matches(text, self.vocabulary)
        spans = [span for span, _ in found]
        ids: list[str] = []
        kept = []
        for (start, end), uids in found:
            if self._incomplete_full_name(text, start, end, uids):
                continue
            if self._runs_into_unknown_name(text, start, end, [s for s in spans if s != (start, end)]):
                continue
            kept.append((start, end))
            for uid in sorted(uids):
                if uid not in ids:
                    ids.append(uid)
        return ids, kept


_index_cache: dict[tuple, SchoolIndex] = {}


def school_index(rows: list[tuple[str, str | None, str | None]]) -> SchoolIndex:
    """The index for these rows, rebuilt only when the universities table changes."""
    key = tuple(sorted(rows))
    if key not in _index_cache:
        _index_cache.clear()
        _index_cache[key] = SchoolIndex(rows)
    return _index_cache[key]


# ---- subjects ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Subject:
    field: str
    name_pattern: str  # a regex on the program's English name, used to rank rows inside the field
    narrows: bool = False  # a specific subject keeps only the rows its pattern fits, when there are any


@lru_cache(maxsize=1)
def subject_entries() -> list[dict]:
    return json.loads(SUBJECTS_FILE.read_text(encoding="utf-8"))["subjects"]


@lru_cache(maxsize=1)
def _subject_vocabulary() -> dict[str, set[Subject]]:
    vocabulary: dict[str, set[Subject]] = {}
    for entry in subject_entries():
        subject = Subject(entry["field"], entry["name"], entry.get("narrows", False))
        for term in entry["terms"]:
            vocabulary.setdefault(normalize(term), set()).add(subject)
    return vocabulary


def match_subjects(text: str) -> tuple[list[Subject], list[str], list[tuple[int, int]]]:
    """Subjects named in `text` (folded, with school names already blanked out), the words used, and
    where they are."""
    out: list[Subject] = []
    words: list[str] = []
    spans: list[tuple[int, int]] = []
    for (start, end), subjects in _longest_matches(text, _subject_vocabulary()):
        words.append(text[start:end])
        spans.append((start, end))
        for s in sorted(subjects, key=lambda s: (s.field, s.name_pattern)):
            if s not in out:
                out.append(s)
    return out, list(dict.fromkeys(words)), spans


@dataclass
class Parsed:
    schools: list[str]
    subjects: list[Subject]
    subject_words: list[str] = field(default_factory=list)  # as the question wrote them, folded
    rest: str = ""  # the folded question with the school names and subject words blanked out

    @property
    def fields(self) -> list[str]:
        return list(dict.fromkeys(s.field for s in self.subjects))

    @property
    def name_pattern(self) -> str | None:
        """Ranks rows inside the named areas."""
        return _union(s.name_pattern for s in self.subjects)

    @property
    def narrowing_pattern(self) -> str | None:
        """Keeps only the fitting rows, when every subject named is a specific one ("金融", not "商科")."""
        if self.subjects and all(s.narrows for s in self.subjects):
            return self.name_pattern
        return None


def _union(patterns) -> str | None:
    unique = list(dict.fromkeys(p for p in patterns if p))
    return "|".join(f"(?:{p})" for p in unique) or None


def parse(index: SchoolIndex, question: str) -> Parsed:
    """Schools first; their names are then blanked so "伦敦政治经济学院" is not also a subject."""
    text = normalize(question)
    schools, spans = index.match(text)
    without_schools = _blank(text, spans)
    subjects, words, subject_spans = match_subjects(without_schools)
    return Parsed(schools=schools, subjects=subjects, subject_words=words,
                  rest=_SPACES.sub(" ", _blank(without_schools, subject_spans)).strip())
