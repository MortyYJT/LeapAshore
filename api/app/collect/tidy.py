"""Program names and non-program pages from discovery (review of PR #51).

Discovery names a page by its link's text, and the model picks the links. Two kinds of mistakes came
through: link text carrying more than the name (an inline icon's CSS, a card's description, a bare
course code) and links that are not one taught master's program (a bachelor's, "Course Not Found",
the listing itself or another page of it). The rules here fix both, using only what the school's own
pages say: a name is shortened to the page's own heading, never rewritten.

    python -m app.collect.tidy [--apply] [<school_key>...]   (in api/; without --apply it only reports)
"""

import copy
import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from app.collect.discover import cricos_courses, page_heading
from app.collect.text import normalize

CSS_RULE = re.compile(r"\s*\.[\w-]+\s*\{[^{}]*\}")
BARE_CODE = re.compile(r"[A-Z]{1,4}\d{1,4}")
LONG_NAME = 60
MASTER = re.compile(
    r"master|máster|mestrado|magistr|\bm\.?sc\b|\bmba\b|\bm\.?a\.?\b|\bmeng\b|\bllm\b|\bmph\b|석사|碩士|硕士",
    re.IGNORECASE,
)
NOT_A_MASTER = re.compile(
    r"bachelor|associate degree|course not found|page not found|higher degree research|closing dates"
    r"|graduate diploma|graduate certificate|\bph\.?d\b|doctor",
    re.IGNORECASE,
)


def program_name(text: str, heading: str | None) -> str:
    """The program's name: the link text without CSS, cut back to the page's own heading when the
    heading is part of a long link text, or the heading when the link text is only a course code."""
    name = re.sub(r"\s+", " ", CSS_RULE.sub("", text)).strip() or text
    if not heading:
        return name
    heading = re.sub(r"\s+", " ", heading).strip()
    if BARE_CODE.fullmatch(name) and heading.startswith(name):
        return heading
    if len(name) > LONG_NAME and 4 <= len(heading) < len(name) and normalize(heading) in normalize(name):
        return heading
    return name


def _bare(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.netloc.lower()}{parts.path.rstrip('/')}"


def not_a_program(name: str, url: str, listing_urls: list[str]) -> str | None:
    """Why this page is not one taught master's program, or None when it may be one."""
    query = parse_qs(urlsplit(url).query)
    if any(_bare(url) == _bare(listing) for listing in listing_urls) and (not query or "page" in query):
        return "the listing page itself"
    if NOT_A_MASTER.search(name) and not MASTER.search(name):
        return f"not a taught master's program: {name[:80]}"
    return None


def tidy_file(data: dict, school: dict | None, *, root: Path, cricos=cricos_courses) -> tuple[dict, dict]:
    """A copy of one requirement file with the rules applied, and counts of what changed."""
    out = copy.deepcopy(data)
    listings = list((school or {}).get("listing_urls") or []) + list(data.get("listing_urls") or [])
    institution = (school or {}).get("cricos_institution")
    codes = cricos(institution) if institution else {}
    report = {"renamed": 0, "dropped": 0, "cricos_codes": 0}
    kept = []
    for program in out.get("programs", []):
        html = root / data["school_key"] / f"{program.get('snapshot_sha256')}.html"
        heading = page_heading(html.read_text(encoding="utf-8", errors="replace")) if html.exists() else None
        name = program_name(program["name"], heading)
        if name != program["name"]:
            program["name"] = name
            report["renamed"] += 1
        if not_a_program(name, program["url"], listings):
            report["dropped"] += 1
            continue
        if institution and not program.get("cricos_code") and codes.get(normalize(name)):
            program["cricos_code"] = codes[normalize(name)]
            report["cricos_codes"] += 1
        kept.append(program)
    out["programs"] = kept
    return out, report


def main(argv: list[str]) -> int:
    from app.collect.importer import load_schools, requirement_files
    from app.collect.snapshot import SNAPSHOT_ROOT

    apply = "--apply" in argv
    keys = {a for a in argv if not a.startswith("--")}
    schools = load_schools()
    for path in requirement_files():
        data = json.loads(path.read_text(encoding="utf-8"))
        if keys and data["school_key"] not in keys:
            continue
        tidied, report = tidy_file(data, schools.get(data["school_key"]), root=SNAPSHOT_ROOT)
        if not any(report.values()):
            continue
        print(json.dumps({"school": data["school_key"], **report}, ensure_ascii=False))
        if apply:
            path.write_text(json.dumps(tidied, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
