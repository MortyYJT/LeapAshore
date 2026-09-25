import asyncio
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from .repository import AgentStore


@dataclass(frozen=True)
class ProjectionBatchResult:
    claimed: int
    applied: int
    duplicates: int
    stale: int
    retried: int
    acknowledgement_lost: int
    error_classes: tuple[str, ...]


async def project_batch(
    postgres_store: Any,
    agent_store: AgentStore,
    *,
    limit: int = 50,
    timeout_seconds: float = 5.0,
) -> ProjectionBatchResult:
    worker_id = f"agent-projector-{uuid4().hex}"
    events = await asyncio.to_thread(postgres_store.claim_projection_events, worker_id, limit=limit)
    applied = duplicates = stale = retried = ack_lost = 0
    error_classes: list[str] = []
    for row in events:
        event = {
            "event_id": row["event_id"],
            "event_type": row["event_type"],
            "schema_version": row["schema_version"],
            "aggregate_type": row["aggregate_type"],
            "aggregate_id": row["aggregate_id"],
            "source_revision": row["source_revision"],
            "occurred_at": row["occurred_at"],
            "projection_targets": ["mysql-agent"],
            "payload": row["payload"],
        }
        try:
            async with asyncio.timeout(timeout_seconds):
                outcome = await agent_store.apply_event(event)
        except Exception as error:
            error_class = type(error).__name__
            error_classes.append(error_class)
            await asyncio.to_thread(
                postgres_store.retry_projection_event,
                worker_id,
                row["event_id"],
                error_class=error_class,
                delay_seconds=min(300, 2 ** min(int(row.get("attempts", 1)), 8)),
            )
            retried += 1
            continue
        if outcome == "applied":
            applied += 1
        elif outcome == "duplicate":
            duplicates += 1
        elif outcome == "stale":
            stale += 1
        else:
            error_classes.append("UnexpectedProjectionOutcome")
            await asyncio.to_thread(
                postgres_store.retry_projection_event,
                worker_id,
                row["event_id"],
                error_class="UnexpectedProjectionOutcome",
                delay_seconds=30,
            )
            retried += 1
            continue
        acknowledged = await asyncio.to_thread(
            postgres_store.acknowledge_projection_event,
            worker_id,
            row["event_id"],
        )
        if not acknowledged:
            ack_lost += 1
    return ProjectionBatchResult(
        claimed=len(events), applied=applied, duplicates=duplicates, stale=stale,
        retried=retried, acknowledgement_lost=ack_lost, error_classes=tuple(error_classes),
    )
