from evals.run_eval import CASES, evaluate
from evals.run_advisor_eval import CASES as ADVISOR_CASES, evaluate_advisor
from evals.run_rag_eval import CASES as RAG_CASES, evaluate_rag


def test_eval_suite_has_ten_cases_and_meets_quality_bar() -> None:
    metrics = evaluate()
    assert len(CASES) == 10
    assert metrics["hard_constraint_accuracy"] >= 0.9
    assert metrics["missing_information_accuracy"] == 1.0
    assert metrics["citation_coverage"] == 1.0
    assert metrics["tool_success_rate"] == 1.0


def test_advisor_eval_has_twenty_cases_and_meets_agent_quality_bar() -> None:
    metrics = evaluate_advisor()
    assert len(ADVISOR_CASES) >= 20
    assert metrics["tool_selection_accuracy"] >= 0.9
    assert metrics["citation_fact_hallucinations"] == 0


def test_rag_eval_has_twelve_cases_and_meets_retrieval_quality_bar() -> None:
    metrics = evaluate_rag()
    assert len(RAG_CASES) >= 12
    assert metrics["top_one_program_accuracy"] >= 0.9
    assert metrics["top_one_section_accuracy"] >= 0.9
    assert metrics["program_recall_at_3"] == 1.0
    assert metrics["citation_coverage"] == 1.0
