import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

_SENSITIVE_KEYS = {"email", "name", "display_name", "user_id", "account_id", "phone", "password", "token"}
_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")


def _redact(value: Any, sensitive_values: Sequence[str]) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "[redacted]" if str(key).lower() in _SENSITIVE_KEYS else _redact(item, sensitive_values)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item, sensitive_values) for item in value]
    if isinstance(value, str):
        cleaned = _EMAIL.sub("[redacted-email]", value)
        for secret in sensitive_values:
            if secret:
                cleaned = cleaned.replace(secret, "[redacted]")
        return cleaned
    return value


def _encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _fit(value: Any, budget: int) -> str:
    """Bound a JSON layer without cutting JSON syntax or field boundaries."""
    while len(_encode(value)) > budget:
        if isinstance(value, dict) and value:
            key = max(value, key=lambda item: len(_encode(value[item])))
            child = value[key]
            if isinstance(child, str) and len(child) > 8:
                value[key] = child[: max(1, len(child) // 2)]
            elif isinstance(child, (dict, list)) and child:
                if isinstance(child, list):
                    child.pop(0 if key == "recent_messages" else -1)
                else:
                    value[key] = json.loads(_fit(child, max(2, budget - 16)))
            else:
                value.pop(key)
        elif isinstance(value, list) and value:
            value.pop(0)
        elif isinstance(value, str) and len(value) > 8:
            value = value[: max(1, len(value) // 2)]
        else:
            break
    return _encode(value)


def build_context_layers(
    *,
    profile: Mapping[str, Any],
    portfolio: Any = None,
    history: Sequence[Mapping[str, str]] = (),
    message: str = "",
    evidence: Sequence[Mapping[str, Any]] = (),
    sensitive_values: Sequence[str] = (),
    total_char_budget: int = 12_000,
) -> dict[str, str]:
    """Serialize four separately budgeted context layers, preserving newest turns."""
    if total_char_budget < 200:
        raise ValueError("context budget must be at least 200 characters")
    safe_profile = _redact(dict(profile), sensitive_values)
    safe_application = _redact(portfolio or {}, sensitive_values)
    safe_history = _redact(list(history), sensitive_values)
    safe_evidence = _redact(list(evidence), sensitive_values)
    layer_payloads = {
        "profile": safe_profile,
        "application": safe_application,
        "conversation": {"recent_messages": safe_history, "current_message": _redact(message, sensitive_values)},
        "evidence": safe_evidence,
    }
    weights = {"profile": 0.22, "application": 0.18, "conversation": 0.30, "evidence": 0.30}
    budgets = {key: max(1, int(total_char_budget * weight)) for key, weight in weights.items()}
    # Trim oldest dialogue first; facts and citations remain structured and separately visible.
    while len(_encode(layer_payloads["conversation"])) > budgets["conversation"] and layer_payloads["conversation"]["recent_messages"]:
        layer_payloads["conversation"]["recent_messages"].pop(0)
    encoded = {key: _fit(value, budgets[key]) for key, value in layer_payloads.items()}
    result: dict[str, str] = {}
    remaining = total_char_budget
    for key in ("profile", "application", "conversation", "evidence"):
        budget = min(budgets[key], remaining)
        result[key] = encoded[key]
        remaining -= len(result[key])
    # Budgets can be a few characters short of the requested total due to integer rounding.
    return result
