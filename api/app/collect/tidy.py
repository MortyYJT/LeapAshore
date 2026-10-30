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
MIN_DESCRIPTION = 20
QUEUE_COLLECTOR = "leapashore-queue"
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
    if (len(name) > LONG_NAME and 4 <= len(heading) and normalize(heading) in normalize(name)
            and len(name) - len(heading) >= MIN_DESCRIPTION):
        # What is cut is a description; a short remainder ("(Online)") tells two programs apart.
        return heading
    return name


def heading_of(root: Path, school_key: str, sha: str | None) -> str | None:
    html = root / school_key / f"{sha}.html"
    return page_heading(html.read_text(encoding="utf-8", errors="replace")) if sha and html.exists() else None


def _bare(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.netloc.lower()}{parts.path.rstrip('/')}"


def not_a_program(name: str, url: str, listing_urls: list[str]) -> str | None:
    """Why this page is not one taught master's program, or None when it may be one."""
    query = urlsplit(url).query
    if any(_bare(url) == _bare(listing) for listing in listing_urls) and (not query or "page" in parse_qs(query)):
        return "the listing page itself"
    if NOT_A_MASTER.search(name) and not MASTER.search(name):
        return f"not a taught master's program: {name[:80]}"
    return None


def tidy_file(data: dict, school: dict | None, *, root: Path, cricos=cricos_courses) -> tuple[dict, dict]:
    """A copy of one requirement file with the rules applied, and counts of what changed.

    Only queue-collected programs change. A rename that would give two of them in one file the same
    name is not made (two campuses of one course): both keep their link text, without CSS.
    """
    out = copy.deepcopy(data)
    listings = list((school or {}).get("listing_urls") or []) + list(data.get("listing_urls") or [])
    institution = (school or {}).get("cricos_institution")
    codes = cricos(institution) if institution else {}
    report = {"renamed": 0, "dropped": 0, "cricos_codes": 0}

    def ours(program: dict) -> bool:
        # Others were named and chosen by a person or an agent reading the page, and are already in
        # the catalogue (a rename would change an id under someone's portfolio): left as they are.
        return str(program.get("collector") or "").startswith(QUEUE_COLLECTOR)

    programs = out.get("programs", [])
    names = {}
    for index, program in enumerate(programs):
        if ours(program):
            heading = heading_of(root, data["school_key"], program.get("snapshot_sha256"))
            names[index] = program_name(program["name"], heading)
    taken: dict[str, list[int]] = {}
    for index, name in names.items():
        taken.setdefault(normalize(name), []).append(index)
    for indexes in taken.values():
        if len(indexes) > 1:
            for index in indexes:
                names[index] = program_name(programs[index]["name"], None)

    kept = []
    for index, program in enumerate(programs):
        if index not in names:
            kept.append(program)
            continue
        if names[index] != program["name"]:
            program["name"] = names[index]
            report["renamed"] += 1
        if not_a_program(program["name"], program["url"], listings):
            report["dropped"] += 1
            continue
        code = codes.get(normalize(program["name"]))
        if institution and not program.get("cricos_code") and code:
            program["cricos_code"] = code
            report["cricos_codes"] += 1
        kept.append(program)
    out["programs"] = kept
    summary = out.get("verification")
    if report["dropped"] and isinstance(summary, dict) and "programs" in summary:
        summary["programs"] = len(kept)
        for status in ("机器核对", "待人工"):
            if status in summary:
                summary[status] = sum((p.get("status") == "机器核对") == (status == "机器核对") for p in kept)
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
            path.write_text(json.dumps(tidied, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
