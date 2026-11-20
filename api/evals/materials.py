"""Score a material extraction against a labelled set (`docs/product/PRD-multi-device.md`, 3.7).

    python -m evals.materials --template --program <id>... [--school <key>...] [--out FILE]
    python -m evals.materials --check [--set FILE]
    python -m evals.materials --score [--set FILE] [--out FILE]
    python -m evals.materials --replay FILE

No model is called by any of these. The extraction itself is done by whoever reads the stored pages
(`python -m app.collect.material_extract`); this module only compares what the requirement files then
hold with what a labeller says each page asks for.

The labelled set (``materials_gold.json`` beside this file; the first one covers 11 programs and was
labelled by a model, not a person):

    {"version": 1,
     "labeller": "<who labelled, and that they did not see any extractor's output>",
     "labelled_at": "2026-11-21",
     "programs": [
       {"program_id": "<catalogue id>", "school_key": "<file key>", "url": "<the page>",
        "snapshot_sha256": "<the snapshot that was read>",
        "materials": [{"type": "recommendation", "count": 2, "quote": "<verbatim from the snapshot>"}]}]}

- ``materials`` lists every material the page asks an applicant to send, one entry per requirement,
  with a type from ``app.collect.materials.MATERIAL_TYPES``. ``[]`` is a label too: the page was read
  and asks for none. ``null`` means not labelled yet, and ``--check`` fails on it.
- ``count`` is given only when the page states a number, as the extraction rule has it.
- ``quote`` is the sentence the label rests on. Where the snapshot store is present, ``--check`` holds
  a label to the same checks as an extracted entry (quote verbatim, count inside the quote).

How a set is labelled blind: ``--template`` writes the programs with their page and snapshot and
nothing else, the labeller reads each page with ``python -m app.collect.material_extract text <id>``
(which prints no extraction state) and fills ``materials`` in. The labeller does not open the
requirement files, whose ``materials`` blocks are the extractor's output.

What ``--score`` measures. A program is scored when the requirement file holds an extraction for it
made from the same snapshot the label was written from; otherwise it is counted as ``not_extracted``
or ``snapshot_differs`` and left out of every rate. The unit is the pair (program, material type):

- precision = pairs both in the extraction and in the labels / pairs in the extraction;
- recall = the same numerator / pairs in the labels;
- count agreement, over the pairs in both where either side states a count = the share whose counts
  are the same (as a sorted list, so two entries of one type are compared together);
- ``empty_pages``: of the programs labelled as asking for nothing, how many the extraction also has
  as empty.

Only entries that passed `verify` are in the extraction: a refused entry was never shown to anybody.
``--replay`` recomputes all of this from the rows a recorded score kept and exits 1 if it differs.
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from app.collect import materials
from app.collect.importer import program_id_for
from app.collect.snapshot import SNAPSHOT_ROOT
from app.collect.text import normalize
from app.collect.verify import SHA

HERE = Path(__file__).resolve().parent
GOLD = HERE / "materials_gold.json"
DATA_DIR = HERE.parent / "data" / "requirements"
VERSION = 1
SCORED, NOT_EXTRACTED, SNAPSHOT_DIFFERS, NOT_ON_FILE = "scored", "not_extracted", "snapshot_differs", "not_on_file"


def _programs_on_file(data_dir: Path, schools: list[str] | None = None) -> dict[str, tuple[str, dict]]:
    """Every program of the requirement files by catalogue id: (school key, program)."""
    found: dict[str, tuple[str, dict]] = {}
    paths = [data_dir / f"{key}.json" for key in schools] if schools else sorted(
        path for path in data_dir.glob("*.json") if not path.name.startswith("_"))
    for path in paths:
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for program in data.get("programs", []):
            found.setdefault(program_id_for(data["school_key"], program), (data["school_key"], program))
    return found


def template(data_dir: Path, program_ids: list[str], schools: list[str] | None = None) -> dict:
    """An unlabelled set for these programs: their page and snapshot, and no extractor output."""
    on_file = _programs_on_file(data_dir, schools)
    ids = list(dict.fromkeys(program_ids)) or list(on_file)
    missing = [pid for pid in ids if pid not in on_file]
    if missing:
        raise ValueError(f"not in any requirement file: {', '.join(missing)}")
    return {
        "version": VERSION, "labeller": None, "labelled_at": None,
        "programs": [{"program_id": pid, "school_key": on_file[pid][0], "url": on_file[pid][1]["url"],
                      "snapshot_sha256": on_file[pid][1]["snapshot_sha256"], "materials": None} for pid in ids],
    }


def check_set(gold, root: Path | None = SNAPSHOT_ROOT) -> tuple[list[str], dict]:
    """What is wrong with a labelled set (empty when nothing is), and how much of it could be checked
    against stored pages."""
    problems: list[str] = []
    counts = {"programs": 0, "labels": 0, "quotes_checked": 0, "quotes_not_checked": 0}
    if not isinstance(gold, dict) or gold.get("version") != VERSION or not isinstance(gold.get("programs"), list):
        return [f"the set must be an object with version {VERSION} and a programs list"], counts
    if not str(gold.get("labeller") or "").strip():
        problems.append("labeller is empty: say who labelled the set")
    seen: set[str] = set()
    for index, program in enumerate(gold["programs"]):
        where = f"programs[{index}]"
        if not isinstance(program, dict):
            problems.append(f"{where} is not an object")
            continue
        pid = program.get("program_id")
        where = f"{where} ({pid})"
        if not pid or not program.get("school_key"):
            problems.append(f"{where} needs program_id and school_key")
        if pid in seen:
            problems.append(f"{where} is listed twice")
        seen.add(pid)
        sha = str(program.get("snapshot_sha256") or "")
        if not SHA.match(sha):
            problems.append(f"{where} snapshot_sha256 is not a sha256")
        labels = program.get("materials")
        if labels is None:
            problems.append(f"{where} is not labelled (materials is null)")
            continue
        if not isinstance(labels, list):
            problems.append(f"{where} materials must be a list")
            continue
        counts["programs"] += 1
        path = (root / str(program.get("school_key")) / f"{sha}.txt") if root and SHA.match(sha) else None
        text = normalize(path.read_text(encoding="utf-8")) if path and path.exists() else None
        for number, label in enumerate(labels):
            counts["labels"] += 1
            problem = materials.shape_problem(label)
            if problem is None and text is not None:
                problem = "; ".join(materials.check_material(label, text)) or None
            counts["quotes_checked" if text is not None else "quotes_not_checked"] += 1
            if problem:
                problems.append(f"{where} materials[{number}]: {problem}")
    return problems, counts


def _pairs(items: list[dict]) -> list[list]:
    """`[type, count]` per entry, sorted: what a row of a score keeps."""
    return sorted(([item["type"], item.get("count")] for item in items), key=lambda pair: (pair[0], pair[1] or 0))


def rows_of(gold: dict, data_dir: Path) -> list[dict]:
    """One row per labelled program: its state, what the labels say and what the extraction holds."""
    schools = sorted({str(program.get("school_key")) for program in gold["programs"]})
    on_file = _programs_on_file(data_dir, schools)
    rows = []
    for labelled in gold["programs"]:
        pid = labelled["program_id"]
        row = {"program_id": pid, "gold": _pairs(labelled["materials"]), "predicted": []}
        entry = on_file.get(pid)
        if entry is None:
            row["state"] = NOT_ON_FILE
        elif not materials.extracted(entry[1]):
            row["state"] = NOT_EXTRACTED
        elif (materials.block_of(entry[1]).get("snapshot_sha256") or entry[1]["snapshot_sha256"]) != labelled["snapshot_sha256"]:
            row["state"] = SNAPSHOT_DIFFERS
        else:
            row["state"] = SCORED
            row["predicted"] = _pairs(materials.accepted_items(entry[1]))
        rows.append(row)
    return rows


def _rate(numerator: int, denominator: int) -> float | None:
    """A share to four places; None when there is nothing to take a share of."""
    return round(numerator / denominator, 4) if denominator else None


def metrics(rows: list[dict]) -> dict:
    """Every number of a score, from its rows alone."""
    states = {state: sum(row["state"] == state for row in rows) for state in (SCORED, NOT_EXTRACTED, SNAPSHOT_DIFFERS, NOT_ON_FILE)}
    by_type = {kind: {"gold": 0, "predicted": 0, "both": 0} for kind in materials.MATERIAL_TYPES}
    count_pairs = count_agree = empty_gold = empty_both = 0
    for row in rows:
        if row["state"] != SCORED:
            continue
        gold: dict[str, list] = {}
        predicted: dict[str, list] = {}
        for kind, count in row["gold"]:
            gold.setdefault(kind, []).append(count)
        for kind, count in row["predicted"]:
            predicted.setdefault(kind, []).append(count)
        if not gold:
            empty_gold += 1
            empty_both += not predicted
        for kind in by_type:
            by_type[kind]["gold"] += kind in gold
            by_type[kind]["predicted"] += kind in predicted
            if kind in gold and kind in predicted:
                by_type[kind]["both"] += 1
                if any(count is not None for count in gold[kind] + predicted[kind]):
                    count_pairs += 1
                    count_agree += sorted(gold[kind], key=lambda c: c or 0) == sorted(predicted[kind], key=lambda c: c or 0)
    total = {key: sum(numbers[key] for numbers in by_type.values()) for key in ("gold", "predicted", "both")}
    return {
        "programs": states,
        "pairs": total,
        "precision": _rate(total["both"], total["predicted"]),
        "recall": _rate(total["both"], total["gold"]),
        "count_agreement": {"pairs": count_pairs, "agree": count_agree, "rate": _rate(count_agree, count_pairs)},
        "empty_pages": {"labelled_empty": empty_gold, "extracted_empty_too": empty_both},
        "by_type": {kind: {**numbers, "precision": _rate(numbers["both"], numbers["predicted"]),
                           "recall": _rate(numbers["both"], numbers["gold"])}
                    for kind, numbers in by_type.items() if numbers["gold"] or numbers["predicted"]},
    }


def score(gold: dict, data_dir: Path = DATA_DIR, today: date | None = None, set_name: str | None = None) -> dict:
    rows = rows_of(gold, data_dir)
    return {"set": set_name, "labeller": gold.get("labeller"), "labelled_at": gold.get("labelled_at"),
            "scored_at": (today or date.today()).isoformat(), "metrics": metrics(rows), "rows": rows}


def replay(path: Path) -> tuple[dict, bool]:
    """The metrics recomputed from a recorded score's rows, and whether they are the recorded ones."""
    recorded = json.loads(path.read_text(encoding="utf-8"))
    again = metrics(recorded["rows"])
    return again, again == recorded["metrics"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--template", action="store_true", help="write an unlabelled set for the programs named")
    mode.add_argument("--check", action="store_true", help="the labelled set is well-formed and its quotes are on their pages")
    mode.add_argument("--score", action="store_true", help="compare the requirement files with the labels")
    mode.add_argument("--replay", type=Path, help="recompute the metrics of a recorded score")
    parser.add_argument("--set", type=Path, default=GOLD, dest="gold")
    parser.add_argument("--program", action="append", default=[])
    parser.add_argument("--school", action="append", default=[])
    parser.add_argument("--out", type=Path)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR, help=argparse.SUPPRESS)
    parser.add_argument("--root", type=Path, default=SNAPSHOT_ROOT, help="the snapshot store, for --check")
    args = parser.parse_args(argv)

    def emit(value: dict) -> None:
        text = json.dumps(value, ensure_ascii=False, indent=1)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text + "\n", encoding="utf-8")
        print(text)

    if args.replay:
        again, same = replay(args.replay)
        print(json.dumps({"metrics": again, "matches_recorded": same}, ensure_ascii=False, indent=1))
        return 0 if same else 1
    if args.template:
        if not args.program and not args.school:
            parser.error("--template needs --program or --school")
        try:
            emit(template(args.data_dir, args.program, args.school or None))
        except ValueError as error:
            print(json.dumps({"error": str(error)}, ensure_ascii=False))
            return 2
        return 0
    if not args.gold.exists():
        print(json.dumps({"error": f"no labelled set at {args.gold.name}: nothing has been labelled yet"}, ensure_ascii=False))
        return 2
    gold = json.loads(args.gold.read_text(encoding="utf-8"))
    problems, counts = check_set(gold, args.root)
    if args.check or problems:
        print(json.dumps({"set": args.gold.name, **counts, "problems": problems}, ensure_ascii=False, indent=1))
        return 1 if problems else 0
    result = score(gold, args.data_dir, set_name=args.gold.name)
    if args.out:
        emit(result)
    else:
        print(json.dumps({key: value for key, value in result.items() if key != "rows"}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
