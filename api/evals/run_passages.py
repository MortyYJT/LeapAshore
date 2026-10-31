"""Measure answering from official page chunks: citation verification pass rate and outcomes.

    python -m evals.run_passages --check                      # gold quotes are in the stored chunks
    python -m evals.run_passages --live [--out FILE] [--budget-cny 5]
    python -m evals.run_passages --replay FILE                # no database, no model
    python -m evals.run_passages --retrieve [--retrieval fts|vector|hybrid] [--out FILE]   # no model

Questions and labels: ``evals/passage_questions.json`` (openspec snapshot-rag D11).

``--live`` runs, per question, the production intent classifier and routing decision, then the passage
gate (the production ranking, which is full text until an embedding key exists) and one answer call
with the chat model in ``CHAT_*``, and the quote check. Every question goes through the passage path,
including one the router would have sent elsewhere, so the citation numbers cover the whole set; the
routing decision is reported apart. It records the passages, the model's raw function-call arguments,
tokens and an upper-bound cost (DeepSeek's peak price, `queue.cost_cny`) to ``--out``; a run stops
before its next call once the cost so far passes ``--budget-cny``. Local only: the chunks come from the
local database.

``--replay`` recomputes every check and metric from a recorded file and exits 1 if they differ from
what the file says; CI does this through ``tests/test_passage_eval.py``.

Metrics:

- citation pass rate: quotes that passed the check / quotes the model gave (over every answer);
- sentence keep rate: sentences shown / sentences written; reasons a sentence was dropped;
- answered: questions left with at least one checked sentence; refused: the gate refused, or nothing
  checked out; for answerable questions, answered / answerable; for unanswerable ones, refused /
  unanswerable;
- gold page retrieved / cited: answerable questions whose labelled page is among the passages / is cited
  by a shown sentence;
- gold quote retrieved / cited: the same for the passage that holds the labelled sentence itself (a
  page can be retrieved through another of its chunks).

``--retrieve`` runs only the passage gate, with no model call: topics come from the question's words
(``passages.detect_topics``, what the router would pass), and the ranking is ``--retrieval`` (default:
the production setting). It reports, over answerable questions, how many retrieved the gold page and
the gold sentence's passage and the mean reciprocal rank of each (0 when missing), and how many
questions of each kind the gate refused. A vector ranking is refused without a key or when no
question embedded, as in ``run_advisor``.

The answered count includes answers whose only shown sentences say the passages do not cover the
asked program (they quote a passage verbatim, so the check keeps them); the gold counts are the
measure of answers that state the labelled fact's source.
"""

import argparse
import asyncio
import json
import sys
import time
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
QUESTIONS_FILE = HERE / "passage_questions.json"


def load_questions() -> list[dict]:
    return json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))["questions"]


# ---- scoring (no database, no model) ---------------------------------------------------------------


def score_item(item: dict) -> dict:
    """The check's outcome for one recorded question."""
    from app.agent.answer import PassageAnswer, verify

    passages = item.get("passages") or []
    from app.collect.text import normalize

    out = {"gate": "pass" if passages else "refuse", "quotes": 0, "quotes_passed": 0, "sentences": 0, "kept": 0,
           "reasons": {}, "answered": False, "gold_retrieved": False, "gold_cited": False,
           "gold_quote_retrieved": False, "gold_quote_cited": False}
    gold = (item.get("gold") or {}).get("url")
    out["gold_retrieved"] = bool(gold and any(p["url"] == gold for p in passages))
    # The passages that hold the labelled sentence itself, not only its page.
    quote = normalize((item.get("gold") or {}).get("quote") or "")
    holding = {n for n, p in enumerate(passages, 1) if quote and p["url"] == gold and quote in normalize(p["text"])}
    out["gold_quote_retrieved"] = bool(holding)
    if not passages:
        return out
    answer = PassageAnswer.model_validate(item.get("arguments") or {})
    checked = verify(answer, [p["text"] for p in passages])
    summary = checked.summary()
    out.update({k: summary[k] for k in ("quotes", "quotes_passed", "sentences", "kept", "reasons")})
    out["answered"] = bool(checked.kept)
    cited = {passages[n - 1]["url"] for s in checked.kept for n in s.passages}
    out["gold_cited"] = bool(gold and gold in cited)
    out["gold_quote_cited"] = bool(holding & {n for s in checked.kept for n in s.passages})
    return out


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def metrics(items: list[dict]) -> dict:
    scored = [score_item(i) for i in items]
    answerable = [(i, s) for i, s in zip(items, scored) if i["answerable"]]
    unanswerable = [(i, s) for i, s in zip(items, scored) if not i["answerable"]]
    quotes = sum(s["quotes"] for s in scored)
    passed = sum(s["quotes_passed"] for s in scored)
    sentences = sum(s["sentences"] for s in scored)
    kept = sum(s["kept"] for s in scored)
    reasons: dict[str, int] = {}
    for s in scored:
        for r, n in s["reasons"].items():
            reasons[r] = reasons.get(r, 0) + n
    return {
        "questions": len(items), "answerable": len(answerable), "unanswerable": len(unanswerable),
        "routed_to_passages": sum(1 for i in items if i.get("routed")),
        "citation_pass_rate": _rate(passed, quotes), "quotes": quotes, "quotes_passed": passed,
        "sentence_keep_rate": _rate(kept, sentences), "sentences": sentences, "sentences_kept": kept,
        "dropped_reasons": dict(sorted(reasons.items())),
        "answerable_answered": sum(1 for _, s in answerable if s["answered"]),
        "answerable_gate_refused": sum(1 for _, s in answerable if s["gate"] == "refuse"),
        "answerable_refused_after_check": sum(1 for _, s in answerable if s["gate"] == "pass" and not s["answered"]),
        "unanswerable_refused": sum(1 for _, s in unanswerable if not s["answered"]),
        "gold_page_retrieved": sum(1 for _, s in answerable if s["gold_retrieved"]),
        "gold_page_cited": sum(1 for _, s in answerable if s["gold_cited"]),
        "gold_quote_retrieved": sum(1 for _, s in answerable if s["gold_quote_retrieved"]),
        "gold_quote_cited": sum(1 for _, s in answerable if s["gold_quote_cited"]),
        "per_question": {i["id"]: s for i, s in zip(items, scored)},
    }


def retrieval_item(item: dict) -> dict:
    """Where one question's gold page and gold sentence came among its retrieved passages (1-based)."""
    from app.collect.text import normalize

    passages = item.get("passages") or []
    gold = item.get("gold") or {}
    quote = normalize(gold.get("quote") or "")
    on_page = [n for n, p in enumerate(passages, 1) if gold.get("url") and p["url"] == gold["url"]]
    holding = [n for n in on_page if quote and quote in normalize(passages[n - 1]["text"])]
    return {"gate": "pass" if passages else "refuse", "gold_page_rank": on_page[0] if on_page else None,
            "gold_quote_rank": holding[0] if holding else None}


def retrieval_metrics(items: list[dict]) -> dict:
    """Retrieval-only metrics: no answer is needed, only the passages each question retrieved."""
    scored = {i["id"]: retrieval_item(i) for i in items}
    answerable = [scored[i["id"]] for i in items if i["answerable"]]
    unanswerable = [scored[i["id"]] for i in items if not i["answerable"]]

    def mrr(key):
        return round(sum(1 / s[key] for s in answerable if s[key]) / len(answerable), 4) if answerable else None

    return {
        "questions": len(items), "answerable": len(answerable), "unanswerable": len(unanswerable),
        "gold_page_retrieved": sum(1 for s in answerable if s["gold_page_rank"]),
        "gold_quote_retrieved": sum(1 for s in answerable if s["gold_quote_rank"]),
        "gold_page_mrr": mrr("gold_page_rank"), "gold_quote_mrr": mrr("gold_quote_rank"),
        "answerable_gate_refused": sum(1 for s in answerable if s["gate"] == "refuse"),
        "unanswerable_refused": sum(1 for s in unanswerable if s["gate"] == "refuse"),
        "per_question": scored,
    }


def run_retrieval(ranking: str | None) -> dict:
    """The passage gate alone over every question; nothing is sent to a chat model."""
    from app.agent import embeddings, passages
    from app.config import settings
    from app.db import SessionLocal

    ranking = ranking or settings.advisor_retrieval
    if ranking not in ("fts", "vector", "hybrid"):
        raise SystemExit(f"passages rank by fts, vector or hybrid, not {ranking!r}; pass --retrieval")
    if ranking in ("vector", "hybrid") and embeddings.configured_client() is None:
        raise SystemExit(f"--retrieval {ranking} needs EMBED_API_KEY; not scoring")
    items, used = [], {}
    started = time.monotonic()
    for q in load_questions():
        topics = passages.detect_topics(q["question"])
        t0 = time.perf_counter()
        with SessionLocal() as s:
            update = passages.gate(s, q["question"], topics, ranking=ranking)
        ms = round((time.perf_counter() - t0) * 1000, 1)
        signals = update["trace"]["gate_signals"]
        if signals["schools"]:
            used[signals["ranking"]] = used.get(signals["ranking"], 0) + 1
        items.append({"id": q["id"], "question": q["question"], "topic": q["topic"], "answerable": q["answerable"],
                      "gold": q.get("gold"), "topics": [t.key for t in topics], "ranking": signals["ranking"],
                      "ms": ms, "refusal": update.get("refusal"),
                      "passages": [{"chunk_id": p["chunk_id"], "url": p["url"], "text": p["text"]}
                                   for p in update.get("passages") or []]})
    if ranking in ("vector", "hybrid") and used and set(used) == {"fts"}:
        raise SystemExit(f"--retrieval {ranking}: no question embedded; not scoring a full-text run as a vector one")
    return {"date": date.today().isoformat(), "ranking": ranking, "ranking_used": used,
            "seconds": round(time.monotonic() - started, 1), "items": items, "metrics": retrieval_metrics(items)}


def replay(path: Path) -> tuple[dict, bool]:
    recorded = json.loads(path.read_text(encoding="utf-8"))
    again = metrics(recorded["items"])
    return again, again == recorded["metrics"]


# ---- live ------------------------------------------------------------------------------------------


def check_labels() -> list[str]:
    from sqlalchemy import select

    from app.collect.text import normalize
    from app.db import SessionLocal
    from app.models.snapshot import SnapshotChunk, SnapshotPage

    problems = []
    with SessionLocal() as s:
        for q in load_questions():
            gold = q.get("gold")
            if q["answerable"] != bool(gold):
                problems.append(f"{q['id']}: answerable must have a gold page, unanswerable none")
                continue
            if not gold:
                continue
            texts = s.scalars(select(SnapshotChunk.text).join(SnapshotPage).where(SnapshotPage.url == gold["url"])).all()
            if not any(normalize(gold["quote"]) in normalize(t) for t in texts):
                problems.append(f"{q['id']}: gold quote not in a stored chunk of {gold['url']}")
    return problems


async def run_live(budget_cny: float) -> dict:
    from app.agent import answer, intent, passages
    from app.agent.llm import get_chat_model
    from app.collect.queue import cost_cny
    from app.config import settings
    from app.db import SessionLocal

    from langchain_core.callbacks import get_usage_metadata_callback

    usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0}
    intent_usage = dict(usage)
    items, models = [], set()
    started = time.monotonic()
    for q in load_questions():
        if cost_cny(usage) + cost_cny(intent_usage) >= budget_cny:
            print(f"budget reached before {q['id']}", file=sys.stderr)
            break
        with get_usage_metadata_callback() as counted:
            classified = await intent.classify(q["question"], "")
        for meta in counted.usage_metadata.values():
            intent_usage["input_tokens"] += meta.get("input_tokens", 0)
            intent_usage["output_tokens"] += meta.get("output_tokens", 0)
            intent_usage["cache_read_tokens"] += (meta.get("input_token_details") or {}).get("cache_read", 0) or 0
        with SessionLocal() as s:
            routed = passages.route(s, q["question"], classified["intent"])
            topics = routed or passages.detect_topics(q["question"])
            update = passages.gate(s, q["question"], topics)
        item = {"id": q["id"], "question": q["question"], "topic": q["topic"], "answerable": q["answerable"],
                "gold": q.get("gold"), "intent": classified["intent"], "routed": bool(routed),
                "topics": [t.key for t in topics], "ranking": update["trace"]["gate_signals"]["ranking"],
                "passages": update.get("passages") or [], "refusal": update.get("refusal")}
        if item["passages"]:
            generated = await answer.generate(q["question"], item["passages"], model=get_chat_model(temperature=0))
            item["arguments"] = generated.answer.model_dump()
            item["answer_error"] = generated.error
            item["usage"] = generated.usage
            models.add(generated.model)
            for key in usage:
                usage[key] += generated.usage.get(key, 0)
        items.append(item)
        print(json.dumps({"id": q["id"], "routed": item["routed"], "passages": len(item["passages"]),
                          "cost_so_far": round(cost_cny(usage) + cost_cny(intent_usage), 4)}, ensure_ascii=False), file=sys.stderr)
    return {
        "date": date.today().isoformat(), "chat_model_setting": settings.chat_model, "models_reported": sorted(m for m in models if m),
        "base_url": settings.chat_base_url, "ranking_setting": settings.advisor_retrieval,
        "answer_tokens": usage, "answer_cost_cny_upper_bound": round(cost_cny(usage), 4),
        "intent_tokens": intent_usage, "intent_cost_cny_upper_bound": round(cost_cny(intent_usage), 4),
        "seconds": round(time.monotonic() - started, 1), "items": items, "metrics": metrics(items),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--replay", type=Path)
    mode.add_argument("--retrieve", action="store_true", help="the passage gate only, no model call")
    parser.add_argument("--retrieval", choices=("fts", "vector", "hybrid"),
                        help="ranking for --retrieve (default: the ADVISOR_RETRIEVAL setting)")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--budget-cny", type=float, default=5.0)
    args = parser.parse_args(argv)
    if args.check:
        problems = check_labels()
        print(json.dumps({"questions": len(load_questions()), "problems": problems}, ensure_ascii=False))
        return 1 if problems else 0
    if args.replay:
        again, same = replay(args.replay)
        print(json.dumps({k: v for k, v in again.items() if k != "per_question"} | {"matches_recorded": same},
                         ensure_ascii=False))
        return 0 if same else 1
    if args.retrieve:
        result = run_retrieval(args.retrieval)
        if args.out:
            args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(json.dumps({k: v for k, v in result["metrics"].items() if k != "per_question"}
                         | {"ranking": result["ranking"], "ranking_used": result["ranking_used"]}, ensure_ascii=False))
        return 0
    result = asyncio.run(run_live(args.budget_cny))
    out = args.out or HERE / "results" / f"passages-{result['date']}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result["metrics"].items() if k != "per_question"}
                     | {"answer_tokens": result["answer_tokens"], "intent_tokens": result["intent_tokens"],
                        "cost_cny": round(result["answer_cost_cny_upper_bound"] + result["intent_cost_cny_upper_bound"], 4),
                        "models": result["models_reported"], "out": str(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
