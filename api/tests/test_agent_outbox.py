from app.agent_store.events import advisor_thread_changed_event


def test_thread_projection_event_is_deterministic_and_contains_no_message_content() -> None:
    first = advisor_thread_changed_event("internal-user-id", "random-thread-id", 2, 4)
    replay = advisor_thread_changed_event("internal-user-id", "random-thread-id", 2, 4)
    assert first["event_id"] == replay["event_id"]
    assert first["aggregate_id"] == "random-thread-id"
    assert first["source_revision"] == 2
    assert first["payload"]["message_count"] == 4
    assert "internal-user-id" not in str(first)
    assert "content" not in first["payload"]
    assert "message" not in first["payload"]
