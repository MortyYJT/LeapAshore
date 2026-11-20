"""The command line of a material extraction (`docs/product/PRD-multi-device.md`, 3.7).

    python -m app.collect.material_extract targets --school <school_key>... [--pending]
    python -m app.collect.material_extract targets --program <program_id>...
    python -m app.collect.material_extract text <program_id> [--school <school_key>] [--full | --lines A:B]
    python -m app.collect.material_extract accept <program_id> --json <file|-> [--school <school_key>]
                                                  [--extractor NAME] [--dry-run]
    python -m app.collect.material_extract status [--school <school_key>...]

No model is called here and no site is fetched. Whoever reads the page (an agent, a person) uses
`targets` to see which programs to read and the snapshot each was checked against, `text` to read one
program's stored page, and `accept` to hand in what the page asks for. `accept` checks every entry
(`app.collect.materials`: the fixed type list, the quote verbatim in the snapshot, a stated count
inside the quote), writes the entries that pass into the school's requirement file and reports the
others with the reason. It never edits a value: an entry is kept as given or refused whole.

Programs are named by their catalogue id (`app.collect.importer.program_id_for`). Snapshot texts are
read from `api/var/snapshots/<school_key>/<sha256>.txt`, or from the store `LEAPASHORE_SNAPSHOT_ROOT`
names.

`accept` takes a JSON object:

    {"snapshot_sha256": "<the sha256 `targets` printed for the program>",
     "materials": [{"type": "recommendation", "count": 2, "note": "…", "quote": "…"}]}

`materials: []` says the page was read and lists no material. Handing a program in again replaces
what was written for it.
"""

import argparse
import fcntl
import json
import sys
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from app.collect import materials
from app.collect.importer import program_id_for
from app.collect.snapshot import SNAPSHOT_ROOT
from app.collect.text import normalize
from app.collect.verify import SHA

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "requirements"
DEFAULT_EXTRACTOR = "agent"
# A page longer than this is printed as the lines around material words unless `--full` is given.
EXCERPT_OVER = 60_000
CONTEXT_LINES = 4
KEYWORDS = (
    "document", "material", "transcript", "reference", "referee", "recommend", "letter", "statement",
    "essay", "cv", "curriculum vitae", "resume", "résumé", "portfolio", "writing sample", "gre", "gmat",
    "ielts", "toefl", "certificate", "upload", "submit", "supporting", "how to apply", "checklist",
    "proof of", "passport", "application form", "research proposal", "interview",
)


class Refused(Exception):
    """A request this tool cannot carry out, with the reason."""


def requirement_files(data_dir: Path, schools: list[str] | None = None) -> list[Path]:
    if schools:
        missing = [key for key in schools if not (data_dir / f"{key}.json").exists()]
        if missing:
            raise Refused(f"no requirement file for {', '.join(missing)}")
        return [data_dir / f"{key}.json" for key in schools]
    return sorted(path for path in data_dir.glob("*.json") if not path.name.startswith("_"))


def _text_path(root: Path, school_key: str, sha: str) -> Path:
    return root / school_key / f"{sha}.txt"


def target_of(school_key: str, program: dict, root: Path) -> dict:
    """One program as `targets` lists it: its id, its page, the snapshot to read, and what is on file."""
    path = _text_path(root, school_key, program["snapshot_sha256"])
    block = materials.block_of(program)
    return {
        "program_id": program_id_for(school_key, program),
        "school_key": school_key,
        "name": program["name"],
        "url": program["url"],
        "snapshot_sha256": program["snapshot_sha256"],
        "snapshot": "ok" if path.exists() else "missing",
        "chars": path.stat().st_size if path.exists() else None,
        "extracted": materials.extracted(program),
        "entries": len(materials.accepted_items(program)) if block else None,
    }


def targets(data_dir: Path, root: Path, schools: list[str] | None = None, program_ids: list[str] | None = None,
            pending: bool = False) -> list[dict]:
    """The programs to read. With ids, those programs in the order given; otherwise every program of
    the schools named. `pending` leaves out the ones already extracted."""
    wanted = list(dict.fromkeys(program_ids or []))
    found: dict[str, dict] = {}
    rows: list[dict] = []
    for path in requirement_files(data_dir, schools if not wanted or schools else None):
        data = json.loads(path.read_text(encoding="utf-8"))
        for program in data.get("programs", []):
            row = target_of(data["school_key"], program, root)
            if wanted:
                if row["program_id"] in wanted:
                    found.setdefault(row["program_id"], row)
            else:
                rows.append(row)
    if wanted:
        rows = [found.get(pid) or {"program_id": pid, "error": "not in any requirement file"} for pid in wanted]
    if pending:
        rows = [row for row in rows if not row.get("extracted")]
    return rows


def locate(data_dir: Path, program_id: str, school: str | None = None) -> tuple[Path, dict, int]:
    """The requirement file, its data and the index of the program with this catalogue id."""
    for path in requirement_files(data_dir, [school] if school else None):
        data = json.loads(path.read_text(encoding="utf-8"))
        for index, program in enumerate(data.get("programs", [])):
            if program_id_for(data["school_key"], program) == program_id:
                return path, data, index
    raise Refused(f"no program {program_id!r} in " + (f"{school}.json" if school else "any requirement file"))


def excerpt(text: str) -> str:
    """The lines around the words a page uses when it lists what to send, with `[...]` between runs."""
    lines = text.split("\n")
    keep = sorted({j for i, line in enumerate(lines) if any(word in line.lower() for word in KEYWORDS)
                   for j in range(max(0, i - CONTEXT_LINES), min(len(lines), i + CONTEXT_LINES + 1))})
    parts, last = [], None
    for i in keep:
        if last is not None and i != last + 1:
            parts.append("[...]")
        parts.append(lines[i])
        last = i
    return "\n".join(parts)


def page_text(data_dir: Path, root: Path, program_id: str, school: str | None = None, *, full: bool = False,
              lines: tuple[int, int] | None = None) -> tuple[dict, str]:
    """One program's header and the text of its snapshot, as stored: a quote is copied from this."""
    _path, data, index = locate(data_dir, program_id, school)
    program = data["programs"][index]
    row = target_of(data["school_key"], program, root)
    path = _text_path(root, data["school_key"], program["snapshot_sha256"])
    if not path.exists():
        raise Refused(f"snapshot text missing: {data['school_key']}/{program['snapshot_sha256']}.txt is not in the snapshot store")
    text = path.read_text(encoding="utf-8")
    # Without `extracted` and `entries`: a labeller reads the page with this command, and must not
    # learn from it what an extractor found.
    header = {**{key: value for key, value in row.items() if key not in ("extracted", "entries")},
              "school": data.get("school_name_en"), "country": data.get("country"), "view": "full"}
    if lines:
        text = "\n".join(text.split("\n")[lines[0] - 1:lines[1]])
        header["view"] = f"lines {lines[0]}:{lines[1]}"
    elif not full and len(text) > EXCERPT_OVER:
        text = excerpt(text)
        header["view"] = (f"excerpt: the page is {row['chars']} characters, so only the lines around material words "
                          "are shown, with [...] between runs; --full or --lines A:B prints the rest")
    return header, text


@contextmanager
def _locked(path: Path):
    """One writer at a time per requirement file: several extractors may work on one school."""
    lock = path.with_suffix(path.suffix + ".lock")
    with lock.open("w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
            lock.unlink(missing_ok=True)


def judge(submission, program: dict, school_key: str, root: Path) -> tuple[list[dict], list[dict]]:
    """Split a submission's entries into the ones to keep (with `check: ok`) and the refusals.

    Refuses the whole submission when it is not about the snapshot the file cites for the program: the
    reader then read another version of the page, and its quotes would be checked against the wrong text.
    """
    if not isinstance(submission, dict) or not isinstance(submission.get("materials"), list):
        raise Refused('the submission must be an object with a "materials" list')
    sha = submission.get("snapshot_sha256")
    if sha != program["snapshot_sha256"]:
        raise Refused(f"snapshot_sha256 must be {program['snapshot_sha256']} (the snapshot `targets` lists for this "
                      f"program); got {sha!r}")
    cache: dict[str, str | None] = {}

    def text_of(snapshot: str) -> str | None:
        if snapshot not in cache:
            path = _text_path(root, school_key, snapshot)
            cache[snapshot] = normalize(path.read_text(encoding="utf-8")) if path.exists() else None
        return cache[snapshot]

    kept, refused, seen = [], [], {}
    for index, raw in enumerate(submission["materials"]):
        problem = materials.shape_problem(raw)
        item = materials.clean(raw) if isinstance(raw, dict) else raw
        if problem is None:
            source = item.get("source_sha256") or sha
            reasons = materials.check_material(item, text_of(source) if SHA.match(source) else None)
            mark = (item["type"], normalize(item["quote"]))
            if not reasons and mark in seen:
                reasons = [f"same type and quote as entry {seen[mark]}"]
            problem = "; ".join(reasons) or None
        if problem:
            refused.append({"entry": index, "type": raw.get("type") if isinstance(raw, dict) else None, "reason": problem})
            continue
        seen[(item["type"], normalize(item["quote"]))] = index
        if item.get("source_sha256"):
            meta = root / school_key / f"{item['source_sha256']}.json"
            if meta.exists():
                url = json.loads(meta.read_text(encoding="utf-8")).get("final_url")
                if url:
                    item["source_url"] = url
        kept.append({**item, "check": "ok"})
    return kept, refused


def accept(data_dir: Path, root: Path, program_id: str, submission, *, school: str | None = None,
           extractor: str = DEFAULT_EXTRACTOR, today: date | None = None, dry_run: bool = False) -> dict:
    """Check a submission and write what passed into the requirement file. Returns the report."""
    path, _data, _index = locate(data_dir, program_id, school)
    with _locked(path):
        # Read again under the lock: another extractor may have written this file since `locate`.
        data = json.loads(path.read_text(encoding="utf-8"))
        index = next((i for i, p in enumerate(data.get("programs", []))
                      if program_id_for(data["school_key"], p) == program_id), None)
        if index is None:
            raise Refused(f"program {program_id!r} is no longer in {path.name}")
        program = data["programs"][index]
        kept, refused = judge(submission, program, data["school_key"], root)
        block = {
            "snapshot_sha256": program["snapshot_sha256"],
            "extractor": extractor,
            "extracted_at": (today or date.today()).isoformat(),
            "rejected": len(refused),
            "items": kept,
        }
        previous = materials.block_of(program)
        same = previous is not None and {k: v for k, v in previous.items() if k != "extracted_at"} == {
            k: v for k, v in block.items() if k != "extracted_at"}
        report = {
            "program_id": program_id, "school_key": data["school_key"], "name": program["name"],
            "accepted": len(kept), "rejected": refused,
            "extracted": materials.extracted({"materials": block}),
            "written": False,
        }
        if not report["extracted"]:
            report["note"] = "every entry was refused: the program stays not extracted until an entry passes"
        if same:
            report["note"] = "the file already holds exactly this"
        elif not dry_run:
            program["materials"] = block
            path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            report["written"] = True
        return report


def status(data_dir: Path, schools: list[str] | None = None) -> dict:
    """How far the extraction has got, counted from the files."""
    programs = extracted = with_entries = entries = refused_only = 0
    by_type: dict[str, int] = {}
    for path in requirement_files(data_dir, schools):
        for program in json.loads(path.read_text(encoding="utf-8")).get("programs", []):
            programs += 1
            block = materials.block_of(program)
            if block is None:
                continue
            if not materials.extracted(program):
                refused_only += 1
                continue
            extracted += 1
            items = materials.accepted_items(program)
            with_entries += bool(items)
            entries += len(items)
            for item in items:
                by_type[item["type"]] = by_type.get(item["type"], 0) + 1
    return {"programs": programs, "extracted": extracted, "with_entries": with_entries,
            "page_lists_none": extracted - with_entries, "refused_only": refused_only,
            "entries": entries, "by_type": dict(sorted(by_type.items()))}


def _lines(value: str) -> tuple[int, int]:
    try:
        first, last = (int(part) for part in value.split(":"))
    except ValueError as error:
        raise argparse.ArgumentTypeError("write --lines as A:B, for example 120:180") from error
    if first < 1 or last < first:
        raise argparse.ArgumentTypeError("--lines A:B needs 1 <= A <= B")
    return first, last


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR, help=argparse.SUPPRESS)
    parser.add_argument("--root", type=Path, default=SNAPSHOT_ROOT, help="the snapshot store (default: LEAPASHORE_SNAPSHOT_ROOT or api/var/snapshots)")
    commands = parser.add_subparsers(dest="command", required=True)

    listing = commands.add_parser("targets", help="list programs to read, one JSON object per line")
    listing.add_argument("--school", action="append", default=[])
    listing.add_argument("--program", action="append", default=[])
    listing.add_argument("--pending", action="store_true", help="only programs not extracted yet")

    reading = commands.add_parser("text", help="print one program's stored page text")
    reading.add_argument("program_id")
    reading.add_argument("--school")
    view = reading.add_mutually_exclusive_group()
    view.add_argument("--full", action="store_true", help="the whole text, however long")
    view.add_argument("--lines", type=_lines, metavar="A:B")

    handing = commands.add_parser("accept", help="check a submission and write what passes")
    handing.add_argument("program_id")
    handing.add_argument("--json", required=True, dest="source", help="a file, or - for standard input")
    handing.add_argument("--school")
    handing.add_argument("--extractor", default=DEFAULT_EXTRACTOR)
    handing.add_argument("--dry-run", action="store_true", help="check and report, write nothing")

    counting = commands.add_parser("status", help="count what the files hold")
    counting.add_argument("--school", action="append", default=[])

    args = parser.parse_args(argv)
    try:
        if args.command == "targets":
            if not args.school and not args.program:
                parser.error("targets needs --school or --program")
            for row in targets(args.data_dir, args.root, args.school or None, args.program or None, args.pending):
                print(json.dumps(row, ensure_ascii=False))
        elif args.command == "text":
            header, text = page_text(args.data_dir, args.root, args.program_id, args.school, full=args.full, lines=args.lines)
            print(json.dumps(header, ensure_ascii=False))
            print("-----")
            print(text)
        elif args.command == "accept":
            raw = sys.stdin.read() if args.source == "-" else Path(args.source).read_text(encoding="utf-8")
            try:
                submission = json.loads(raw)
            except json.JSONDecodeError as error:
                raise Refused(f"the submission is not JSON: {error}") from error
            report = accept(args.data_dir, args.root, args.program_id, submission, school=args.school,
                            extractor=args.extractor, dry_run=args.dry_run)
            print(json.dumps(report, ensure_ascii=False, indent=1))
        else:
            print(json.dumps(status(args.data_dir, args.school or None), ensure_ascii=False, indent=1))
    except Refused as error:
        print(json.dumps({"refused": str(error)}, ensure_ascii=False))
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
