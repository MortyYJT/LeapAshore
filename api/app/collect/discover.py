"""Find a school's taught master's program pages on its official listing (openspec collect-queue, D11).

The listing URLs come from `_schools.json` (found with web search, which is used only to find URLs).
Each listing is fetched with the snapshot tool like any other page. The links on it that stay on the
school's own site are numbered and shown to the advisor's model, which answers, by function call, which
numbers are taught master's program pages. Only numbers from the list are accepted, so the model can
choose a page but never invent an address, and the program name is the link's own text.
"""

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlsplit

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

from app.agent.llm import get_chat_model
from app.collect.text import normalize

ROOT = Path(__file__).resolve().parents[3]
CRICOS_FILE = ROOT / "web" / "prototype-fixtures" / "cricos-au-masters.json"
# Second-level labels under which a school's own site is the third label (unimelb.edu.au).
SECOND_LEVEL = {"ac", "edu", "co", "gov", "org", "net", "com"}
SKIP_EXTENSIONS = re.compile(r"\.(pdf|jpe?g|png|gif|svg|webp|docx?|xlsx?|pptx?|zip|ics|mp4|mp3|css|js)$", re.I)
# Links whose text or address mentions none of these are not shown to the model when a page has many.
HINT = re.compile(
    r"master|msc|m\.sc|\bma\b|mba|meng|mres|mphil|llm|mpa|mph|postgrad|graduate|program|programme|course"
    r"|degree|study|studies|studium|studi|master's|硕士|碩士|석사|laurea|mestrado|máster",
    re.IGNORECASE,
)
MAX_LINKS = 400


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, re.sub(r"\s+", " ", "".join(self._text)).strip()))
            self._href = None


def site_of(host: str) -> str:
    """The school's own site a host belongs to: `study.unimelb.edu.au` → `unimelb.edu.au`."""
    labels = host.lower().split(".")
    if len(labels) >= 3 and labels[-2] in SECOND_LEVEL and len(labels[-1]) == 2:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def listing_links(html: str, base_url: str) -> list[dict]:
    """The distinct links on the page that stay on the school's site, in page order, with their text."""
    parser = _Links()
    parser.feed(html)
    site = site_of(urlsplit(base_url).netloc)
    seen, out = set(), []
    for href, text in parser.links:
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        url = urldefrag(urljoin(base_url, href))[0]
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or SKIP_EXTENSIONS.search(parts.path):
            continue
        if site_of(parts.netloc) != site or url.rstrip("/") == base_url.rstrip("/"):
            continue
        if url in seen or not text:
            continue
        seen.add(url)
        out.append({"url": url, "text": text[:160]})
    return out


def candidates(links: list[dict], limit: int = MAX_LINKS) -> list[dict]:
    """The links shown to the model: all of them on a short page, else those with a hint of a degree."""
    if len(links) <= limit:
        return links
    return [link for link in links if HINT.search(link["text"]) or HINT.search(link["url"])][:limit]


class Pick(BaseModel):
    number: int = Field(description="The number of the link in the list.")


class ProgramLinks(BaseModel):
    """The links that lead to the page of one taught master's program."""

    picks: list[Pick] = Field(default_factory=list)


PROMPT = """These are the links on an official page of {school} ({country}) that lists study programs.
Answer with the numbers of the links that lead to the page of ONE taught (coursework) master's degree
program: MSc, MA, MEng, MBA, LLM, MPH, Master of X, or the country's normal master's degree (Master,
Laurea Magistrale, Máster, 석사, 碩士). Leave out: bachelor's, PhD and doctoral, research-only degrees
(MPhil, MRes, MSc by research), graduate certificates and diplomas, short courses, and pages that are
not one program (faculty pages, search pages, news, "apply", "fees", "events", navigation).
Give each program once. If none qualify, answer with an empty list.

Links:
{links}"""


def pick_programs(links: list[dict], school: dict, model: BaseChatModel | None = None) -> tuple[list[dict], dict]:
    """The links the model calls taught master's program pages, and the call's token usage."""
    if not links:
        return [], {}
    model = model or get_chat_model(temperature=0, max_tokens=2000)
    structured = model.with_structured_output(ProgramLinks, method="function_calling", include_raw=True)
    numbered = "\n".join(f"{i}. {link['text']} — {link['url']}" for i, link in enumerate(links, 1))
    answer = structured.invoke(PROMPT.format(school=school["name"], country=school.get("country") or "", links=numbered))
    raw = answer["raw"]
    meta = getattr(raw, "usage_metadata", None) or {}
    usage = {"input_tokens": meta.get("input_tokens", 0), "output_tokens": meta.get("output_tokens", 0),
             "cache_read_tokens": (meta.get("input_token_details") or {}).get("cache_read", 0) or 0}
    parsed = answer.get("parsed")
    picked, seen = [], set()
    for pick in (parsed.picks if parsed else []):
        if 1 <= pick.number <= len(links) and pick.number not in seen:
            seen.add(pick.number)
            picked.append(links[pick.number - 1])
    return picked, usage


def cricos_courses(institution: str | None, path: Path = CRICOS_FILE) -> dict[str, str]:
    """Normalised course name → CRICOS code, for one Australian institution (unique names only)."""
    if not institution or not path.exists():
        return {}
    names: dict[str, list[str]] = {}
    for course in json.loads(path.read_text(encoding="utf-8"))["courses"]:
        if course["institution"] == institution:
            names.setdefault(normalize(course["name"]), []).append(course["code"])
    return {name: codes[0] for name, codes in names.items() if len(codes) == 1}


class _Heading(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.parts: list[str] = []
        self.done = False

    def handle_starttag(self, tag, attrs):
        if tag == "h1" and not self.done:
            self.depth += 1

    def handle_endtag(self, tag):
        if tag == "h1" and self.depth:
            self.depth -= 1
            self.done = self.done or bool("".join(self.parts).strip())

    def handle_data(self, data):
        if self.depth and not self.done:
            self.parts.append(data)


def page_heading(html: str) -> str | None:
    """The page's first non-empty `<h1>`, the program's name as the page itself writes it."""
    parser = _Heading()
    parser.feed(html)
    text = re.sub(r"\s+", " ", "".join(parser.parts)).strip()
    return text if 4 <= len(text) <= 160 else None


def discover_school(session, school_key: str, *, budget, fetch=None, pick=pick_programs, data_dir=None,
                    root=None, can_render: bool | None = None, cap: int | None = None) -> dict:
    """Fetch the school's listings, let the model pick program links, and add a pending row for each.

    Returns a report: listings fetched or refused, links seen, pages added. A refused listing is
    recorded and skipped like any page; nothing is fetched from a host that refused.
    """
    from app.collect import queue
    from app.collect.snapshot import SNAPSHOT_ROOT, Blocked, snapshot
    from app.config import settings

    fetch = fetch or snapshot
    data_dir = data_dir or queue.DATA_DIR
    root = root or SNAPSHOT_ROOT
    can_render = settings.collect_can_render if can_render is None else can_render
    cap = cap or settings.collect_programs_per_school
    schools = queue.load_schools(data_dir)
    school = schools.get(school_key) or {}
    info = {"name": school.get("name_en") or school_key, "country": school.get("country")}
    report = {"school": school_key, "listings": [], "links": 0, "picked": 0, "added": 0, "cost_cny": 0.0}
    existing = {p.url for p in session.scalars(
        queue.select(queue.CollectPage).where(queue.CollectPage.school_key == school_key))}
    links: list[dict] = []
    for url in school.get("listing_urls") or []:
        if not budget.allows():
            report["listings"].append({"url": url, "skipped": "budget reached"})
            continue
        try:
            meta = fetch(url, school_key, render=bool(school.get("render_listing")), root=root)
        except Blocked as blocked:
            report["listings"].append({"url": url, "blocked": str(blocked)[:200]})
            continue
        except Exception as error:  # noqa: BLE001 - one listing failing must not stop the others
            report["listings"].append({"url": url, "error": f"{type(error).__name__}: {str(error)[:200]}"})
            continue
        html = (root / school_key / f"{meta['sha256']}.html").read_text(encoding="utf-8")
        found = listing_links(html, meta.get("final_url") or url)
        if len(candidates(found)) < 5 and can_render and not meta.get("rendered"):
            # A listing built by JavaScript has no links in its HTML: ask Chrome once.
            try:
                meta = fetch(url, school_key, render=True, root=root)
                html = (root / school_key / f"{meta['sha256']}.html").read_text(encoding="utf-8")
                found = listing_links(html, meta.get("final_url") or url)
            except Exception as error:  # noqa: BLE001
                report["listings"].append({"url": url, "render_error": f"{type(error).__name__}: {str(error)[:200]}"})
        report["listings"].append({"url": url, "sha256": meta["sha256"], "links": len(found)})
        links += [link for link in found if link["url"] not in {l["url"] for l in links}]
    shown = candidates(links)
    report["links"] = len(shown)
    picked = []
    if shown and budget.allows():
        picked, usage = pick(shown, info)
        spent = queue.cost_cny(usage)
        budget.add(spent)
        report["cost_cny"] = round(spent, 4)
    report["picked"] = len(picked)
    codes = cricos_courses(school.get("cricos_institution"))
    room = max(0, cap - len(existing))
    for link in picked:
        if link["url"] in existing or room <= 0:
            continue
        queue.upsert_page(session, school_key, link["url"], link["text"],
                          cricos_code=codes.get(normalize(link["text"])), origin="discovered")
        existing.add(link["url"])
        room -= 1
        report["added"] += 1
    session.commit()
    return report
