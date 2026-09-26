from __future__ import annotations

from hashlib import sha256
from math import ceil
import json
from statistics import median
from time import perf_counter
from typing import Any

from app.graph.live_workflow import run_live_workflow
from app.models import ApplicantProfile
from evals.run_rag_eval import CASES as RAG_CASES, NO_ANSWER_CASES

PROFILE = ApplicantProfile(
    undergraduate_school="评测大学", school_tier="双非", undergraduate_major="软件工程",
    gpa=82, gpa_scale=100, target_field="计算机与数据", intake="2027 S1",
    english_score="IELTS 6.5", coursework_summary="高等数学、数据结构、数据库",
)

CASES: list[dict[str, Any]] = [
    *[
        {"id": f"rag-{index + 1}", "query": case["query"], "intent": "official_knowledge",
         "expected_route": "retrieve_official_facts", "answerable": True,
         "program": case["program"], "section": case["section"]}
        for index, case in enumerate(RAG_CASES)
    ],
    *[
        {"id": f"reject-{index + 1}", "query": query,
         "intent": "other" if "天气" in query else "official_knowledge",
         "expected_route": "general_response" if "天气" in query else "retrieve_official_facts",
         "answerable": False}
        for index, query in enumerate(NO_ANSWER_CASES)
    ],
]


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[min(len(ordered) - 1, max(0, ceil(len(ordered) * percentile) - 1))]


def evaluate_workflow() -> dict[str, Any]:
    encoded_cases = json.dumps(CASES, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    route_ok = gate_tp = gate_fp = gate_fn = retrieval_hit = section_hit = citation_ok = recall_hit = 0
    reciprocal_rank = 0.0
    answerable_count = sum(case["answerable"] for case in CASES)
    gate_reject_cases = sum(not case["answerable"] and case["expected_route"] == "retrieve_official_facts" for case in CASES)
    latencies: list[float] = []
    node_paths: dict[str, int] = {}

    for case in CASES:
        started = perf_counter()
        turn = run_live_workflow(case["query"], PROFILE)
        latencies.append((perf_counter() - started) * 1000)
        route_ok += int(turn.state.intent == case["intent"] and turn.state.route == case["expected_route"])
        node_key = ">".join(turn.nodes)
        node_paths[node_key] = node_paths.get(node_key, 0) + 1
        allowed = bool(turn.state.confidence_decision.get("allowed"))
        if case["answerable"]:
            gate_tp += int(allowed)
            if turn.knowledge.hits:
                first = turn.knowledge.hits[0]
                retrieval_hit += int(first.program_slug == case["program"])
                section_hit += int(first.program_slug == case["program"] and first.section == case["section"])
                recall_hit += int(any(hit.program_slug == case["program"] for hit in turn.knowledge.hits))
                matching_ranks = [
                    rank for rank, hit in enumerate(turn.knowledge.hits, start=1)
                    if hit.program_slug == case["program"] and hit.section == case["section"]
                ]
                reciprocal_rank += 1 / min(matching_ranks) if matching_ranks else 0.0
                citation_ok += int(
                    all(hit.source.url.startswith("https://") and hit.source.id for hit in turn.knowledge.hits)
                    and "https://" in turn.state.final_reply
                )
        else:
            if case["expected_route"] == "retrieve_official_facts":
                gate_fp += int(allowed)
                gate_fn += int(not allowed)

    return {
        "workflow_version": "offerpilot-stategraph-v1",
        "retrieval_version": "official-knowledge-bm25-1.0.0",
        "confidence_gate_version": "evidence-gate-v1",
        "dataset_sha256": sha256(encoded_cases).hexdigest(),
        "cases": len(CASES),
        "answerable_cases": answerable_count,
        "no_answer_cases": len(CASES) - answerable_count,
        "gate_applicable_no_answer_cases": gate_reject_cases,
        "intent_route_accuracy": round(route_ok / len(CASES), 4),
        "answerable_retrieval_top1_accuracy": round(retrieval_hit / answerable_count, 4),
        "answerable_recall_at_5": round(recall_hit / answerable_count, 4),
        "answerable_mrr_at_5": round(reciprocal_rank / answerable_count, 4),
        "answerable_section_top1_accuracy": round(section_hit / answerable_count, 4),
        "evidence_gate_answerable_recall": round(gate_tp / answerable_count, 4),
        "evidence_gate_no_answer_rejection_accuracy": round(gate_fn / gate_reject_cases, 4),
        "evidence_gate_false_accepts": gate_fp,
        "citation_and_answer_url_coverage": round(citation_ok / answerable_count, 4),
        "latency_ms_median": round(median(latencies), 3),
        "latency_ms_p95_nearest_rank": round(_percentile(latencies, 0.95), 3),
        "node_paths": node_paths,
    }


if __name__ == "__main__":
    print(json.dumps(evaluate_workflow(), ensure_ascii=False, indent=2))
