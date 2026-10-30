"""Score the advisor's requirement retrieval and evidence gate, and optionally its intent router.

    python -m evals.run_advisor [--split tune|heldout|all] [--retrieval rules|fts|vector|hybrid]
                                [--details] [--intent] [--out FILE] [--check]

``--retrieval`` picks the ranking inside the named schools (openspec hybrid-retrieval D7); without it
the production setting ``ADVISOR_RETRIEVAL`` is scored. A ranking that needs vectors is refused unless
the question embeds and every program it could return has a vector for the configured model, so a
missing key or an unfinished backfill cannot pass for a vector result.

The retrieval part calls ``app.agent.evidence.gate`` exactly as the graph does and needs no model, so
CI runs it (``--split tune --check``). ``--intent`` calls the production classifier against the chat
model in ``CHAT_*`` and is never run in CI.

Labels live in ``evals/advisor_questions.json``. A question's relevant programs are read from the
database at scoring time from its label (schools, optional ``field`` and ``name`` regex), restricted to
rows that carry requirement data and a citable source. The runner refuses to score a set whose
``answerable`` flags disagree with the database, so a catalogue change cannot silently re-grade it.

Metrics, over the questions whose intent is ``官方要求核验`` (the only ones that reach the gate):

- Recall@K: per answerable question, relevant rows among the K returned / min(K, relevant rows); a
  refused answerable question scores 0. K is the number of rows the gate hands the model.
- Precision@K: per answerable question the gate passed, relevant rows / rows returned.
- false-pass rate (门槛误放率): unanswerable questions the gate let through / unanswerable questions.
- false-block rate (误拦率): answerable questions the gate refused / answerable questions.
- rows read: rows the database returned to Python while gating one question, and statements run.

Intent accuracy is over every question in the split.
"""

import argparse
import asyncio
import inspect
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import event, select

from app.agent import evidence
from app.db import SessionLocal, engine
from app.models.program import Program, ProgramDeadline, ProgramPrerequisite, University
from app.models.source import Source

HERE = Path(__file__).resolve().parent
QUESTIONS_FILE = HERE / "advisor_questions.json"
THRESHOLDS_FILE = HERE / "advisor_thresholds.json"
REQUIREMENT_INTENT = "官方要求核验"


def load_questions(split: str) -> list[dict]:
    rows = json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))["questions"]
    return [q for q in rows if split == "all" or q["split"] == split]


def top_k() -> int:
    """The number of rows the gate hands the model, read from the code rather than restated here."""
    if hasattr(evidence, "TOP_K"):
        return evidence.TOP_K
    return inspect.signature(evidence.search_requirements).parameters["limit"].default


def relevant_ids(session, q: dict) -> set[str]:
    """The programs a labelled question is about, with requirement data and a citable source."""
    if not q["schools"]:
        return set()
    rows = session.execute(
        select(Program.id, Program.name, Program.name_en, Program.field, Program.english_requirement,
               Program.minimum_mark, Program.non_211_minimum_mark, Program.academic_requirement,
               Source.url, Source.title)
        .join(Source, Source.id == Program.source_id)
        .where(Program.university_id.in_(q["schools"]))
    ).all()
    with_prereqs = set(session.scalars(
        select(ProgramPrerequisite.program_id).where(ProgramPrerequisite.program_id.in_([r.id for r in rows]))
    ))
    # An academic requirement or a deadline is requirement data too (openspec requirement-dates D6).
    with_deadlines = set(session.scalars(
        select(ProgramDeadline.program_id).where(ProgramDeadline.program_id.in_([r.id for r in rows]))
    ))
    pattern = re.compile(q["name"], re.IGNORECASE) if q.get("name") else None
    out = set()
    for r in rows:
        if q.get("field") and r.field != q["field"]:
            continue
        if pattern and not pattern.search(f"{r.name_en or ''} {r.name or ''}"):
            continue
        has_data = (r.english_requirement or r.minimum_mark is not None
                    or r.non_211_minimum_mark is not None or r.id in with_prereqs
                    or r.academic_requirement is not None or r.id in with_deadlines)
        citable = bool(r.title) and (r.url or "").startswith("https://")
        if has_data and citable:
            out.add(r.id)
    return out


def validate_labels(session, questions: list[dict]) -> dict[str, set[str]]:
    """Every school id must exist and every answerable flag must match the database. The curated
    short forms are checked here too, because only a full catalogue has every id they name."""
    known = set(session.scalars(select(University.id)))
    relevant, problems = {}, []
    from app.agent import catalog_match

    stale = sorted(set(catalog_match.curated_aliases()) - known)
    if stale:
        problems.append(f"university_aliases.json names ids the catalogue does not hold: {stale}")
    for q in questions:
        if q["intent"] != REQUIREMENT_INTENT:
            continue
        missing = [s for s in q["schools"] if s not in known]
        if missing:
            problems.append(f"{q['id']}: unknown school ids {missing}")
            continue
        relevant[q["id"]] = relevant_ids(session, q)
        if bool(relevant[q["id"]]) != q["answerable"]:
            problems.append(
                f"{q['id']}: labelled answerable={q['answerable']} but the database has "
                f"{len(relevant[q['id']])} relevant rows"
            )
    if problems:
        raise SystemExit("label/database mismatch, refusing to score:\n  " + "\n  ".join(problems))
    return relevant


@dataclass
class QueryCounter:
    """Counts statements and returned rows on the engine while a question is gated."""

    statements: int = 0
    rows: int = 0
    active: bool = False
    _hooked: bool = field(default=False, repr=False)

    def hook(self):
        if self._hooked:
            return

        @event.listens_for(engine, "after_cursor_execute")
        def _count(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
            if self.active:
                self.statements += 1
                if statement.lstrip().upper().startswith(("SELECT", "WITH")) and cursor.rowcount > 0:
                    self.rows += cursor.rowcount

        self._hooked = True


def check_vectors(session, ranking: str) -> None:
    """Refuse a vector ranking that would silently run on full text or on part of the catalogue."""
    from sqlalchemy import func

    from app.agent import embeddings
    from app.config import settings
    from app.models.program import ProgramEmbedding

    if ranking not in ("vector", "hybrid"):
        return
    if embeddings.configured_client() is None:
        raise SystemExit(f"--retrieval {ranking} needs EMBED_API_KEY; not scoring")
    missing = session.scalar(
        select(func.count()).select_from(Program)
        .outerjoin(ProgramEmbedding, (ProgramEmbedding.program_id == Program.id)
                   & (ProgramEmbedding.model == settings.embed_model))
        .where(ProgramEmbedding.program_id.is_(None))
    )
    if missing:
        raise SystemExit(f"{missing} programs have no {settings.embed_model} vector; run "
                         "`python -m app.agent.embeddings` first")


def score_retrieval(questions: list[dict], details: bool, ranking: str | None = None) -> dict:
    from app.config import settings

    ranking = ranking or settings.advisor_retrieval
    k = top_k()
    counter = QueryCounter()
    counter.hook()
    per_question = []
    with SessionLocal() as session:
        relevant = validate_labels(session, questions)
        check_vectors(session, ranking)
    for q in questions:
        if q["intent"] != REQUIREMENT_INTENT:
            continue
        with SessionLocal() as session:
            counter.statements = counter.rows = 0
            counter.active = True
            started = time.perf_counter()
            update = evidence.gate(session, q["question"], ranking=ranking)
            elapsed = time.perf_counter() - started
            counter.active = False
        used = update["trace"]["gate_signals"].get("ranking")
        if q["schools"] and update["trace"]["gate_signals"]["schools"] and used != ranking:
            raise SystemExit(f"{q['id']}: asked for ranking {ranking!r}, the gate used {used!r} "
                             "(the question did not embed)")
        returned = [c["programId"] for c in update.get("citations", [])]
        if len(returned) > k:
            raise SystemExit(f"{q['id']}: the gate returned {len(returned)} rows, more than K={k}")
        rel = relevant[q["id"]]
        passed = bool(update.get("evidence_strong"))
        hit = len(set(returned) & rel)
        per_question.append({
            "id": q["id"], "answerable": q["answerable"], "passed": passed,
            "refusal": update.get("refusal"), "returned": returned, "relevant": len(rel), "hit": hit,
            "recall": (hit / min(k, len(rel)) if passed else 0.0) if rel else None,
            "precision": (hit / len(returned) if returned else 0.0) if (rel and passed) else None,
            "statements": counter.statements, "rows_read": counter.rows, "ms": round(elapsed * 1000, 1),
        })
    answerable = [p for p in per_question if p["answerable"]]
    unanswerable = [p for p in per_question if not p["answerable"]]
    passed_answerable = [p for p in answerable if p["passed"]]

    def mean(values):
        values = list(values)
        return round(sum(values) / len(values), 4) if values else None

    summary = {
        "ranking": ranking,
        "k": k,
        "questions": len(per_question),
        "answerable": len(answerable),
        "unanswerable": len(unanswerable),
        "recall_at_k": mean(p["recall"] for p in answerable),
        "precision_at_k": mean(p["precision"] for p in passed_answerable),
        "false_pass_rate": mean(1.0 if p["passed"] else 0.0 for p in unanswerable),
        "false_block_rate": mean(0.0 if p["passed"] else 1.0 for p in answerable),
        "false_passes": sum(p["passed"] for p in unanswerable),
        "false_blocks": sum(not p["passed"] for p in answerable),
        "mean_rows_read": mean(p["rows_read"] for p in per_question),
        "max_rows_read": max((p["rows_read"] for p in per_question), default=0),
        "mean_statements": mean(p["statements"] for p in per_question),
        "mean_ms": mean(p["ms"] for p in per_question),
    }
    return {"summary": summary, "questions": per_question if details else []}


async def _classify_all(questions: list[dict]) -> tuple[list[dict], dict]:
    from langchain_core.callbacks import get_usage_metadata_callback

    from app.agent import intent

    results = []
    with get_usage_metadata_callback() as usage:
        for q in questions:
            got = await intent.classify(q["question"], "")
            results.append({"id": q["id"], "expected": q["intent"], "got": got["intent"],
                            "confidence": got["confidence"]})
    return results, dict(usage.usage_metadata)


def score_intent(questions: list[dict], details: bool) -> dict:
    from app.config import settings

    results, usage = asyncio.run(_classify_all(questions))
    correct = sum(r["expected"] == r["got"] for r in results)
    # A classifier error falls back to 通用问答 with confidence 0; count those, or a dead key reads as
    # a classifier that merely likes general Q&A.
    fallbacks = sum(r["confidence"] == 0.0 and r["got"] == "通用问答" for r in results)
    return {
        "summary": {
            "model": settings.chat_model,
            "base_url": settings.chat_base_url,
            "questions": len(results),
            "intent_accuracy": round(correct / len(results), 4) if results else None,
            "fallbacks": fallbacks,
            "usage": usage,
        },
        "questions": results if details else [],
    }


def check(summary: dict) -> list[str]:
    """Compare a tune-split retrieval summary against the committed thresholds."""
    limits = json.loads(THRESHOLDS_FILE.read_text(encoding="utf-8"))
    failures = []
    for key, bound in limits.get("min", {}).items():
        if summary[key] is None or summary[key] < bound:
            failures.append(f"{key}={summary[key]} < {bound}")
    for key, bound in limits.get("max", {}).items():
        if summary[key] is None or summary[key] > bound:
            failures.append(f"{key}={summary[key]} > {bound}")
    return failures


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", choices=("tune", "heldout", "all"), default="tune")
    parser.add_argument("--retrieval", choices=evidence.RANKINGS,
                        help="ranking inside the named schools (default: the ADVISOR_RETRIEVAL setting)")
    parser.add_argument("--details", action="store_true", help="include per-question rows")
    parser.add_argument("--intent", action="store_true", help="also score the intent router (calls the model)")
    parser.add_argument("--out", help="write the full report as JSON")
    parser.add_argument("--check", action="store_true", help="fail when the tune split misses the thresholds")
    args = parser.parse_args(argv)
    if args.check and args.split != "tune":
        parser.error("--check only applies to the tune split")

    questions = load_questions(args.split)
    report = {"split": args.split, "retrieval": score_retrieval(questions, args.details, args.retrieval)}
    if args.intent:
        report["intent"] = score_intent(questions, args.details)
    print(json.dumps({k: (v["summary"] if isinstance(v, dict) else v) for k, v in report.items()},
                     ensure_ascii=False, indent=1))
    if args.details:
        for p in report["retrieval"]["questions"]:
            print(json.dumps(p, ensure_ascii=False))
        for p in report.get("intent", {}).get("questions", []):
            if p["expected"] != p["got"]:
                print("intent miss:", json.dumps(p, ensure_ascii=False))
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if args.check:
        failures = check(report["retrieval"]["summary"])
        if failures:
            print("eval below thresholds: " + "; ".join(failures), file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
