"""Measure the summary faithfulness check (`app.collect.faithful`) against AI labels.

    python -m evals.faithfulness --sample                 # draw the 100 fields (seeded) from the files
    python -m evals.faithfulness --sample-v2              # the second set: those 100 + a stratified draw
    python -m evals.faithfulness --check [--set FILE]     # every sampled field and sentence is labelled
    python -m evals.faithfulness --live [--set FILE] [--budget-cny 2]  # judge them with the model in CHAT_*
    python -m evals.faithfulness --replay FILE            # no model: recompute the metrics

``--check`` and ``--live`` use the second set (``faithfulness_set_v2.json``) unless ``--set`` says
otherwise; a recorded run names the set it was labelled against, and ``--replay`` reads that one.

The first set (``faithfulness_set.json``, 2026-10-30, kept as it was run) has two parts, both labelled by
a Claude subagent that never saw the judge's verdicts:

- ``fields``: 100 requirement fields drawn with ``random.Random(SEED)`` from every item of
  ``api/data/requirements`` whose quote passed ``verify`` and that states something beyond its quote
  (the population the backfill judges). Drawn before the backfill wrote any verdict.
- ``sentences``: every sentence the advisor kept in the one recorded snapshot-RAG run
  (``results/passages-2026-10-30.json``), with the quotes and pages it cites.

The second set (``faithfulness_set_v2.json``, 2026-10-31) exists because 100 random fields held only 27
``unsupported`` ones. It keeps those 100 (the 9 ``china_requirement`` rows relabelled on the claim the
judge is now asked, the earlier claim and label kept beside them) and adds ``PER_FIELD`` fields from
each of the six fields, drawn with ``random.Random(SEED_V2)`` from the same population minus the first
100. Stratifying by field, not by anything the judge said, raises the share of the rarer, more often
unfaithful fields (deadlines, TOEFL, Chinese-applicant marks); the sets' field counts in the population
let ``weighted`` scale each field back to its share. Its new labels were written by Claude from the claim
and quote alone, without the judge's verdicts; no person reviewed them. The sentences are the first set's.

Labels: ``supported`` (the quote on its own states the claim) or ``unsupported``. ``--live`` judges the
fields one request per program (as the backfill does) and the sentences one request per answer (as the
advisor does), records the function-call arguments, tokens and an upper-bound cost, and ``--replay``
recomputes the metrics from them; CI does this through ``tests/test_faithfulness_eval.py``.

Metrics, per set: blocked (verdict not "ok", including "not checked") / all = block rate; blocked among
``unsupported`` / ``unsupported`` = catch rate; blocked among ``supported`` / ``supported`` = false-block
rate (误伤率); blocked and ``unsupported`` / blocked = precision. For a set with field counts, the
replay adds the same per field and per sample, and ``weighted``: the rates over the whole population,
each field's rows standing for its share of it.
"""

import argparse
import json
import random
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
SET_FILE = HERE / "faithfulness_set.json"
PASSAGES_RUN = HERE / "results" / "passages-2026-10-30.json"
SEED = 20261030
SIZE = 100
SET_V2 = HERE / "faithfulness_set_v2.json"
SEED_V2 = 20261031
PER_FIELD = 65
FIRST_SAMPLE = f"random-{SEED}"
STRATIFIED_SAMPLE = f"stratified-{SEED_V2}"


# ---- the sets -----------------------------------------------------------------------------------------


def population(data_dir: Path | None = None) -> list[dict]:
    """Every judgeable item of the requirement files, in a fixed order."""
    from app.collect.faithful import requirement_files, statement
    from app.collect.verify import LIST_FIELDS

    out = []
    for path in requirement_files(data_dir) if data_dir else requirement_files():
        data = json.loads(path.read_text(encoding="utf-8"))
        for p_index, program in enumerate(data["programs"]):
            for name, value in program.get("fields", {}).items():
                for i_index, item in enumerate(value if name in LIST_FIELDS else [value]):
                    if item.get("check") != "ok" or statement(name, item) is None:
                        continue
                    out.append({"school_key": data["school_key"], "school_name_en": data["school_name_en"],
                                "program": program["name"], "program_index": p_index, "field": name,
                                "item_index": i_index, "claim": statement(name, item), "quote": item["quote"],
                                "item": {k: v for k, v in item.items() if k not in ("check", "summary_check", "summary_sha")}})
    return out


def draw_fields() -> dict:
    items = population()
    picked = sorted(random.Random(SEED).sample(range(len(items)), SIZE))
    fields = []
    for n, index in enumerate(picked, 1):
        fields.append({"id": f"f{n:03d}", **items[index]})
    return {"seed": SEED, "population": len(items), "drawn_on": date.today().isoformat(), "fields": fields}


def _key(row: dict) -> tuple:
    return (row["school_key"], row["program_index"], row["field"], row["item_index"])


def draw_stratified(items: list[dict], *, seed: int, per_field: int, exclude: set[tuple]) -> list[int]:
    """Indices of `per_field` items of each field (all of a field's items when it has fewer), drawn with
    `random.Random(seed)` field by field in name order, leaving out the items whose key is in `exclude`."""
    groups = defaultdict(list)
    for index, item in enumerate(items):
        if _key(item) not in exclude:
            groups[item["field"]].append(index)
    rng = random.Random(seed)
    picked = []
    for name in sorted(groups):
        pool = groups[name]
        picked += rng.sample(pool, min(per_field, len(pool)))
    return sorted(picked)


def draw_v2() -> dict:
    """The second set: the first set's fields (china rows relabelled later) plus a stratified draw."""
    from app.collect.faithful import statement

    first = load_set(SET_FILE)
    items = population()
    rows = []
    for row in first["fields"]:
        row = {**row, "sample": FIRST_SAMPLE}
        now = statement(row["field"], row["item"])
        if now != row["claim"]:
            # Asked differently now: keep what was labelled, and label the current claim afresh.
            row = {**row, "claim_2026_10_30": row["claim"], "label_2026_10_30": row["label"],
                   "label_note_2026_10_30": row.get("label_note", ""), "claim": now, "label": None,
                   "label_note": ""}
        rows.append(row)
    picked = draw_stratified(items, seed=SEED_V2, per_field=PER_FIELD, exclude={_key(r) for r in first["fields"]})
    for n, index in enumerate(picked, 1):
        rows.append({"id": f"s{n:03d}", **items[index], "sample": STRATIFIED_SAMPLE, "label": None, "label_note": ""})
    by_field = defaultdict(int)
    for item in items:
        by_field[item["field"]] += 1
    return {
        "seed": SEED_V2, "per_field": PER_FIELD, "population": len(items),
        "population_by_field": dict(sorted(by_field.items())), "drawn_on": date.today().isoformat(),
        "samples": {FIRST_SAMPLE: {"size": len(first["fields"]), "drawn_on": first["drawn_on"],
                                   "how": f"simple random sample of {SIZE} with random.Random({SEED})"},
                    STRATIFIED_SAMPLE: {"size": len(picked), "drawn_on": date.today().isoformat(),
                                        "how": f"{PER_FIELD} per field with random.Random({SEED_V2}), "
                                               f"fields in name order, the {FIRST_SAMPLE} rows left out"}},
        "fields": rows, "sentences": first["sentences"],
    }


def advisor_sentences() -> list[dict]:
    """The sentences the advisor kept in the recorded passages run, with what they cite."""
    from app.agent.answer import PassageAnswer, _source, verify

    run = json.loads(PASSAGES_RUN.read_text(encoding="utf-8"))
    out = []
    for item in run["items"]:
        if not item.get("arguments"):
            continue
        checked = verify(PassageAnswer.model_validate(item["arguments"]), [p["text"] for p in item["passages"]])
        for n, s in enumerate(checked.kept, 1):
            out.append({"id": f"{item['id']}-s{n}", "question_id": item["id"], "question": item["question"],
                        "sentence_index": n, "claim": s.text,
                        "quotes": [{"source": _source(item["passages"][p - 1]), "quote": q} for p, q in s.quotes]})
    return out


def load_set(path: Path = SET_FILE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def stale_claims(data: dict) -> list[str]:
    """Sampled fields whose claim, as the judge would now be asked it, differs from the one labelled.

    The china_requirement wording changed after the 2026-10-30 run (review of #62): those labels are
    about the old sentence, so a new live run needs them relabelled first.
    """
    from app.collect.faithful import statement

    return [r["id"] for r in data.get("fields", []) if statement(r["field"], r["item"]) != r["claim"]]


def check_labels(data: dict) -> list[str]:
    problems = []
    for kind in ("fields", "sentences"):
        for row in data.get(kind, []):
            if row.get("label") not in ("supported", "unsupported"):
                problems.append(f"{row['id']}: no label")
    if "samples" in data:
        for name, spec in data["samples"].items():
            got = sum(1 for r in data.get("fields", []) if r.get("sample") == name)
            if got != spec["size"]:
                problems.append(f"{name}: {got} rows, expected {spec['size']}")
    elif len(data.get("fields", [])) != SIZE:
        problems.append(f"fields: {len(data.get('fields', []))} rows, expected {SIZE}")
    return problems


# ---- scoring (no model) ----------------------------------------------------------------------------


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def metrics(rows: list[dict]) -> dict:
    """Block, catch and false-block rates of recorded verdicts against labels."""
    blocked = [r for r in rows if r.get("verdict") != "ok"]
    bad = [r for r in rows if r["label"] == "unsupported"]
    good = [r for r in rows if r["label"] == "supported"]
    caught = [r for r in blocked if r["label"] == "unsupported"]
    false_blocks = [r for r in blocked if r["label"] == "supported"]
    return {
        "n": len(rows), "labelled_unsupported": len(bad), "labelled_supported": len(good),
        "blocked": len(blocked), "block_rate": _rate(len(blocked), len(rows)),
        "caught": len(caught), "catch_rate": _rate(len(caught), len(bad)),
        "false_blocks": len(false_blocks), "false_block_rate": _rate(len(false_blocks), len(good)),
        "precision": _rate(len(caught), len(blocked)),
        "not_checked": sum(1 for r in rows if (r.get("verdict") or "").startswith("not checked")),
        "false_block_ids": sorted(r["id"] for r in false_blocks),
        "missed_ids": sorted(r["id"] for r in bad if r not in caught),
    }


def breakdown(rows: list[dict], key: str) -> dict:
    """`metrics` of each group of rows sharing `key`."""
    groups = defaultdict(list)
    for row in rows:
        groups[row[key]].append(row)
    return {name: metrics(group) for name, group in sorted(groups.items())}


def weighted(rows: list[dict], population_by_field: dict[str, int]) -> dict:
    """Rates over the population: each sampled row of a field stands for population / sampled of it."""
    sampled = defaultdict(int)
    for row in rows:
        sampled[row["field"]] += 1
    total = bad = good = blocked = caught = false_blocks = 0.0
    for row in rows:
        w = population_by_field[row["field"]] / sampled[row["field"]]
        is_blocked = row.get("verdict") != "ok"
        total += w
        blocked += w * is_blocked
        if row["label"] == "unsupported":
            bad += w
            caught += w * is_blocked
        else:
            good += w
            false_blocks += w * is_blocked

    def rate(num: float, den: float) -> float | None:
        return round(num / den, 4) if den else None

    return {"unsupported_share": rate(bad, total), "block_rate": rate(blocked, total),
            "catch_rate": rate(caught, bad), "false_block_rate": rate(false_blocks, good),
            "precision": rate(caught, blocked)}


def replay(path: Path) -> tuple[dict, bool]:
    """Recompute the metrics from a recorded run, re-reading its verdicts from the raw arguments."""
    from app.collect.faithful import Claim, Verdicts, _read

    recorded = json.loads(path.read_text(encoding="utf-8"))
    data = load_set(HERE / recorded.get("set", SET_FILE.name))
    rows_by_id = {r["id"]: r for kind in ("fields", "sentences") for r in data[kind]}
    again = {}
    for kind in ("fields", "sentences"):
        rows = []
        for call in recorded["calls"][kind]:
            claims = [Claim(id=n, statement="", quotes=[]) for n in range(1, len(call["ids"]) + 1)]
            readable = [raw for raw in call["raw"] if raw is not None]
            verdicts = _read({"parsed": Verdicts.model_validate(readable[0])}, claims) if readable else {}
            for n, row_id in enumerate(call["ids"], 1):
                verdict = verdicts.get(n)
                row = rows_by_id[row_id]
                rows.append({"id": row_id, "label": row["label"], "field": row.get("field"),
                             "sample": row.get("sample"), "verdict": verdict if verdict is not None else "not checked"})
        again[kind] = metrics(rows)
        if kind == "fields" and "population_by_field" in data:
            again["fields_by_field"] = breakdown(rows, "field")
            again["fields_by_sample"] = breakdown(rows, "sample")
            again["fields_weighted"] = weighted(rows, data["population_by_field"])
    return again, again == recorded.get("metrics")


# ---- live --------------------------------------------------------------------------------------------


def run_live(budget_cny: float, set_path: Path = SET_V2) -> dict:
    from app.agent.llm import get_chat_model
    from app.collect.faithful import JUDGE_MAX_TOKENS, Claim, cost_cny, judge, program_context

    data = load_set(set_path)
    problems = check_labels(data) + [f"{i}: claim wording changed since labelling" for i in stale_claims(data)]
    if problems:
        raise SystemExit("labels incomplete or stale: " + "; ".join(problems[:5]))
    model = get_chat_model(temperature=0, max_tokens=JUDGE_MAX_TOKENS)
    usage = {"fields": defaultdict(int), "sentences": defaultdict(int)}
    calls = {"fields": [], "sentences": []}
    models, seconds = set(), {"fields": [], "sentences": []}

    groups = defaultdict(list)
    for row in data["fields"]:
        groups[(row["school_key"], row["program_index"])].append(row)
    jobs = [("fields", rows, program_context({"name": rows[0]["program"]}, rows[0]["school_name_en"]),
             [Claim(id=n, statement=r["claim"], quotes=[(None, r["quote"])], field=r["field"])
              for n, r in enumerate(rows, 1)]) for rows in groups.values()]
    by_question = defaultdict(list)
    for row in data["sentences"]:
        by_question[row["question_id"]].append(row)
    for rows in by_question.values():
        context = (f"The claims are sentences of an answer, in Chinese, to an applicant's question: {rows[0]['question']}\n"
                   "Each quote names the page it was copied from.")
        jobs.append(("sentences", rows, context,
                     [Claim(id=n, statement=r["claim"], quotes=[(q["source"], q["quote"]) for q in r["quotes"]])
                      for n, r in enumerate(rows, 1)]))

    spent = 0.0
    for kind, rows, context, claims in jobs:
        if spent >= budget_cny:
            raise SystemExit(f"budget {budget_cny} CNY reached after {spent:.4f}")
        started = time.time()
        result = judge(claims, context, model)
        seconds[kind].append(round(time.time() - started, 2))
        models.add(result.model)
        for key, value in result.usage.items():
            usage[kind][key] += value
        spent += cost_cny(result.usage)
        calls[kind].append({"ids": [r["id"] for r in rows], "raw": result.raw, "usage": result.usage,
                            "error": result.error})

    out = {"date": date.today().isoformat(), "set": set_path.name, "models": sorted(m for m in models if m), "calls": calls}
    out["usage"] = {k: dict(v) for k, v in usage.items()}
    out["cost_cny_upper_bound"] = {k: round(cost_cny(v), 4) for k, v in usage.items()}
    out["seconds_per_call"] = {k: {"median": sorted(v)[len(v) // 2] if v else None, "max": max(v) if v else None,
                                   "calls": len(v)} for k, v in seconds.items()}
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--sample", action="store_true")
    mode.add_argument("--sample-v2", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--replay", type=Path)
    parser.add_argument("--out", type=Path, default=HERE / "results" / f"faithfulness-{date.today().isoformat()}.json")
    parser.add_argument("--budget-cny", type=float, default=2.0)
    parser.add_argument("--set", type=Path, default=SET_V2, help="the labelled set for --check and --live")
    args = parser.parse_args(argv)
    if args.sample:
        if SET_FILE.exists():
            raise SystemExit(f"{SET_FILE.name} exists: the sample is drawn once")
        data = draw_fields()
        data["sentences"] = advisor_sentences()
        SET_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(json.dumps({"population": data["population"], "fields": len(data["fields"]),
                          "sentences": len(data["sentences"])}))
        return 0
    if args.sample_v2:
        if SET_V2.exists():
            raise SystemExit(f"{SET_V2.name} exists: the sample is drawn once")
        data = draw_v2()
        SET_V2.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(json.dumps({"population": data["population"], "samples": data["samples"],
                          "to_label": sum(1 for r in data["fields"] if r["label"] is None)}))
        return 0
    if args.check:
        problems = check_labels(load_set(args.set))
        stale = stale_claims(load_set(args.set))
        print(json.dumps({"problems": problems, "stale_claims": stale}, ensure_ascii=False))
        return 1 if problems or stale else 0
    if args.replay:
        again, same = replay(args.replay)
        print(json.dumps({"metrics": again, "same_as_recorded": same}, ensure_ascii=False))
        return 0 if same else 1
    out = run_live(args.budget_cny, args.set)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    again, _ = replay(args.out)
    out["metrics"] = again
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"metrics": again, "usage": out["usage"], "cost": out["cost_cny_upper_bound"],
                      "models": out["models"], "seconds": out["seconds_per_call"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
