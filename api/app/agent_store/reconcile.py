from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .repository import AgentStore


@dataclass(frozen=True)
class ReconciliationReport:
    checked: int
    missing: int
    stale: int
    ahead: int
    metadata_mismatch: int


async def reconcile_projection(expected: Sequence[dict[str, Any]], agent_store: AgentStore) -> ReconciliationReport:
    missing = stale = ahead = metadata_mismatch = 0
    for record in expected:
        projection = await agent_store.get_projection(str(record["aggregate_id"]))
        if projection is None:
            missing += 1
            continue
        expected_revision = int(record["source_revision"])
        if projection.source_revision < expected_revision:
            stale += 1
            continue
        if projection.source_revision > expected_revision:
            ahead += 1
            continue
        if projection.status != record["status"] or projection.content_hash != record.get("content_hash"):
            metadata_mismatch += 1
    return ReconciliationReport(len(expected), missing, stale, ahead, metadata_mismatch)
