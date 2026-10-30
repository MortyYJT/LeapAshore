"""Merge university rows that are one school.

    python -m app.collect.merge_schools                        # list the rows that share a name
    python -m app.collect.merge_schools [--apply] KEEP DUP ...  # move DUP's rows onto KEEP, then delete DUP

Without `--apply` the merge runs and is rolled back: the report says what would move. With it, the merge
is one transaction.

What points at a university row moves to the kept one: its programs (`programs.university_id`), the
official pages cut for the advisor (`snapshot_pages.university_id`) and the pages an import cited under
it (`sources.publisher`). The kept row takes the duplicate's website and city only where it has none.
A duplicate is deleted only once nothing points at it, because both foreign keys cascade: deleting a
row that still had programs would delete them.

Nothing an applicant wrote is touched: portfolios (`applications`), roadmap tasks and materials name
programs, and a program keeps its id when it moves.
"""

import json
import sys

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.program import Program, University
from app.models.snapshot import SnapshotPage
from app.models.source import Source


def duplicate_groups(session: Session) -> list[dict]:
    """Rows that share an English name (case-insensitive) or a Chinese name, with what points at each."""
    rows = session.scalars(select(University).order_by(University.id)).all()
    programs = dict(session.execute(select(Program.university_id, func.count()).group_by(Program.university_id)).all())
    pages = dict(session.execute(select(SnapshotPage.university_id, func.count())
                                 .group_by(SnapshotPage.university_id)).all())
    groups: dict[tuple[str, str], list[University]] = {}
    for row in rows:
        if row.name_en:
            groups.setdefault(("name_en", row.name_en.strip().lower()), []).append(row)
        groups.setdefault(("name", row.name.strip()), []).append(row)
    out, seen = [], set()
    for (_, _), members in groups.items():
        ids = tuple(sorted(r.id for r in members))
        if len(members) < 2 or ids in seen:
            continue
        seen.add(ids)
        out.append({"name": members[0].name, "name_en": members[0].name_en, "rows": [
            {"id": r.id, "name_en": r.name_en, "official_url": r.official_url,
             "programs": programs.get(r.id, 0), "snapshot_pages": pages.get(r.id, 0)} for r in members]})
    return out


def merge(session: Session, keep: str, duplicates: list[str]) -> dict:
    """Move everything that points at `duplicates` onto `keep` and delete them. Does not commit."""
    if not duplicates:
        raise ValueError("nothing to merge")
    if keep in duplicates:
        raise ValueError(f"cannot merge {keep} into itself")
    wanted = [keep, *duplicates]
    # FOR UPDATE: an import that writes a program under one of these rows while this runs waits.
    found = {row.id: row for row in session.scalars(
        select(University).where(University.id.in_(wanted)).order_by(University.id).with_for_update())}
    missing = [uid for uid in wanted if uid not in found]
    if missing:
        raise ValueError(f"no university {', '.join(missing)}")
    # Programs an import wrote (ids without `cricos-`) belong to one requirement file, and
    # `importer --prune` deletes a school's programs its file does not list: two rows that each hold
    # such programs are two files' schools, and one row for both would let a prune delete the other's.
    imported = {uid for uid in wanted if session.scalar(select(func.count()).select_from(Program).where(
        Program.university_id == uid, Program.id.not_like("cricos-%")))}
    if len(imported) > 1:
        raise ValueError(f"{', '.join(sorted(imported))} each hold imported programs; not merged")
    kept = found[keep]
    report = {"keep": keep, "merged": list(duplicates), "programs_moved": 0, "snapshot_pages_moved": 0,
              "sources_repointed": 0}
    for dup in duplicates:
        row = found[dup]
        for column in ("official_url", "city", "name_en"):
            if getattr(kept, column) is None and getattr(row, column) is not None:
                setattr(kept, column, getattr(row, column))
        report["programs_moved"] += session.execute(
            update(Program).where(Program.university_id == dup).values(university_id=keep)).rowcount
        report["snapshot_pages_moved"] += session.execute(
            update(SnapshotPage).where(SnapshotPage.university_id == dup).values(university_id=keep)).rowcount
        report["sources_repointed"] += session.execute(
            update(Source).where(Source.publisher == dup).values(publisher=keep)).rowcount
    session.flush()
    for table, column in ((Program, Program.university_id), (SnapshotPage, SnapshotPage.university_id)):
        left = session.scalar(select(func.count()).select_from(table).where(column.in_(duplicates)))
        if left:
            raise RuntimeError(f"{left} {table.__tablename__} rows still point at {duplicates}; nothing deleted")
    for dup in duplicates:
        session.delete(found[dup])
    session.flush()
    return report


def main(argv: list[str] | None = None) -> int:
    from app.db import SessionLocal

    argv = list(sys.argv[1:] if argv is None else argv)
    apply = "--apply" in argv
    ids = [a for a in argv if a != "--apply"]
    with SessionLocal() as session:
        if not ids:
            print(json.dumps(duplicate_groups(session), ensure_ascii=False, indent=1))
            return 0
        try:
            report = merge(session, ids[0], ids[1:])
        except ValueError as error:
            session.rollback()
            print(json.dumps({"error": str(error)}, ensure_ascii=False))
            return 2
        if apply:
            session.commit()
        else:
            session.rollback()
        print(json.dumps({**report, "applied": apply}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
