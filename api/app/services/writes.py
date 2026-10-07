"""The pieces the two row-writing services share: reading a payload row, and the audit trail.

`app.services.roadmap_tasks` and `app.services.applications` both take a list of rows a caller
computed, apply the fields each one carries, and record what changed in `task_events`. That column
pair — a payload row that may arrive as a schema object or as a plain mapping, and the history table
that has to name whichever row moved — is the same work in both, so it lives here once instead of
being written twice with the two copies free to drift.

Nothing here decides anything about a task or an application: what a row means, which fields a given
caller owns, and when a row is refused stay in the service that understands them. What is here is the
plumbing both of them need to be honest about what they were given and what they did.
"""

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy.orm import Session

from app.models.task import TaskEvent


def row_value(row: Any, name: str, default: Any = None) -> Any:
    """Read one field from a payload row, which may be a schema object or a plain mapping.

    The routers pass schema instances and the service tests pass dicts, and both spell a field the
    same way. A missing key answers with the default rather than raising, and ``carries`` is what
    tells the two apart: the default is for a field the payload never mentions, while a value the
    payload does state — including an explicit ``None`` — is applied as it stands.
    """
    if isinstance(row, Mapping):
        return row.get(name, default)
    return getattr(row, name, default)


def carries(row: Any, name: str) -> bool:
    """True when the payload states this field, as opposed to leaving it to a default.

    The distinction is what makes a replacement a partial update. A payload that omits a date is
    silent about that date, so the row keeps the one it has; sending ``null`` is the claim that the
    row has no date, and that is what clears it. Without the distinction, a caller that computed a
    suggestion date but no deadline would silently wipe a deadline the row held — a loss the caller
    cannot see in its own payload, which is exactly the kind of state change this rule prevents.
    """
    if isinstance(row, Mapping):
        return name in row
    fields_set = getattr(row, "model_fields_set", None)
    if fields_set is not None:
        return name in fields_set
    return hasattr(row, name)


def write_history(
    session: Session,
    client_id: str,
    event: str,
    before: dict | None,
    after: dict | None,
    *,
    actor: str,
    task_id: str | None = None,
    application_id: str | None = None,
) -> None:
    """Append one entry to the audit trail, attributed to whoever made the change.

    Exactly one of ``task_id`` and ``application_id`` names the row the entry describes, and neither
    is a foreign key: the history has to outlive the row it describes, so a removal is recorded with
    the row's values in ``before`` and nothing left to point at.

    ``actor`` is required rather than defaulted, because it is the whole point of the table: a
    recomputation's entries say ``system`` and an applicant's say ``user``, and a default would let a
    new caller inherit an attribution it never chose.
    """
    session.add(
        TaskEvent(
            id=str(uuid.uuid4()),
            client_id=client_id,
            task_id=task_id,
            application_id=application_id,
            actor=actor,
            event=event,
            before=before,
            after=after,
        )
    )
