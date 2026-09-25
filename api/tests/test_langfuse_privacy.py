import json

from app.observability_fields import safe_agent_attributes


def test_trace_attributes_allow_only_bounded_known_fields_and_drop_sentinels() -> None:
    values = safe_agent_attributes({
        "intent.class": "program_search",
        "node.name": "retrieve",
        "outcome": "success",
        "token_count": 17,
        "query": "private-query-marker",
        "profile": "private-profile-marker",
        "email": "private@example.com",
        "exception": "private-error-marker",
        "source_excerpt": "private-source-marker",
    })
    rendered = json.dumps(values)
    assert values == {
        "intent.class": "program_search",
        "node.name": "retrieve",
        "outcome": "success",
        "token_count": 17,
    }
    for sentinel in ("private-query-marker", "private-profile-marker", "private@example.com", "private-error-marker", "private-source-marker"):
        assert sentinel not in rendered


def test_trace_attributes_reject_unknown_enum_values_and_clamp_counts() -> None:
    values = safe_agent_attributes({
        "intent.class": "private-user-value",
        "outcome": "custom-error-with-private-text",
        "token_count": 10**20,
        "latency_ms": -4,
        "workflow.version": "v1" * 100,
    })
    assert values == {"token_count": 1_000_000_000, "latency_ms": 0}
