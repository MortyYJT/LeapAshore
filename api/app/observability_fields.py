"""Allowlisted, low-sensitivity fields suitable for an external trace backend."""

from collections.abc import Mapping
from typing import TypeAlias

TraceValue: TypeAlias = str | int | float | bool

_ENUMS: dict[str, frozenset[str]] = {
    "intent.class": frozenset({"program_search", "profile_review", "task_help", "knowledge", "unknown"}),
    "route.class": frozenset({"answer", "retrieve", "clarify", "handoff", "unknown"}),
    "node.name": frozenset({"classify", "retrieve", "answer", "confidence_gate", "fallback", "unknown"}),
    "outcome": frozenset({"success", "error", "cancelled", "no_answer", "fallback"}),
    "workflow.version": frozenset({"v1", "v2"}),
}
_COUNTS = frozenset({"token_count", "source_count", "tool_count"})
_DURATIONS = frozenset({"latency_ms"})


def safe_agent_attributes(values: Mapping[str, object]) -> dict[str, TraceValue]:
    """Return only fixed-name, bounded values; never stringify arbitrary state."""
    safe: dict[str, TraceValue] = {}
    for name, allowed in _ENUMS.items():
        value = values.get(name)
        if isinstance(value, str) and value in allowed:
            safe[name] = value
    for name in _COUNTS:
        value = values.get(name)
        if isinstance(value, int) and not isinstance(value, bool):
            safe[name] = min(1_000_000_000, max(0, value))
    for name in _DURATIONS:
        value = values.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            safe[name] = min(3_600_000, max(0, value))
    return safe
