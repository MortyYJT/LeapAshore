from app.graph.live_workflow import run_live_workflow
from app.models import ApplicantProfile


PROFILE = ApplicantProfile(
    undergraduate_school="评测大学", school_tier="双非", undergraduate_major="软件工程",
    gpa=82, gpa_scale=100, target_field="计算机与数据", intake="2027 S1",
    english_score="IELTS 6.5", coursework_summary="高等数学、数据结构",
)


def test_live_graph_routes_official_question_through_retrieval_gate_and_citation() -> None:
    turn = run_live_workflow("UQ 数据科学 IELTS 和数学先修要求", PROFILE)

    assert turn.state.intent == "official_knowledge"
    assert turn.state.route == "retrieve_official_facts"
    assert turn.state.confidence_decision["allowed"] is True
    assert turn.state.knowledge_evidence
    assert turn.state.citations[0]["url"].startswith("https://")
    assert "来源：" in turn.state.final_reply
    assert turn.nodes == (
        "load_snapshot", "resolve_context", "classify", "route",
        "retrieve_official_facts", "evidence_gate", "compose_reply",
    )


def test_live_graph_refuses_off_corpus_fact_without_evidence() -> None:
    turn = run_live_workflow("哈佛医学院录取要求", PROFILE)

    assert turn.state.route == "retrieve_official_facts"
    assert turn.state.confidence_decision["reason"] == "no_evidence"
    assert turn.state.knowledge_evidence == []
    assert "没有足够" in turn.state.final_reply


def test_live_graph_runs_deterministic_recommendation_node() -> None:
    turn = run_live_workflow("帮我规划申请选校", PROFILE)

    assert turn.state.route == "deterministic_recommendation"
    assert turn.state.recommendation is not None
    assert "deterministic_recommendation" in turn.nodes
    assert "retrieve_official_facts" not in turn.nodes
