import asyncio

from app.agent_store.projector import project_batch


class FakePostgres:
    def __init__(self, rows):
        self.rows = rows
        self.acked = []
        self.retried = []

    def claim_projection_events(self, _worker, *, limit):
        return self.rows[:limit]

    def acknowledge_projection_event(self, _worker, event_id):
        self.acked.append(event_id)
        return True

    def retry_projection_event(self, _worker, event_id, *, error_class, delay_seconds):
        self.retried.append((event_id, error_class, delay_seconds))
        return True


class FakeAgentStore:
    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.events = []

    async def apply_event(self, event):
        self.events.append(event)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def row(event_id, revision=1, attempts=1):
    return {
        "event_id": event_id, "event_type": "advisor.thread.changed", "schema_version": 1,
        "aggregate_type": "advisor_thread", "aggregate_id": "opaque-thread", "source_revision": revision,
        "occurred_at": "2026-09-25T00:00:00Z", "attempts": attempts,
        "payload": {"owner_ref": "opaque-owner", "source_ref": "opaque-thread", "status": "active", "message_count": 1},
    }


def test_projector_acknowledges_applied_duplicate_and_stale_events() -> None:
    async def exercise() -> None:
        postgres = FakePostgres([row("a"), row("b"), row("c")])
        mysql = FakeAgentStore(["applied", "duplicate", "stale"])
        result = await project_batch(postgres, mysql)
        assert result.claimed == 3
        assert (result.applied, result.duplicates, result.stale) == (1, 1, 1)
        assert postgres.acked == ["a", "b", "c"]
        assert mysql.events[0]["projection_targets"] == ["mysql-agent"]

    asyncio.run(exercise())


def test_projector_retries_with_safe_error_class_and_never_logs_event_payload() -> None:
    async def exercise() -> None:
        postgres = FakePostgres([row("a", attempts=3)])
        mysql = FakeAgentStore([RuntimeError("private source text")])
        result = await project_batch(postgres, mysql)
        assert result.retried == 1
        assert result.error_classes == ("RuntimeError",)
        assert postgres.retried == [("a", "RuntimeError", 8)]
        assert postgres.acked == []

    asyncio.run(exercise())
