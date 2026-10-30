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
