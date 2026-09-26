import sys
from types import SimpleNamespace

from app.agent_trace import emit_workflow_trace


def test_langfuse_trace_exports_only_allowlisted_metadata(monkeypatch) -> None:
    captured = {}

    class Observation:
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def update(self, **kwargs): captured.update(kwargs)

    class Client:
        def start_as_current_observation(self, **kwargs):
            captured["observation"] = kwargs
            return Observation()
        def flush(self): captured["flushed"] = True

    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setitem(sys.modules, "langfuse", SimpleNamespace(get_client=Client))

    sent = emit_workflow_trace(
        nodes=["classify", "retrieve_official_facts", "evidence_gate", "compose_reply"],
        intent="official_knowledge", route="retrieve_official_facts",
        source_count=2, latency_ms=14.2, no_answer=False,
    )

    assert sent is True
    metadata = captured["metadata"]
    assert metadata["intent.class"] == "knowledge"
    assert metadata["route.class"] == "retrieve"
    assert metadata["source_count"] == 2
    assert metadata["node.name"] == "answer"
    assert "input" not in metadata and "output" not in metadata
    assert captured["flushed"] is True


def test_langfuse_export_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("LANGFUSE_ENABLED", raising=False)
    assert emit_workflow_trace(nodes=[], intent="other", route="general_response", source_count=0, latency_ms=1, no_answer=False) is False
