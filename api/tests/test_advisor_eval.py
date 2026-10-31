"""The advisor retrieval eval's metrics and label rules (api/evals/run_advisor.py), without a database.

The scored numbers go on a CV, so each metric is pinned against values worked out by hand: graded
nDCG@K with gain 2^g - 1 and a log2 discount normalised by the ideal order of the labelled set, MRR on
the first grade-2 row, and Recall/Precision@K on grade-2 rows as before. A refused answerable question
scores 0 on all of them.
"""

import json
import math

import pytest

from evals import run_advisor as ra

K = 4
GRADES = {"a": 2, "b": 1, "c": 2}


def test_dcg_uses_exponential_gain_and_log2_discount():
    # (2^2-1)/log2(2) + (2^0-1)/log2(3) + (2^1-1)/log2(4)
    assert ra.dcg([2, 0, 1]) == pytest.approx(3 + 0 + 1 / 2)


def test_ndcg_is_one_for_the_ideal_order_and_normalised_by_the_labelled_set():
    assert ra.ndcg(["a", "c", "b"], GRADES, K) == pytest.approx(1.0)
    # The ideal is the labelled set in grade order (2, 2, 1), even though only two rows came back.
    ideal = 3 + 3 / math.log2(3) + 1 / 2
    assert ra.ndcg(["b", "a"], GRADES, K) == pytest.approx((1 + 3 / math.log2(3)) / ideal)


def test_ndcg_counts_only_the_first_k_rows_and_unlabelled_rows_gain_nothing():
    assert ra.ndcg(["x", "y", "z", "w", "a"], GRADES, K) == 0.0
    grades = {f"p{i}": 2 for i in range(6)}
    assert ra.ndcg([f"p{i}" for i in range(6)], grades, K) == pytest.approx(1.0)


def test_reciprocal_rank_waits_for_a_grade_two_row():
    assert ra.reciprocal_rank(["b", "x", "c"], GRADES) == pytest.approx(1 / 3)
    assert ra.reciprocal_rank(["b", "x"], GRADES) == 0.0
    assert ra.reciprocal_rank([], GRADES) == 0.0


def test_recall_and_precision_count_grade_two_rows():
    assert ra.recall(["a", "b", "x"], GRADES, K) == pytest.approx(1 / 2)
    assert ra.precision(["a", "b", "x"], GRADES) == pytest.approx(1 / 3)
    many = {f"p{i}": 2 for i in range(9)}
    assert ra.recall(["p0", "p1", "p2", "p3"], many, K) == 1.0  # denominator min(K, relevant)


def test_a_refused_answerable_question_scores_zero_and_unanswerable_ones_score_nothing():
    refused = ra.score_question({"answerable": True, "grades": GRADES}, passed=False, returned=[], k=K)
    assert refused["ndcg"] == refused["rr"] == refused["recall"] == 0.0 and refused["precision"] is None
    passed = ra.score_question({"answerable": True, "grades": GRADES}, passed=True, returned=["c"], k=K)
    assert passed["rr"] == 1.0 and passed["precision"] == 1.0
    blocked = ra.score_question({"answerable": False, "grades": {}}, passed=False, returned=[], k=K)
    assert blocked["ndcg"] is blocked["rr"] is blocked["recall"] is blocked["precision"] is None


def test_percentile_is_nearest_rank():
    values = list(range(1, 101))
    assert ra.percentile(values, 50) == 50 and ra.percentile(values, 99) == 99
    assert ra.percentile([7.0], 99) == 7.0 and ra.percentile([], 50) is None
    assert ra.percentile([1, 2, 3], 50) == 2


def row(id_, passed=True, answerable=True, ndcg=1.0, rr=1.0, recall=1.0, precision=1.0, ms=1.0, type_="subject"):
    return {"id": id_, "type": type_, "answerable": answerable, "passed": passed, "ndcg": ndcg, "rr": rr,
            "recall": recall, "precision": precision, "ms": ms, "rows_read": 10, "statements": 3}


def test_summary_and_per_type_breakdown():
    rows = [
        row("q1", ndcg=1.0, rr=1.0, type_="synonym", ms=5),
        row("q2", ndcg=0.5, rr=0.5, recall=0.5, precision=0.5, type_="synonym", ms=7),
        row("q3", passed=False, ndcg=0.0, rr=0.0, recall=0.0, precision=None, type_="vague", ms=9),
        row("q4", answerable=False, passed=True, ndcg=None, rr=None, recall=None, precision=None, type_="unanswerable"),
        row("q5", answerable=False, passed=False, ndcg=None, rr=None, recall=None, precision=None, type_="unanswerable"),
    ]
    s = ra.summarise(rows)
    assert s["ndcg_at_k"] == pytest.approx(0.5) and s["mrr"] == pytest.approx(0.5)
    assert s["recall_at_k"] == pytest.approx(0.5) and s["precision_at_k"] == pytest.approx(0.75)
    assert s["false_pass_rate"] == 0.5 and s["false_passes"] == 1
    assert s["false_block_rate"] == pytest.approx(1 / 3, abs=1e-4) and s["false_blocks"] == 1
    assert s["latency_ms_p50"] == 5 and s["latency_ms_p99"] == 9
    by_type = ra.by_type(rows)
    assert by_type["synonym"]["questions"] == 2 and by_type["synonym"]["ndcg_at_k"] == pytest.approx(0.75)
    assert by_type["unanswerable"]["false_pass_rate"] == 0.5 and by_type["unanswerable"]["ndcg_at_k"] is None


def report(ranking, rows, labels="x"):
    return {"split": "heldout", "labels_sha256": labels,
            "retrieval": {"summary": {"ranking": ranking}, "questions": rows}}


def test_compare_counts_wins_losses_and_ties_per_question_and_type():
    a = report("rules", [row("q1", ndcg=1.0, type_="synonym"), row("q2", ndcg=0.2, type_="vague"),
                         row("q3", ndcg=0.5, type_="vague"), row("q4", answerable=False, ndcg=None, rr=None)])
    b = report("fts", [row("q1", ndcg=0.4, type_="synonym"), row("q2", ndcg=0.9, type_="vague"),
                       row("q3", ndcg=0.5, type_="vague"), row("q4", answerable=False, ndcg=None, rr=None)])
    out = ra.compare(a, b)
    assert out["a"] == "rules" and out["b"] == "fts"
    assert out["ndcg_at_k"]["all"] == {"a_wins": 1, "b_wins": 1, "ties": 1}
    assert out["ndcg_at_k"]["by_type"]["vague"] == {"a_wins": 0, "b_wins": 1, "ties": 1}
    assert out["ndcg_at_k"]["a_wins"] == ["q1"] and out["ndcg_at_k"]["b_wins"] == ["q2"]
    assert out["rr"]["all"] == {"a_wins": 0, "b_wins": 0, "ties": 3}


def test_compare_refuses_reports_on_different_labels_or_without_details():
    with pytest.raises(SystemExit):
        ra.compare(report("rules", [row("q1")], labels="x"), report("fts", [row("q1")], labels="y"))
    with pytest.raises(SystemExit):
        ra.compare(report("rules", [], labels="x"), report("fts", [], labels="x"))


def test_grades_follow_the_meant_and_related_specs():
    rows = [
        ("p1", "MSc Computing (Artificial Intelligence and Machine Learning)", None, "计算机与数据"),
        ("p2", "MSc Computing", None, "计算机与数据"),
        ("p3", "MSc Transport with Data Science", None, "计算机与数据"),
        ("p4", "MSc Finance", "金融硕士", "商科与金融"),
    ]
    q = {"meant": {"name": r"Computing \(Artificial"}, "related": {"name": "comput", "field": "计算机与数据"}}
    assert ra.grade_rows(rows, q) == {"p1": 2, "p2": 1}
    assert ra.grade_rows(rows, {"meant": {"field": "计算机与数据"}, "related": None}) == {"p1": 2, "p2": 2, "p3": 2}
    assert ra.grade_rows(rows, {"meant": {"name": "金融"}}) == {"p4": 2}  # the stored Chinese name counts
    assert ra.grade_rows(rows, {"meant": {"ids": ["p3"]}}) == {"p3": 2}
    assert ra.grade_rows(rows, {"meant": {"all": True}}) == {"p1": 2, "p2": 2, "p3": 2, "p4": 2}
    with pytest.raises(ValueError):
        ra.grade_rows(rows, {"meant": {}})


def test_label_rules_are_checked_without_a_database():
    good = {"id": "n1", "split": "tune", "type": "synonym", "intent": ra.REQUIREMENT_INTENT, "question": "x",
            "schools": ["s"], "answerable": True, "meant": {"name": "x"}, "related": None, "grades": {"p": 2}}
    assert ra.label_problems(good) == []
    assert ra.label_problems({**good, "grades": {"p": 1}})  # answerable needs a grade-2 row
    assert ra.label_problems({**good, "answerable": False})  # unanswerable has no graded rows
    assert ra.label_problems({**good, "grades": {"p": 3}})
    assert ra.label_problems({**good, "type": "other"})
    assert ra.label_problems({**good, "split": "test"})


def test_the_committed_set_is_well_formed():
    data = json.loads(ra.QUESTIONS_FILE.read_text(encoding="utf-8"))
    questions = data["questions"]
    assert len({q["id"] for q in questions}) == len(questions)
    problems = [p for q in questions for p in ra.label_problems(q)]
    assert problems == []
    assert "no human review" in data["description"]
    requirement = [q for q in questions if q["intent"] == ra.REQUIREMENT_INTENT]
    assert {q["type"] for q in requirement} == set(ra.QUESTION_TYPES) - {"other_intent"}


def test_vector_rankings_are_refused_without_a_key(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "embed_api_key", "")
    with pytest.raises(SystemExit, match="EMBED_API_KEY"):
        ra.check_vectors(None, "vector")
    with pytest.raises(SystemExit, match="EMBED_API_KEY"):
        ra.check_vectors(None, "hybrid")
    ra.check_vectors(None, "fts")  # the model-free rankings need nothing


def test_embedding_summary_is_not_applicable_without_vectors_and_counts_fallbacks_with_them():
    plain = [{"has_school": True, "fell_back": False, "embed_tokens": 0, "embed_calls": 0}]
    assert ra.embedding_summary(plain, "fts", price_cny_per_mtok=0.0) == {
        "embedded_queries": 0, "fallbacks": None, "fallback_rate": None,
        "mean_tokens_per_query": None, "cost_cny_per_query": None,
    }
    vec = [
        {"has_school": True, "fell_back": False, "embed_tokens": 10, "embed_calls": 1},
        {"has_school": True, "fell_back": True, "embed_tokens": 0, "embed_calls": 1},
        {"has_school": False, "fell_back": False, "embed_tokens": 6, "embed_calls": 1},
    ]
    out = ra.embedding_summary(vec, "hybrid", price_cny_per_mtok=0.5)
    assert out["fallbacks"] == 1 and out["fallback_rate"] == 0.5
    assert out["mean_tokens_per_query"] == pytest.approx(16 / 3)
    assert out["cost_cny_per_query"] == pytest.approx(16 / 3 * 0.5 / 1_000_000)
