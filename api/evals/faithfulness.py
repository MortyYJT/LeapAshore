"""Measure the summary faithfulness check (`app.collect.faithful`) against AI labels.

    python -m evals.faithfulness --sample                 # draw the 100 fields (seeded) from the files
    python -m evals.faithfulness --check                  # every sampled field and sentence is labelled
    python -m evals.faithfulness --live [--budget-cny 2]  # judge them with the model in CHAT_*
    python -m evals.faithfulness --replay FILE            # no model: recompute the metrics

Two sets, both labelled by a Claude subagent that never saw the judge's verdicts:

- ``fields``: 100 requirement fields drawn with ``random.Random(SEED)`` from every item of
  ``api/data/requirements`` whose quote passed ``verify`` and that states something beyond its quote
  (the population the backfill judges). Drawn before the backfill wrote any verdict.
- ``sentences``: every sentence the advisor kept in the one recorded snapshot-RAG run
  (``results/passages-2026-10-30.json``), with the quotes and pages it cites.

Labels: ``supported`` (the quote on its own states the claim) or ``unsupported``. ``--live`` judges the
fields one request per program (as the backfill does) and the sentences one request per answer (as the
advisor does), records the function-call arguments, tokens and an upper-bound cost, and ``--replay``
recomputes the metrics from them; CI does this through ``tests/test_faithfulness_eval.py``.

Metrics, per set: blocked (verdict not "ok", including "not checked") / all = block rate; blocked among
``unsupported`` / ``unsupported`` = catch rate; blocked among ``supported`` / ``supported`` = false-block
rate (误伤率); blocked and ``unsupported`` / blocked = precision.
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


def load_set() -> dict:
    return json.loads(SET_FILE.read_text(encoding="utf-8"))


def check_labels(data: dict) -> list[str]:
    problems = []
    for kind in ("fields", "sentences"):
        for row in data.get(kind, []):
            if row.get("label") not in ("supported", "unsupported"):
                problems.append(f"{row['id']}: no label")
    if len(data.get("fields", [])) != SIZE:
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


def replay(path: Path) -> tuple[dict, bool]:
    """Recompute the metrics from a recorded run, re-reading its verdicts from the raw arguments."""
    from app.collect.faithful import Claim, Verdicts, _read

    recorded = json.loads(path.read_text(encoding="utf-8"))
    labels = {r["id"]: r["label"] for kind in ("fields", "sentences") for r in load_set()[kind]}
    again = {}
    for kind in ("fields", "sentences"):
        rows = []
        for call in recorded["calls"][kind]:
            claims = [Claim(id=n, statement="", quotes=[]) for n in range(1, len(call["ids"]) + 1)]
            readable = [raw for raw in call["raw"] if raw is not None]
            verdicts = _read({"parsed": Verdicts.model_validate(readable[0])}, claims) if readable else {}
            for n, row_id in enumerate(call["ids"], 1):
                verdict = verdicts.get(n)
                rows.append({"id": row_id, "label": labels[row_id],
                             "verdict": verdict if verdict is not None else "not checked"})
        again[kind] = metrics(rows)
    return again, again == recorded.get("metrics")


# ---- live --------------------------------------------------------------------------------------------


def run_live(budget_cny: float) -> dict:
    from app.agent.llm import get_chat_model
    from app.collect.faithful import JUDGE_MAX_TOKENS, Claim, cost_cny, judge, program_context

    data = load_set()
    problems = check_labels(data)
    if problems:
        raise SystemExit("labels incomplete: " + "; ".join(problems[:5]))
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

    out = {"date": date.today().isoformat(), "models": sorted(m for m in models if m), "calls": calls}
    out["usage"] = {k: dict(v) for k, v in usage.items()}
    out["cost_cny_upper_bound"] = {k: round(cost_cny(v), 4) for k, v in usage.items()}
    out["seconds_per_call"] = {k: {"median": sorted(v)[len(v) // 2] if v else None, "max": max(v) if v else None,
                                   "calls": len(v)} for k, v in seconds.items()}
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--sample", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--replay", type=Path)
    parser.add_argument("--out", type=Path, default=HERE / "results" / f"faithfulness-{date.today().isoformat()}.json")
    parser.add_argument("--budget-cny", type=float, default=2.0)
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
    if args.check:
        problems = check_labels(load_set())
        print(json.dumps({"problems": problems}, ensure_ascii=False))
        return 1 if problems else 0
    if args.replay:
        again, same = replay(args.replay)
        print(json.dumps({"metrics": again, "same_as_recorded": same}, ensure_ascii=False))
        return 0 if same else 1
    out = run_live(args.budget_cny)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    again, _ = replay(args.out)
    out["metrics"] = again
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"metrics": again, "usage": out["usage"], "cost": out["cost_cny_upper_bound"],
                      "models": out["models"], "seconds": out["seconds_per_call"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
