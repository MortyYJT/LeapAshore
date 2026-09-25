import asyncio

import pytest
from pydantic import ValidationError

from app.graph.routing import classify_intent, route_intent
from app.graph.state import AdvisorState
from app.graph.runtime import arun_advisor_turn, run_advisor_turn
from app.graph.build import build_advisor_graph
from app.graph.checkpoint import create_checkpointer, opaque_thread_key, validate_checkpoint_path


def test_unsupported_state_schema_version_is_rejected() -> None:
    with pytest.raises(ValidationError, match="schema_version"):
        AdvisorState.model_validate({"schema_version": 999})


@pytest.mark.parametrize(
    ("message", "intent"),
    [
        ("帮我规划申请路线", "planning"),
        ("墨尔本大学的语言要求是什么", "official_knowledge"),
        ("你还需要我补充什么", "profile_clarification"),
        ("帮我创建申请任务", "action"),
        ("你好", "other"),
    ],
)
def test_intent_boundaries(message: str, intent: str) -> None:
    assert classify_intent(message) == intent


def test_ambiguous_and_missing_profile_routes_to_clarification() -> None:
    assert route_intent("planning", ambiguous=True, profile_snapshot=None) == "clarify"


def test_high_impact_route_forces_deterministic_node() -> None:
    assert route_intent("action", ambiguous=False, profile_snapshot={"x": 1}, high_impact=True) == "deterministic_action"


def test_graph_emits_ordered_deterministic_node_events() -> None:
    events: list[str] = []
    graph = build_advisor_graph(on_node=events.append)

    result = graph.invoke(AdvisorState(messages=[{"role": "user", "content": "你好"}]).model_dump())

    assert events == ["load_snapshot", "resolve_context", "classify", "route", "general_response", "evidence_gate", "compose_reply"]
    assert result["final_reply"]


def test_checkpoint_key_is_stable_and_does_not_contain_raw_identifiers() -> None:
    key = opaque_thread_key("private-user", "private-thread", key="test-key")
    assert key == opaque_thread_key("private-user", "private-thread", key="test-key")
    assert "private-user" not in key and "private-thread" not in key


def test_production_checkpoint_rejects_ephemeral_path(tmp_path) -> None:
    with pytest.raises(ValueError, match="持久化卷"):
        validate_checkpoint_path("/tmp/offerpilot.sqlite", production=True)


def test_checkpoint_survives_saver_reopen_without_advancing_product_revision(tmp_path) -> None:
    path = tmp_path / "graph.sqlite"
    config = {"configurable": {"thread_id": opaque_thread_key("user", "thread", key="test-key")}}
    graph_input = AdvisorState(expected_revision=4).model_dump()

    async def exercise() -> None:
        async with create_checkpointer(path) as saver:
            graph = build_advisor_graph(checkpointer=saver)
            first = await graph.ainvoke(graph_input, config)
            assert first["expected_revision"] == 4
        async with create_checkpointer(path) as saver:
            graph = build_advisor_graph(checkpointer=saver)
            resumed = await graph.aget_state(config)
        assert resumed.values["expected_revision"] == 4

    asyncio.run(exercise())


def test_checkpoint_runtime_rejects_private_payloads(tmp_path) -> None:
    async def exercise() -> None:
        async with create_checkpointer(tmp_path / "graph.sqlite") as saver:
            with pytest.raises(ValueError, match="profiles or raw messages"):
                await arun_advisor_turn(
                    AdvisorState(messages=[{"role": "user", "content": "private"}]),
                    checkpointer=saver,
                    configurable={"thread_id": opaque_thread_key("user", "thread", key="test-key")},
                )

        async with create_checkpointer(tmp_path / "safe-id.sqlite") as saver:
            with pytest.raises(ValueError, match="thread_id"):
                await arun_advisor_turn(AdvisorState(), checkpointer=saver, configurable={"thread_id": "raw-thread"})

    asyncio.run(exercise())


def test_runtime_adapter_calls_injected_deterministic_handler() -> None:
    called: list[str] = []

    def recommendation(_state: AdvisorState) -> dict:
        called.append("recommendation")
        return {"recommendation": {"kind": "deterministic"}}

    result = run_advisor_turn(
        AdvisorState(
            profile_snapshot={"target": "course"},
            messages=[{"role": "user", "content": "帮我规划申请路线"}],
        ),
        handlers={"deterministic_recommendation": recommendation},
    )

    assert called == ["recommendation"]
    assert result.recommendation == {"kind": "deterministic"}


def test_async_runtime_adapter_matches_sync_node_order() -> None:
    async def exercise() -> None:
        events: list[str] = []
        result = await arun_advisor_turn(
            {"messages": [{"role": "user", "content": "你好"}]},
            on_node=events.append,
        )
        assert result.final_reply
        assert events[0:4] == ["load_snapshot", "resolve_context", "classify", "route"]

    asyncio.run(exercise())
