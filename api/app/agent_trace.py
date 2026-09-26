"""Optional Langfuse export using an explicit low-sensitivity metadata allowlist."""

import importlib
import logging
import os
from collections.abc import Sequence
from time import perf_counter

from .observability_fields import safe_agent_attributes

logger = logging.getLogger(__name__)


def emit_workflow_trace(
    *,
    nodes: Sequence[str],
    intent: str,
    route: str,
    source_count: int,
    latency_ms: float,
    no_answer: bool,
) -> bool:
    """Emit metadata only; never include state, query, profile, citations, or model text."""
    if os.getenv("LANGFUSE_ENABLED", "false").lower() not in {"1", "true", "yes", "on"}:
        return False
    intent_class = {
        "planning": "program_search", "official_knowledge": "knowledge",
        "profile_clarification": "profile_review", "action": "task_help", "other": "unknown",
    }.get(intent, "unknown")
    route_class = {
        "deterministic_recommendation": "answer", "retrieve_official_facts": "retrieve",
        "clarify": "clarify", "deterministic_action": "handoff", "general_response": "answer",
    }.get(route, "unknown")
    attrs = safe_agent_attributes({
        "intent.class": intent_class,
        "route.class": route_class,
        "workflow.version": "v1",
        "prompt.version": "v2",
        "source_count": source_count,
        "latency_ms": latency_ms,
        "outcome": "no_answer" if no_answer else "success",
    })
    if nodes:
        node_alias = {
            "classify": "classify", "retrieve_official_facts": "retrieve",
            "evidence_gate": "confidence_gate", "compose_reply": "answer",
        }
        attrs.update(safe_agent_attributes({"node.name": node_alias.get(nodes[-1], "unknown")}))
    started = perf_counter()
    try:
        get_client = importlib.import_module("langfuse").get_client
        client = get_client()
        with client.start_as_current_observation(as_type="span", name="offerpilot.agent.workflow") as span:
            span.update(metadata=attrs)
        client.flush()
        return True
    except Exception as error:
        logger.warning(
            "Langfuse workflow export unavailable",
            extra={"error_type": type(error).__name__, "export_latency_ms": round((perf_counter() - started) * 1000, 2)},
        )
        return False
