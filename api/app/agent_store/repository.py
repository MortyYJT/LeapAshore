from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from .models import AdvisorThreadProjection, ProjectionReceipt

PROJECTION_NAME = "mysql-agent"
FORBIDDEN_PAYLOAD_KEYS = {"password", "token", "email", "prompt", "reply", "question", "profile", "message", "content"}


def _validate_event(event: dict[str, Any]) -> None:
    if event.get("schema_version") != 1:
        raise ValueError("unsupported event schema_version")
    if PROJECTION_NAME not in event.get("projection_targets", []):
        raise ValueError("event does not target mysql-agent")
    if event.get("event_type") != "advisor.thread.changed":
        raise ValueError("unsupported MySQL projection event_type")
    payload = event.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("event payload must be an object")
    if FORBIDDEN_PAYLOAD_KEYS.intersection(payload):
        raise ValueError("event payload contains a forbidden field")
    for key in ("event_id", "aggregate_id", "source_revision"):
        if not event.get(key):
            raise ValueError(f"event {key} is required")
    if int(event["source_revision"]) < 0:
        raise ValueError("source_revision must not be negative")


class AgentStore:
    def __init__(self, sessions: async_sessionmaker):
        self._sessions = sessions

    async def healthcheck(self) -> bool:
        async with self._sessions() as session:
            await session.execute(text("SELECT 1"))
        return True

    async def apply_event(self, event: dict[str, Any]) -> str:
        _validate_event(event)
        async with self._sessions.begin() as session:
            receipt_key = (event["event_id"], PROJECTION_NAME)
            receipt = await session.get(ProjectionReceipt, receipt_key)
            if receipt:
                return "duplicate"
            projection = await session.get(AdvisorThreadProjection, event["aggregate_id"])
            revision = int(event["source_revision"])
            outcome = "applied"
            if projection and revision < projection.source_revision:
                outcome = "stale"
            elif projection and revision == projection.source_revision:
                incoming_hash = event["payload"].get("content_hash")
                if incoming_hash != projection.content_hash:
                    raise ValueError("reconciliation conflict: same revision has different content_hash")
                outcome = "stale"
            else:
                payload = event["payload"]
                values = {
                    "owner_ref": str(payload["owner_ref"]),
                    "source_revision": revision,
                    "source_ref": str(payload["source_ref"]),
                    "status": str(payload["status"]),
                    "content_hash": payload.get("content_hash"),
                }
                if projection:
                    for name, value in values.items():
                        setattr(projection, name, value)
                else:
                    session.add(AdvisorThreadProjection(aggregate_id=event["aggregate_id"], **values))
            session.add(ProjectionReceipt(event_id=event["event_id"], projection_name=PROJECTION_NAME, outcome=outcome))
            return outcome

    async def get_projection(self, aggregate_id: str) -> AdvisorThreadProjection | None:
        async with self._sessions() as session:
            return await session.get(AdvisorThreadProjection, aggregate_id)

    async def delete_subject(self, subject_ref: str) -> int:
        async with self._sessions.begin() as session:
            result = await session.execute(
                select(AdvisorThreadProjection).where(AdvisorThreadProjection.owner_ref == subject_ref)
            )
            rows = result.scalars().all()
            for row in rows:
                await session.delete(row)
            return len(rows)
