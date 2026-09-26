from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import logging
import os
from time import perf_counter
from typing import Any

from ..models import ApplicantProfile, KnowledgeSearchRequest, KnowledgeSearchResponse
from ..agent_trace import emit_workflow_trace
from ..services.confidence import evaluate_evidence
from ..services.context_layers import build_context_layers
from ..services.knowledge_rag import grounded_fallback_answer, infer_program_slugs, retrieve_official_knowledge
from ..services.hybrid_knowledge import configured_hybrid_retrieval
from ..services.agent import run_recommendation_agent
from .runtime import NodeHandler, run_advisor_turn
from .state import AdvisorState

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkflowTurn:
    state: AdvisorState
    knowledge: KnowledgeSearchResponse
    nodes: tuple[str, ...]


def run_live_workflow(
    message: str,
    profile: ApplicantProfile,
    history: Sequence[Mapping[str, str]] = (),
    *,
    sensitive_values: Sequence[str] = (),
    retriever: Callable[[KnowledgeSearchRequest], KnowledgeSearchResponse] | None = None,
    published_versions: Sequence[Any] = (),
    cloud_processing_consented: bool = False,
) -> WorkflowTurn:
    """Run one in-process product turn through the deterministic StateGraph.

    The graph is intentionally not checkpointed here: raw applicant state and messages
    stay within the existing authenticated API request and PostgreSQL turn lifecycle.
    """
    started = perf_counter()
    events: list[str] = []
    response = KnowledgeSearchResponse(
        query=message,
        retrieval_version="not-run",
        generated_at=datetime.now(UTC),
        hits=[],
        coverage_notice="当前问题未触发官方知识检索。",
    )

    def load_snapshot(_state: AdvisorState) -> dict[str, Any]:
        return {"profile_snapshot": profile.model_dump(mode="json")}

    def resolve_context(_state: AdvisorState) -> dict[str, Any]:
        layers = build_context_layers(
            profile=profile.model_dump(mode="json"),
            history=history,
            message=message,
            sensitive_values=list(sensitive_values),
        )
        return {"context_layers": layers}

    def retrieve(_state: AdvisorState) -> dict[str, Any]:
        nonlocal response
        request = KnowledgeSearchRequest(
            query=message,
            target_degree_level=profile.target_degree_level,
            target_field=profile.target_field,
            program_slugs=infer_program_slugs(message),
            top_k=5,
        )
        if retriever:
            response = retriever(request)
        elif os.getenv("HYBRID_RAG_ENABLED", "false").lower() in {"1", "true", "yes", "on"}:
            try:
                response = configured_hybrid_retrieval(
                    request,
                    published_versions,
                    cloud_processing_consented=cloud_processing_consented,
                )
            except Exception as error:
                logger.warning("Hybrid retrieval degraded to BM25", extra={"error_type": type(error).__name__})
                response = retrieve_official_knowledge(request).model_copy(update={
                    "retrieval_version": "official-knowledge-bm25-fallback-v1",
                })
        else:
            response = retrieve_official_knowledge(request)
        hits = [hit.model_dump(mode="json") for hit in response.hits]
        return {
            "knowledge_evidence": hits,
            "citations": [
                {"source_id": hit.source.id, "title": hit.source.title, "url": hit.source.url,
                 "version_id": hit.source.version_id, "verified_at": hit.source.verified_at}
                for hit in response.hits
            ],
        }

    def recommend(_state: AdvisorState) -> dict[str, Any]:
        result = run_recommendation_agent(profile)
        return {"recommendation": result.model_dump(mode="json")}

    def gate(state: AdvisorState) -> dict[str, Any]:
        if state.route != "retrieve_official_facts":
            return {"confidence_decision": {"allowed": True, "reason": "not_applicable", "gate_version": "evidence-gate-v1"}}
        from ..models import KnowledgeEvidence

        evidence = [KnowledgeEvidence.model_validate(item) for item in state.knowledge_evidence]
        decision = evaluate_evidence(evidence)
        updates: dict[str, Any] = {"confidence_decision": decision.__dict__}
        if not decision.allowed:
            updates["final_reply"] = "我目前没有足够、可核验且在复核期限内的官方来源，暂时不能确认这个要求。"
        return updates

    def compose(state: AdvisorState) -> dict[str, Any]:
        if state.route == "retrieve_official_facts":
            from ..models import KnowledgeEvidence

            hits = [KnowledgeEvidence.model_validate(item) for item in state.knowledge_evidence]
            answer = grounded_fallback_answer(message, hits) if state.confidence_decision.get("allowed") else None
            return {"final_reply": answer or state.final_reply or "我目前没有足够的官方证据回答这个问题。"}
        if state.route == "deterministic_recommendation":
            return {"final_reply": "已按确定性申请规则完成评估；具体项目组合和硬门槛以结构化评估结果为准。"}
        return {"final_reply": state.final_reply or "我可以继续帮你规划申请、核对官方要求或完善资料。"}

    handlers: dict[str, NodeHandler] = {
        "load_snapshot": load_snapshot,
        "resolve_context": resolve_context,
        "retrieve_official_facts": retrieve,
        "deterministic_recommendation": recommend,
        "evidence_gate": gate,
        "compose_reply": compose,
    }
    state = run_advisor_turn(
        AdvisorState(messages=[*list(history), {"role": "user", "content": message}]),
        handlers=handlers,
        on_node=events.append,
    )
    emit_workflow_trace(
        nodes=events,
        intent=state.intent,
        route=state.route,
        source_count=len(state.knowledge_evidence),
        latency_ms=(perf_counter() - started) * 1000,
        no_answer=state.confidence_decision.get("reason") == "no_evidence",
    )
    return WorkflowTurn(state=state, knowledge=response, nodes=tuple(events))
