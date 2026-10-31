"""Score the advisor's requirement retrieval and evidence gate, and optionally its intent router.

    python -m evals.run_advisor [--split tune|heldout|all] [--retrieval rules|fts|vector|hybrid]
                                [--details] [--intent] [--out FILE] [--check]
    python -m evals.run_advisor --compare A.json B.json [--out FILE]
    python -m evals.run_advisor --relabel

``--retrieval`` picks the ranking inside the named schools (openspec hybrid-retrieval D7). A ranking
asked for by name that needs vectors is refused unless the key is set and every program has a vector
for the configured model, so a missing key or an unfinished backfill cannot pass for a vector result.
A question whose embedding fails at query time (timeout, error) is ranked by full text, as production
does; the summary reports how often that happened (``embedding.fallback_rate``), and a run where no
question embedded at all is refused. Without the flag, the production setting ``ADVISOR_RETRIEVAL`` is
scored exactly as production runs it; the summary's ``ranking`` lists what was used.

The retrieval part calls ``app.agent.evidence.gate`` exactly as the graph does and needs no model, so
CI runs it (``--split tune --check``). ``--intent`` calls the production classifier against the chat
model in ``CHAT_*`` and is never run in CI.

Labels live in ``evals/advisor_questions.json`` (written by Claude from the catalogue's program names,
fields and schools; no human review). Every requirement question carries graded relevance per program
id: 2 = the program the question names or clearly means, 1 = same school and same subject but not the
named one, 0 = any other row. ``grades`` is the frozen list; ``meant`` and ``related`` are the rules it
was resolved from (a regex on the program's English and stored names, an optional ``Program.field``,
explicit ids, or ``all`` rows of the named schools), restricted to rows with requirement data and a citable source (the only rows the gate
can return). The runner re-resolves the rules and refuses to score when they no longer give the frozen
grades, so a catalogue change cannot silently re-grade the set; ``--relabel`` rewrites the grades from
the rules after a deliberate catalogue change and prints what moved.

Metrics, over the questions whose intent is ``官方要求核验`` (the only ones that reach the gate), K being
the number of rows the gate hands the model:

- nDCG@K: DCG = sum over the first K returned rows of (2^grade - 1) / log2(rank + 1), divided by the
  DCG of the ideal order of the question's labelled rows. Per answerable question.
- MRR: 1 / rank of the first returned row of grade 2 (0 when none is in the K rows). Grade 1 rows do
  not count: the question is "did the program the user meant come first".
- Recall@K: grade-2 rows among the K returned / min(K, grade-2 rows); Precision@K: grade-2 rows /
  rows returned, over answerable questions the gate passed. Grade 2 is what the previous binary labels
  called relevant, so these two stay comparable with earlier runs.
- A refused answerable question scores 0 on nDCG, MRR and recall.
- false-pass rate (门槛误放率): unanswerable questions the gate let through / unanswerable questions.
- false-block rate (误拦率): answerable questions the gate refused / answerable questions.
- latency: wall time of one ``gate`` call (embedding included), p50 / p99 by nearest rank.
- rows read: rows the database returned to Python while gating one question, and statements run.
- embedding: queries embedded, fallbacks to full text and their rate, tokens and cost per embedded
  query (``EMBED_PRICE_CNY_PER_MTOK``); ``null`` when nothing was sent to the embedding service (a
  ranking without vectors, or no key).

Each of these is also reported per question type. ``--compare`` pairs two ``--details`` reports on the
same labels question by question and counts wins, losses and ties on nDCG@K and on reciprocal rank.

Intent accuracy is over every question in the split.
"""

import argparse
import asyncio
import hashlib
import inspect
import json
import math
import re
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import event, select

from app.agent import embeddings, evidence
from app.db import SessionLocal, engine
from app.models.program import Program, University, has_requirement_data
from app.models.source import Source

HERE = Path(__file__).resolve().parent
QUESTIONS_FILE = HERE / "advisor_questions.json"
THRESHOLDS_FILE = HERE / "advisor_thresholds.json"
REQUIREMENT_INTENT = "官方要求核验"
SPLITS = ("tune", "heldout")
QUESTION_TYPES = (
    "exact_name",  # quotes the program's English title
    "zh_named",  # names one specific program in Chinese (a translation of its English title)
    "synonym",  # names it with other words than its title (学 NLP 的 -> Speech and Language Processing)
    "vague",  # describes a kind of program rather than naming one
    "subject",  # names a subject (计算机硕士), so every program in it is meant
    "multi_school",  # the same question about two schools
    "unanswerable",  # the catalogue cannot answer it; the gate should refuse
    "other_intent",  # not a requirement question; scored by the intent router only
)


# ---- labels -------------------------------------------------------------------------------------


def load_questions(split: str) -> list[dict]:
    rows = json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))["questions"]
    return [q for q in rows if split == "all" or q["split"] == split]


def labels_sha256() -> str:
    return hashlib.sha256(QUESTIONS_FILE.read_bytes()).hexdigest()


def top_k() -> int:
    """The number of rows the gate hands the model, read from the code rather than restated here."""
    if hasattr(evidence, "TOP_K"):
        return evidence.TOP_K
    return inspect.signature(evidence.search_requirements).parameters["limit"].default


def _matches(spec: dict | None, row: tuple) -> bool:
    if not spec:
        return False
    if not ({"name", "field", "ids", "all"} & spec.keys()):
        raise ValueError(f"a label rule needs name, field, ids or all: {spec}")
    pid, name_en, name, field_ = row
    if "ids" in spec and pid not in spec["ids"]:
        return False
    if spec.get("field") and field_ != spec["field"]:
        return False
    if spec.get("name") and not re.search(spec["name"], f"{name_en or ''} {name or ''}", re.IGNORECASE):
        return False
    return True


def grade_rows(rows: list[tuple], q: dict) -> dict[str, int]:
    """Grades for ``rows`` (id, English name, stored name, field) from a question's rules."""
    meant = q.get("meant")
    if meant is not None and not ({"name", "field", "ids", "all"} & meant.keys()):
        raise ValueError(f"a label rule needs name, field, ids or all: {meant}")
    grades = {}
    for r in rows:
        if _matches(meant, r):
            grades[r[0]] = 2
        elif _matches(q.get("related"), r):
            grades[r[0]] = 1
    return grades


def label_problems(q: dict) -> list[str]:
    """What is wrong with one question's labels, checked without the database."""
    out = []
    if q.get("split") not in SPLITS:
        out.append(f"{q.get('id')}: split {q.get('split')!r}")
    if q.get("type") not in QUESTION_TYPES:
        out.append(f"{q.get('id')}: type {q.get('type')!r}")
    if q.get("intent") != REQUIREMENT_INTENT:
        if q.get("type") != "other_intent":
            out.append(f"{q['id']}: a non-requirement question must be other_intent")
        return out
    if q.get("type") == "other_intent":
        out.append(f"{q['id']}: a requirement question cannot be other_intent")
    grades = q.get("grades")
    if not isinstance(grades, dict) or any(g not in (1, 2) for g in grades.values()):
        out.append(f"{q['id']}: grades must map program ids to 1 or 2")
        return out
    if q.get("answerable") is not bool(grades):
        out.append(f"{q['id']}: answerable={q.get('answerable')} but {len(grades)} graded rows")
    if grades and 2 not in grades.values():
        out.append(f"{q['id']}: an answerable question needs a grade-2 row")
    if (q.get("type") == "unanswerable") is bool(q.get("answerable")):
        out.append(f"{q['id']}: type unanswerable must equal answerable=false")
    return out


def _usable_rows(session, schools: list[str]) -> list[tuple]:
    """The rows of these schools that carry requirement data and a citable source: the only rows the
    gate can return, so the only ones worth a grade. The same SQL rules the gate filters by."""
    if not schools:
        return []
    return [tuple(r) for r in session.execute(
        select(Program.id, Program.name_en, Program.name, Program.field)
        .join(Source, Source.id == Program.source_id)
        .where(Program.university_id.in_(schools), has_requirement_data(), evidence.citable_source())
        .order_by(Program.id)
    )]


def resolve_grades(session, q: dict) -> dict[str, int]:
    return grade_rows(_usable_rows(session, q["schools"]), q)


def validate_labels(session, questions: list[dict]) -> None:
    """Every school id must exist, every label rule must still give the frozen grades. The curated
    short forms are checked here too, because only a full catalogue has every id they name."""
    known = set(session.scalars(select(University.id)))
    problems = []
    from app.agent import catalog_match

    stale = sorted(set(catalog_match.curated_aliases()) - known)
    if stale:
        problems.append(f"university_aliases.json names ids the catalogue does not hold: {stale}")
    for q in questions:
        mine = label_problems(q)
        problems.extend(mine)
        if mine or q["intent"] != REQUIREMENT_INTENT:
            continue
        missing = [s for s in q["schools"] if s not in known]
        if missing:
            problems.append(f"{q['id']}: unknown school ids {missing}")
            continue
        now = resolve_grades(session, q)
        if now != q["grades"]:
            gone = sorted(set(q["grades"]) - set(now))
            new = sorted(set(now) - set(q["grades"]))
            changed = sorted(p for p in set(now) & set(q["grades"]) if now[p] != q["grades"][p])
            problems.append(f"{q['id']}: the rules now grade differently (gone {gone}, new {new}, "
                            f"changed {changed}); check the catalogue, then `--relabel`")
    if problems:
        raise SystemExit("label/database mismatch, refusing to score:\n  " + "\n  ".join(problems))


def relabel() -> int:
    """Rewrite every requirement question's grades from its rules, printing what changed."""
    data = json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))
    changed = 0
    with SessionLocal() as session:
        for q in data["questions"]:
            if q["intent"] != REQUIREMENT_INTENT:
                continue
            now = resolve_grades(session, q)
            if now != q.get("grades"):
                changed += 1
                print(json.dumps({"id": q["id"], "was": q.get("grades"), "now": now}, ensure_ascii=False))
                q["grades"] = now
                q["answerable"] = bool(now)
    QUESTIONS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{changed} questions regraded", file=sys.stderr)
    return 0


# ---- metrics ------------------------------------------------------------------------------------


def dcg(gains: list[int]) -> float:
    return sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(gains))


def ndcg(returned: list[str], grades: dict[str, int], k: int) -> float:
    ideal = dcg(sorted(grades.values(), reverse=True)[:k])
    return dcg([grades.get(p, 0) for p in returned[:k]]) / ideal if ideal else 0.0


def reciprocal_rank(returned: list[str], grades: dict[str, int]) -> float:
    return next((1 / (i + 1) for i, p in enumerate(returned) if grades.get(p) == 2), 0.0)


def recall(returned: list[str], grades: dict[str, int], k: int) -> float:
    meant = {p for p, g in grades.items() if g == 2}
    return len(set(returned[:k]) & meant) / min(k, len(meant))


def precision(returned: list[str], grades: dict[str, int]) -> float:
    return sum(grades.get(p) == 2 for p in returned) / len(returned) if returned else 0.0


def score_question(q: dict, passed: bool, returned: list[str], k: int) -> dict:
    """The ranking metrics of one gated question; ``None`` where they do not apply."""
    if not q["answerable"]:
        return {"ndcg": None, "rr": None, "recall": None, "precision": None}
    if not passed:
        return {"ndcg": 0.0, "rr": 0.0, "recall": 0.0, "precision": None}
    g = q["grades"]
    return {"ndcg": ndcg(returned, g, k), "rr": reciprocal_rank(returned, g), "recall": recall(returned, g, k),
            "precision": precision(returned, g)}


def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile: the smallest value with at least p% of the values at or below it."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(1, math.ceil(p / 100 * len(ordered))) - 1]


def _mean(values) -> float | None:
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 4) if values else None


def summarise(rows: list[dict]) -> dict:
    answerable = [p for p in rows if p["answerable"]]
    unanswerable = [p for p in rows if not p["answerable"]]
    passed_answerable = [p for p in answerable if p["passed"]]
    ms = [p["ms"] for p in rows]
    return {
        "questions": len(rows),
        "answerable": len(answerable),
        "unanswerable": len(unanswerable),
        "ndcg_at_k": _mean(p["ndcg"] for p in answerable),
        "mrr": _mean(p["rr"] for p in answerable),
        "recall_at_k": _mean(p["recall"] for p in answerable),
        "precision_at_k": _mean(p["precision"] for p in passed_answerable),
        "false_pass_rate": _mean(1.0 if p["passed"] else 0.0 for p in unanswerable),
        "false_block_rate": _mean(0.0 if p["passed"] else 1.0 for p in answerable),
        "false_passes": sum(p["passed"] for p in unanswerable),
        "false_blocks": sum(not p["passed"] for p in answerable),
        "latency_ms_p50": percentile(ms, 50),
        "latency_ms_p99": percentile(ms, 99),
        "mean_ms": _mean(ms),
        "mean_rows_read": _mean(p["rows_read"] for p in rows),
        "max_rows_read": max((p["rows_read"] for p in rows), default=0),
        "mean_statements": _mean(p["statements"] for p in rows),
    }


def by_type(rows: list[dict]) -> dict[str, dict]:
    keys = ("questions", "answerable", "ndcg_at_k", "mrr", "recall_at_k", "precision_at_k",
            "false_pass_rate", "false_block_rate", "latency_ms_p50")
    out = {}
    for t in QUESTION_TYPES:
        these = [p for p in rows if p["type"] == t]
        if these:
            s = summarise(these)
            out[t] = {key: s[key] for key in keys}
    return out


def embedding_summary(rows: list[dict], ranking: str, price_cny_per_mtok: float) -> dict:
    """How the vector half behaved: queries embedded, full-text fallbacks among questions that named a
    school (the only ones ranked), tokens and cost per embedded query. ``None`` = not applicable."""
    embedded = [p for p in rows if p["embedded"]]
    if ranking not in ("vector", "hybrid") or not any(p["embed_calls"] for p in rows):
        return {"embedded_queries": len(embedded), "fallbacks": None, "fallback_rate": None,
                "mean_tokens_per_query": None, "cost_cny_per_query": None}
    ranked = [p for p in rows if p["has_school"]]
    fallbacks = sum(p["fell_back"] for p in ranked)
    tokens = sum(p["embed_tokens"] for p in embedded) / len(embedded) if embedded else None
    return {
        "embedded_queries": len(embedded),
        "fallbacks": fallbacks,
        "fallback_rate": round(fallbacks / len(ranked), 4) if ranked else None,
        "mean_tokens_per_query": tokens,
        "cost_cny_per_query": None if tokens is None else tokens * price_cny_per_mtok / 1_000_000,
    }


def compare(a: dict, b: dict) -> dict:
    """Per-question wins, losses and ties of report ``b`` against report ``a`` (both ``--details``
    runs on the same labels), on nDCG@K and on reciprocal rank, overall and per question type."""
    if a.get("labels_sha256") != b.get("labels_sha256") or a.get("split") != b.get("split"):
        raise SystemExit("the two reports were scored on different labels or splits; not comparing")
    rows_a = {p["id"]: p for p in a["retrieval"]["questions"]}
    rows_b = {p["id"]: p for p in b["retrieval"]["questions"]}
    if not rows_a or rows_a.keys() != rows_b.keys():
        raise SystemExit("both reports need --details rows for the same questions")
    ids = [i for i in rows_a if rows_a[i]["answerable"]]
    out = {"a": a["retrieval"]["summary"]["ranking"], "b": b["retrieval"]["summary"]["ranking"],
           "split": a["split"], "answerable": len(ids)}
    for metric in ("ndcg", "rr"):
        tally = {"all": {"a_wins": 0, "b_wins": 0, "ties": 0}, "by_type": {}}
        winners = {"a_wins": [], "b_wins": []}
        for i in ids:
            x, y = rows_a[i][metric], rows_b[i][metric]
            verdict = "ties" if math.isclose(x, y, abs_tol=1e-9) else ("a_wins" if x > y else "b_wins")
            t = rows_a[i]["type"]
            tally["by_type"].setdefault(t, {"a_wins": 0, "b_wins": 0, "ties": 0})[verdict] += 1
            tally["all"][verdict] += 1
            if verdict != "ties":
                winners[verdict].append(i)
        out["ndcg_at_k" if metric == "ndcg" else "rr"] = {**tally, **winners}
    return out


# ---- running the gate ---------------------------------------------------------------------------


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


@contextmanager
def recording_embeddings():
    """Record every embedding call (tokens, ok) made while the block runs, without changing it."""
    calls: list[dict] = []
    original = embeddings.OpenAIEmbeddings.embed

    def embed(self, texts):
        try:
            result = original(self, texts)
        except Exception:
            calls.append({"tokens": 0, "ok": False})
            raise
        calls.append({"tokens": result.tokens, "ok": True})
        return result

    embeddings.OpenAIEmbeddings.embed = embed
    try:
        yield calls
    finally:
        embeddings.OpenAIEmbeddings.embed = original


def check_vectors(session, ranking: str) -> None:
    """Refuse a vector ranking that would silently run on full text or on part of the catalogue."""
    from sqlalchemy import func

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

    strict = ranking is not None
    ranking = ranking or settings.advisor_retrieval
    k = top_k()
    counter = QueryCounter()
    counter.hook()
    per_question = []
    used_rankings: set[str] = set()
    with SessionLocal() as session:
        validate_labels(session, questions)
        if strict:
            check_vectors(session, ranking)
    with recording_embeddings() as calls:
        for q in questions:
            if q["intent"] != REQUIREMENT_INTENT:
                continue
            before = len(calls)
            with SessionLocal() as session:
                counter.statements = counter.rows = 0
                counter.active = True
                started = time.perf_counter()
                update = evidence.gate(session, q["question"], ranking=ranking)
                elapsed = time.perf_counter() - started
                counter.active = False
            signals = update["trace"]["gate_signals"]
            used = signals.get("ranking")
            has_school = bool(signals["schools"])
            if has_school:
                used_rankings.add(used)
            returned = [c["programId"] for c in update.get("citations", [])]
            if len(returned) > k:
                raise SystemExit(f"{q['id']}: the gate returned {len(returned)} rows, more than K={k}")
            passed = bool(update.get("evidence_strong"))
            mine = calls[before:]
            per_question.append({
                "id": q["id"], "type": q["type"], "answerable": q["answerable"], "passed": passed,
                "refusal": update.get("refusal"), "returned": returned,
                "gains": [q["grades"].get(p, 0) for p in returned],
                "meant": sum(g == 2 for g in q["grades"].values()), "related": sum(g == 1 for g in q["grades"].values()),
                **{key: (None if v is None else round(v, 4))
                   for key, v in score_question(q, passed, returned, k).items()},
                "ranking_used": used if has_school else None, "has_school": has_school,
                "fell_back": has_school and ranking in ("vector", "hybrid") and used != ranking,
                "embed_calls": len(mine), "embedded": any(c["ok"] for c in mine),
                "embed_tokens": sum(c["tokens"] for c in mine if c["ok"]),
                "statements": counter.statements, "rows_read": counter.rows, "ms": round(elapsed * 1000, 1),
            })
    emb = embedding_summary(per_question, ranking, settings.embed_price_cny_per_mtok)
    ranked = sum(p["has_school"] for p in per_question)
    if strict and emb["fallbacks"] is not None and ranked and emb["fallbacks"] == ranked:
        raise SystemExit(f"--retrieval {ranking}: no question embedded (every one fell back to full text); "
                         "not scoring a full-text run as a vector one")
    summary = {
        "ranking": ranking if strict else f"{ranking} (used: {', '.join(sorted(used_rankings)) or 'none'})",
        "k": k,
        **summarise(per_question),
        "embedding": emb,
        "by_type": by_type(per_question),
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
    parser.add_argument("--compare", nargs=2, metavar=("A", "B"),
                        help="per-question wins/losses/ties between two --details reports; runs nothing")
    parser.add_argument("--relabel", action="store_true",
                        help="rewrite the frozen grades from the label rules (after a catalogue change)")
    args = parser.parse_args(argv)
    if args.check and args.split != "tune":
        parser.error("--check only applies to the tune split")
    if args.relabel:
        return relabel()
    if args.compare:
        a, b = (json.loads(Path(p).read_text(encoding="utf-8")) for p in args.compare)
        result = compare(a, b)
        print(json.dumps(result, ensure_ascii=False, indent=1))
        if args.out:
            Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        return 0

    questions = load_questions(args.split)
    report = {"split": args.split, "labels_sha256": labels_sha256(),
              "retrieval": score_retrieval(questions, args.details, args.retrieval)}
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
