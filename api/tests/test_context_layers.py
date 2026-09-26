import json

from app.services.context_layers import build_context_layers


def test_context_layers_keep_profile_evidence_and_recent_turns_within_budget() -> None:
    result = build_context_layers(
        profile={"gpa": 82, "undergraduate_major": "Software Engineering"},
        portfolio={"choices": ["uq-master-data-science"]},
        history=[{"role": "user", "content": f"old-{index}-" + "x" * 60} for index in range(12)],
        message="UQ IELTS requirements?",
        evidence=[{"source_id": "official-1", "content": "IELTS 6.5", "url": "https://example.edu"}],
        total_char_budget=700,
    )

    assert set(result) == {"profile", "application", "conversation", "evidence"}
    assert "gpa" in result["profile"]
    assert "official-1" in result["evidence"]
    assert "old-0-" not in result["conversation"]
    assert sum(len(value) for value in result.values()) <= 700
    for layer in result.values():
        json.loads(layer)


def test_context_layers_redact_sensitive_values_from_all_layers() -> None:
    result = build_context_layers(
        profile={"email": "person@example.com", "name": "Private Name", "gpa": 80},
        history=[{"role": "user", "content": "my email is person@example.com"}],
        message="help",
        sensitive_values=["person@example.com", "Private Name"],
    )
    serialized = " ".join(result.values())
    assert "person@example.com" not in serialized
    assert "Private Name" not in serialized
