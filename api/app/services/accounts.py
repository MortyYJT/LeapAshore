"""What happens to a data subject when an account claims it, merges it or deletes it.

`openspec/changes/archive/2026-10-30-account-login/design.md` D7 (merge rules) and D9 (deletion). The functions here
change rows but never commit, except `delete_subject`, which has to commit before it may remove files.
"""

import logging
from collections.abc import Iterable

from sqlalchemy import delete, exists, select, update
from sqlalchemy.orm import Session

from app.models.account import Account, LoginCode
from app.models.application import Application
from app.models.client import Client, Profile
from app.models.document import Document, DocumentVersion
from app.models.task import RoadmapTask, TaskEvent
from app.services import knowledge_gaps
from app.services.conversations import delete_conversations, move_conversations
from app.services.documents import storage_root

logger = logging.getLogger(__name__)

# The columns that hold the applicant's answers; the key and the timestamps are bookkeeping.
PROFILE_FIELDS = tuple(
    column.key
    for column in Profile.__table__.columns
    if column.key not in ("client_id", "created_at", "updated_at")
)


def profile_is_empty(profile: Profile | None) -> bool:
    """True when no answer field holds a value (an empty string counts as unanswered)."""
    if profile is None:
        return True
    for name in PROFILE_FIELDS:
        value = getattr(profile, name)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return False
    return True


def is_claimable(session: Session, client_id: str | None) -> bool:
    """An anonymous subject exists and no account owns it. Call with the client row locked."""
    if not client_id or session.get(Client, client_id) is None:
        return False
    return not session.scalar(select(exists().where(Account.client_id == client_id)))


def lock_client(session: Session, client_id: str | None) -> None:
    """Hold the subject's row until the transaction ends, so it is claimed or merged only once."""
    if client_id:
        session.execute(select(Client.id).where(Client.id == client_id).with_for_update())


def new_subject(session: Session, client_id: str) -> None:
    session.add(Client(id=client_id))
    session.flush()
    session.add(Profile(client_id=client_id))
    session.flush()


def merge_subject(session: Session, source_id: str, target_id: str) -> dict[str, int]:
    """Move the anonymous subject `source_id` into `target_id`; the target's rows always win.

    - profile: a unit. Copied only when the target's profile has no answer at all.
    - applications: rows for programs the target lacks move; the target's first choice is kept.
    - roadmap tasks: rows the target lacks move; a duplicate's materials are re-pointed first.
    - documents (with versions and reviews) and task events always move.
    - advisor conversations move, except a conversation id the target already has
      (openspec advisor-persistence D7).
    The source client is deleted at the end, and the cascade drops what was not moved.
    """
    if source_id == target_id:
        return {}
    counts = {"profile": 0, "applications": 0, "tasks": 0, "documents": 0, "events": 0, "conversations": 0,
              "gap_reports": 0}

    source_profile = session.get(Profile, source_id)
    target_profile = session.get(Profile, target_id)
    if target_profile is None:
        target_profile = Profile(client_id=target_id)
        session.add(target_profile)
    if not profile_is_empty(source_profile) and profile_is_empty(target_profile):
        for name in PROFILE_FIELDS:
            setattr(target_profile, name, getattr(source_profile, name))
        counts["profile"] = 1
    session.flush()

    held = set(session.scalars(select(Application.program_id).where(Application.client_id == target_id)))
    has_primary = bool(
        session.scalar(
            select(exists().where(Application.client_id == target_id, Application.is_primary.is_(True)))
        )
    )
    for row in session.scalars(select(Application).where(Application.client_id == source_id)).all():
        if row.program_id in held:
            continue
        if row.is_primary and has_primary:
            row.is_primary = False
        has_primary = has_primary or row.is_primary
        row.client_id = target_id
        held.add(row.program_id)
        counts["applications"] += 1
        # One row at a time: the partial unique index allows one first choice per subject.
        session.flush()

    target_tasks = {
        (t.material_key, t.program_id): t.id
        for t in session.scalars(select(RoadmapTask).where(RoadmapTask.client_id == target_id))
    }
    replaced: dict[str, str] = {}
    for task in session.scalars(select(RoadmapTask).where(RoadmapTask.client_id == source_id)).all():
        key = (task.material_key, task.program_id)
        if key in target_tasks:
            replaced[task.id] = target_tasks[key]
        else:
            task.client_id = target_id
            counts["tasks"] += 1
    session.flush()

    for document in session.scalars(select(Document).where(Document.client_id == source_id)).all():
        document.client_id = target_id
        if document.task_id in replaced:
            document.task_id = replaced[document.task_id]
        counts["documents"] += 1
    session.flush()

    counts["events"] = session.execute(
        update(TaskEvent).where(TaskEvent.client_id == source_id).values(client_id=target_id)
    ).rowcount
    counts["conversations"] = move_conversations(session, source_id, target_id)["moved"]
    # Knowledge-gap reports follow the subject, so deleting the account later deletes them too.
    counts["gap_reports"] = knowledge_gaps.rekey_reports(session, source_id, target_id)
    session.execute(delete(Client).where(Client.id == source_id))
    session.flush()
    session.expire_all()
    return counts


def _unlink_orphans(session: Session, paths: Iterable[str]) -> int:
    """Remove each blob no remaining version references. Runs after the deleting commit."""
    candidates = set(paths)
    if not candidates:
        return 0
    still_used = set(
        session.scalars(
            select(DocumentVersion.storage_path).where(DocumentVersion.storage_path.in_(candidates)).distinct()
        )
    )
    root = storage_root()
    removed = 0
    for relpath in candidates - still_used:
        target = (root / relpath).resolve()
        # A stored path is always relative to the root; anything else is not ours to remove.
        if not target.is_relative_to(root.resolve()):
            continue
        try:
            target.unlink()
            removed += 1
        except FileNotFoundError:
            pass
    return removed


def delete_subject(session: Session, client_id: str) -> dict[str, int]:
    """Delete a subject with everything it owns, its account, sessions and login codes, and its files.

    One `DELETE FROM clients`: the foreign keys cascade to the profile, applications, roadmap tasks,
    task events, documents (and versions, reviews, findings), the account and its sessions. Login
    codes are keyed by email, so they are deleted by the account's email, and the advisor's
    conversations by their thread prefix, in the same transaction (openspec advisor-persistence D7). Files are content-addressed
    and may be shared with another subject's identical upload, so a blob is removed only when no
    remaining version references it, and only after the rows are committed.
    """
    paths = list(
        session.scalars(
            select(DocumentVersion.storage_path)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(Document.client_id == client_id)
        )
    )
    emails = list(session.scalars(select(Account.email).where(Account.client_id == client_id)))
    session.execute(delete(Client).where(Client.id == client_id))
    if emails:
        session.execute(delete(LoginCode).where(LoginCode.email.in_(emails)))
    conversations = delete_conversations(session, client_id)
    # The subject's knowledge-gap reports (questions and their hash) go with it; the gaps stay.
    gap_reports = knowledge_gaps.delete_reports_of(session, client_id)
    session.commit()
    removed = _unlink_orphans(session, paths)
    return {"files_removed": removed, "accounts": len(emails), "conversations": conversations,
            "gap_reports": gap_reports}
