import asyncio
import os

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agent_store.models import AgentBase
from app.agent_store.repository import AgentStore


def event(event_id: str, revision: int, status: str = "active") -> dict:
    return {
        "event_id": event_id,
        "event_type": "advisor.thread.changed",
        "schema_version": 1,
        "aggregate_type": "advisor_thread",
        "aggregate_id": "opaque-thread-1",
        "source_revision": revision,
        "occurred_at": "2026-09-25T00:00:00Z",
        "projection_targets": ["mysql-agent"],
        "payload": {"owner_ref": "owner-opaque-ref", "source_ref": "pg-thread-1", "content_hash": None, "status": status},
    }


def test_agent_projection_is_idempotent_and_rejects_stale_revision() -> None:
    async def exercise() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(AgentBase.metadata.create_all)
        store = AgentStore(async_sessionmaker(engine, expire_on_commit=False))
        first = await store.apply_event(event("evt-2", 2))
        replay = await store.apply_event(event("evt-2", 2))
        stale = await store.apply_event(event("evt-1", 1, "old"))
        projection = await store.get_projection("opaque-thread-1")
        assert first == "applied"
        assert replay == "duplicate"
        assert stale == "stale"
        assert projection.source_revision == 2
        assert projection.status == "active"
        with pytest.raises(ValueError, match="reconciliation conflict"):
            await store.apply_event({**event("evt-conflict", 2), "payload": {"source_ref": "pg-thread-1", "status": "active", "content_hash": "b" * 64}})
        assert await store.delete_subject("owner-opaque-ref") == 1
        assert await store.get_projection("opaque-thread-1") is None
        await engine.dispose()

    asyncio.run(exercise())


def test_projection_rejects_unknown_schema_and_sensitive_payload_fields() -> None:
    from app.agent_store.repository import _validate_event

    with pytest.raises(ValueError, match="schema_version"):
        _validate_event({**event("evt", 1), "schema_version": 9})
    with pytest.raises(ValueError, match="forbidden"):
        _validate_event({**event("evt", 1), "payload": {"source_ref": "x", "status": "active", "message": "private"}})


@pytest.mark.skipif(not os.getenv("MYSQL_TEST_URL"), reason="MYSQL_TEST_URL is not configured")
def test_mysql_agent_store_connects_to_disposable_mysql() -> None:
    async def exercise() -> None:
        engine = create_async_engine(os.environ["MYSQL_TEST_URL"], pool_pre_ping=True)
        async with engine.begin() as connection:
            await connection.run_sync(AgentBase.metadata.create_all)
        assert await AgentStore(async_sessionmaker(engine)).healthcheck()
        await engine.dispose()

    asyncio.run(exercise())
