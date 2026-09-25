from datetime import UTC, datetime
from hashlib import sha256
from typing import Any


def advisor_thread_changed_event(user_ref: str, thread_id: str, revision: int, message_count: int) -> dict[str, Any]:
    event_id = sha256(f"advisor.thread.changed\0{thread_id}\0{revision}".encode()).hexdigest()
    owner_ref = sha256(f"owner\0{user_ref}".encode()).hexdigest()
    return {
        "event_id": event_id,
        "event_type": "advisor.thread.changed",
        "schema_version": 1,
        "aggregate_type": "advisor_thread",
        "aggregate_id": thread_id,
        "source_revision": revision,
        "occurred_at": datetime.now(UTC),
        "projection_targets": ["mysql-agent"],
        "payload": {
            "owner_ref": owner_ref,
            "source_ref": thread_id,
            "status": "active",
            "message_count": message_count,
        },
    }
