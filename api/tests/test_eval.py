from evals.run_eval import CASES, evaluate


def test_eval_suite_has_ten_cases_and_meets_quality_bar() -> None:
    metrics = evaluate()
    assert len(CASES) == 10
    assert metrics["hard_constraint_accuracy"] >= 0.9
    assert metrics["missing_information_accuracy"] == 1.0
    assert metrics["citation_coverage"] == 1.0
    assert metrics["tool_success_rate"] == 1.0
