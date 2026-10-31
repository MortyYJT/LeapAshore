"""The snapshot RAG eval's model-free half (openspec snapshot-rag D11), run in CI.

`evals/results/passages-2026-10-30.json` is the one live run: the passages each question retrieved
from the local chunks and DeepSeek's recorded function-call arguments. Replaying it re-runs the quote
check on those recorded answers, so a change to the check that would change the reported numbers
fails here instead of passing silently.
"""

import json
from pathlib import Path

from app.agent.answer import PassageAnswer, verify
from evals.run_passages import load_questions, metrics, replay

RECORDED = Path(__file__).resolve().parents[1] / "evals" / "results" / "passages-2026-10-30.json"


def test_the_recorded_run_replays_to_its_reported_metrics():
    again, same = replay(RECORDED)
    assert same
    assert again["citation_pass_rate"] == 1.0 and again["quotes"] == 82
    assert again["sentences"] == 79 and again["sentences_kept"] == 75
    assert again["unanswerable_refused"] == again["unanswerable"] == 6


def test_a_recorded_sentence_stating_a_year_its_quote_lacks_is_dropped():
    item = next(i for i in json.loads(RECORDED.read_text())["items"] if i["id"] == "t05")
    checked = verify(PassageAnswer.model_validate(item["arguments"]), [p["text"] for p in item["passages"]])
    dropped = [s for s in checked.sentences if not s.ok]
    assert len(dropped) == 1 and dropped[0].reasons == ["number_not_in_quotes"] and "2027-2028" in dropped[0].text


def test_the_labels_are_well_formed():
    questions = load_questions()
    assert len(questions) == len({q["id"] for q in questions}) == 38
    for q in questions:
        assert q["topic"] in {"tuition", "recommendation", "interview"}
        assert bool(q.get("gold")) == q["answerable"]
        if q["answerable"]:
            assert q["gold"]["url"].startswith("https://") and len(q["gold"]["quote"]) >= 12


def test_a_question_the_gate_refused_scores_as_refused():
    out = metrics([{"id": "x", "answerable": False, "passages": [], "routed": True}])
    assert out["unanswerable_refused"] == 1 and out["quotes"] == 0 and out["citation_pass_rate"] is None


def _passage(url, text):
    return {"url": url, "text": text}


def test_retrieval_only_scores_where_the_gold_page_and_sentence_rank():
    from evals.run_passages import retrieval_metrics

    gold = {"url": "https://a.example/p", "quote": "Tuition is 30,000 dollars per year"}
    items = [
        # the gold page comes second, through a chunk that does not hold the sentence; the sentence third
        {"id": "x1", "answerable": True, "gold": gold, "passages": [
            _passage("https://a.example/other", "nothing"), _passage(gold["url"], "Fees vary."),
            _passage(gold["url"], "Note: tuition is 30,000 dollars per year for all.")]},
        {"id": "x2", "answerable": True, "gold": gold, "passages": [_passage("https://a.example/other", "no")]},
        {"id": "x3", "answerable": True, "gold": gold, "passages": []},
        {"id": "x4", "answerable": False, "gold": None, "passages": []},
        {"id": "x5", "answerable": False, "gold": None, "passages": [_passage("https://b.example", "t")]},
    ]
    out = retrieval_metrics(items)
    assert out["answerable"] == 3 and out["unanswerable"] == 2
    assert out["gold_page_retrieved"] == 1 and out["gold_quote_retrieved"] == 1
    assert out["answerable_gate_refused"] == 1 and out["unanswerable_refused"] == 1
    assert out["gold_page_mrr"] == round(0.5 / 3, 4) and out["gold_quote_mrr"] == round((1 / 3) / 3, 4)
    assert out["per_question"]["x1"] == {"gate": "pass", "gold_page_rank": 2, "gold_quote_rank": 3}
    assert out["per_question"]["x3"] == {"gate": "refuse", "gold_page_rank": None, "gold_quote_rank": None}


def test_the_recorded_live_run_retrieved_what_its_metrics_say():
    # The retrieval-only score of the recorded passages agrees with the live run's own counts.
    from evals.run_passages import retrieval_metrics

    recorded = json.loads(RECORDED.read_text())
    again = retrieval_metrics(recorded["items"])
    assert again["gold_page_retrieved"] == recorded["metrics"]["gold_page_retrieved"]
    assert again["gold_quote_retrieved"] == recorded["metrics"]["gold_quote_retrieved"]
