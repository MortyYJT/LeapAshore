"""Measure the extractor's rejection rate on schools that were already collected.

    python -m evals.extract_rejection [--per-school 10] [--budget-cny 5] [--out evals/results/extract-<date>.json]

For each school in `SAMPLE`, the first `--per-school` programs of its requirement file (file order,
one per snapshot) are extracted again from their local snapshots by `app.collect.extract`. Reported:

- rejection rate: values `verify` (or the pre-check) dropped / values the model returned (extra
  academic routes the file has no room for are counted apart, as `unused`);
- reasons, grouped (quote not on the page, number not in quote, deadline, pre-check);
- coverage against the existing file: of the values the earlier collection took from the same page
  (no `source_sha256`) and that passed, how many the extractor also returned and kept, and whether the
  numbers agree;
- tokens and an upper-bound cost at DeepSeek's peak price.

The schools' snapshots are local only (`api/var/snapshots/`), so this runs on a collector's machine,
never in CI. It calls the advisor's model (`CHAT_*`); a run stops before the next call once the cost
so far passes `--budget-cny`.
"""

import argparse
import json
import sys
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import asdict
from datetime import date
from pathlib import Path

from app.collect.extract import DATA_DIR, extract_snapshot
from app.collect.snapshot import SNAPSHOT_ROOT
from app.collect.verify import LIST_FIELDS
from app.config import settings

# Ten schools in ten countries, chosen for the spread of page styles and date orders (month-first US,
# either-order Canada, German- and Korean-language sites), each with at least ten programs on file.
SAMPLE = (
    "australian-national-university",
    "brown-university",
    "chinese-university-of-hong-kong",
    "eth-zurich",
    "imperial-college-london",
    "korea-university",
    "nanyang-technological-university-singapore",
    "technical-university-of-munich",
    "university-of-toronto",
    "universiti-malaya",
)

# CNY per million tokens, deepseek-flash at peak hours (api-docs.deepseek.com/zh-cn/quick_start/pricing,
# read 2026-10-30). Off-peak is half; the cost reported here is the upper bound.
PRICE_CACHE_HIT = 0.04
PRICE_CACHE_MISS = 2.0
PRICE_OUTPUT = 8.0
NUMBERS = ("overall", "min_band", "min_mark_211", "min_mark_other")


def cost_cny(usage: dict) -> float:
    hit = usage.get("cache_read_tokens", 0)
    miss = usage.get("input_tokens", 0) - hit
    return (hit * PRICE_CACHE_HIT + miss * PRICE_CACHE_MISS + usage.get("output_tokens", 0) * PRICE_OUTPUT) / 1e6


def reason_group(reason: str) -> str:
    if reason.startswith("quote not found"):
        return "quote not on the page"
    if reason.startswith("deadline"):
        return "deadline not as quoted"
    if "not in quote" in reason:
        return "number not in its quote"
    if reason == "snapshot missing":
        return "snapshot missing"
    return "pre-check (no quote / zero / bad date / no value)"


def items(fields: dict):
    for name, value in fields.items():
        for item in value if name in LIST_FIELDS else [value]:
            yield name, item


def sample_programs(school_key: str, per_school: int) -> tuple[dict, list[dict]]:
    data = json.loads((DATA_DIR / f"{school_key}.json").read_text(encoding="utf-8"))
    chosen, seen = [], set()
    for program in data["programs"]:
        sha = program["snapshot_sha256"]
        if sha in seen or not (SNAPSHOT_ROOT / school_key / f"{sha}.txt").exists():
            continue
        seen.add(sha)
        chosen.append(program)
        if len(chosen) == per_school:
            break
    return data, chosen


def coverage(old: dict, new: dict) -> dict:
    """Compare with the earlier collection, on the values it took from this same page and kept."""
    same_page = [(n, i) for n, i in items(old) if i.get("check") == "ok" and not i.get("source_sha256")]
    single = {n: i for n, i in same_page if n not in LIST_FIELDS}
    found = sum(1 for n in single if n in new)
    found += sum(min(len([i for m, i in same_page if m == n]), len(new.get(n, []))) for n in LIST_FIELDS)
    compared = agreed = 0
    for name, item in single.items():
        if name not in new:
            continue
        for key in NUMBERS:
            if item.get(key) is not None and new[name].get(key) is not None:
                compared += 1
                agreed += float(item[key]) == float(new[name][key])
    return {"earlier_same_page": len(same_page), "also_extracted": found,
            "numbers_compared": compared, "numbers_agree": agreed}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--per-school", type=int, default=10)
    parser.add_argument("--budget-cny", type=float, default=5.0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--out", type=Path, default=Path("evals/results") / f"extract-{date.today().isoformat()}.json")
    args = parser.parse_args(argv)

    jobs = []
    for school_key in SAMPLE:
        data, programs = sample_programs(school_key, args.per_school)
        jobs += [(data, program) for program in programs]

    spent = 0.0
    rows: list[dict | None] = [None] * len(jobs)

    def one(job):
        data, program = job
        try:
            result = extract_snapshot(data["school_key"], program["snapshot_sha256"], program_name=program["name"],
                                      school_name=data["school_name_en"], country=data.get("country"),
                                      url=program["url"])
        except Exception as error:  # noqa: BLE001 - one failed call is a row, not the end of the run
            return {"school": data["school_key"], "program": program["name"], "error": repr(error)}
        kept = sum(1 for _ in items(result.program["fields"]))
        return {
            "school": data["school_key"], "program": program["name"], "snapshot_sha256": program["snapshot_sha256"],
            "model": result.model, "usage": result.usage, "truncated": result.truncated, "error": result.error,
            "kept": kept, "fields": result.program["fields"], "rejected": result.rejected,
            "unused": result.unused, "attempts": result.attempts,
            "status": result.program["status"],
            "coverage": coverage(program["fields"], result.program["fields"]),
        }

    # At most `workers` calls in flight, and a new one starts only while the cost so far is within the
    # budget, so a run overshoots it by at most the calls already running.
    pending = list(enumerate(jobs))
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        running = {}
        while pending or running:
            while pending and len(running) < args.workers and spent <= args.budget_cny:
                index, job = pending.pop(0)
                running[pool.submit(one, job)] = index
            if not running:
                break
            finished, _ = wait(running, return_when=FIRST_COMPLETED)
            for future in finished:
                row = rows[running.pop(future)] = future.result()
                if "usage" in row:
                    spent += cost_cny(row["usage"])
                print(f"{row['school'][:28]:28} {row['program'][:50]:50} kept={row.get('kept')} "
                      f"rejected={len(row.get('rejected', []))} {row.get('error') or ''}", flush=True)
    for index, (data, program) in pending:
        rows[index] = {"school": data["school_key"], "program": program["name"], "skipped": "budget"}

    done = [r for r in rows if "usage" in r]
    kept = sum(r["kept"] for r in done)
    rejected = [x for r in done for x in r["rejected"]]
    usage = {key: sum(r["usage"][key] for r in done) for key in ("input_tokens", "output_tokens", "cache_read_tokens")}
    cov = {key: sum(r["coverage"][key] for r in done) for key in done[0]["coverage"]} if done else {}
    summary = {
        "date": date.today().isoformat(),
        "endpoint": settings.chat_base_url,
        "model_requested": settings.chat_model,
        "models_reported": sorted({r["model"] for r in done if r["model"]}),
        "schools": list(SAMPLE),
        "programs_attempted": len(jobs),
        "programs_extracted": len(done),
        "call_errors": [r for r in rows if "usage" not in r and "skipped" not in r],
        "skipped_for_budget": sum(1 for r in rows if "skipped" in r),
        "answer_errors": sum(1 for r in done if r["error"]),
        "truncated_pages": sum(1 for r in done if r["truncated"]),
        "values_returned": kept + len(rejected),
        "values_kept": kept,
        "values_rejected": len(rejected),
        "values_unused": sum(len(r["unused"]) for r in done),
        "retried_calls": sum(r["attempts"] - 1 for r in done),
        "rejection_rate": round(len(rejected) / (kept + len(rejected)), 4) if kept + len(rejected) else None,
        "rejected_by_reason": dict(Counter(reason_group(x["reason"]) for x in rejected).most_common()),
        "rejected_by_field": dict(Counter(x["field"] for x in rejected).most_common()),
        "programs_machine_checked": sum(1 for r in done if r["status"] == "机器核对"),
        "coverage_vs_earlier": cov,
        "usage": usage,
        "cost_cny_upper_bound": round(sum(cost_cny(r["usage"]) for r in done), 4),
        "price_cny_per_million": {"cache_hit": PRICE_CACHE_HIT, "cache_miss": PRICE_CACHE_MISS, "output": PRICE_OUTPUT},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"summary": summary, "programs": rows}, ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
