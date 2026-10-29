"""Remove schools that left the school library's scope from the catalogue.

    python -m app.collect.remove_schools [--apply] <university_id> ...

Without `--apply` it only reports what it would remove (the transaction is rolled back). With it, the
removal is one transaction, and running it again changes nothing.

For each university it removes the programs (with their prerequisites), then every page those programs
or earlier imports for that school cited (`sources.publisher` is the university id), unless something
else still cites the page. The university row goes once it has no programs left.

Nothing an applicant wrote is lost: a program that a portfolio row (`applications.program_id`) or a
material (`documents.program_id`) names is kept as it is, with its university and the page it cites,
and listed under `kept_programs`. Deleting it would either be refused (applications) or silently
unlink the applicant's material (documents is SET NULL), so it is reported for a person to decide.
"""

import json
import sys

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.document import Document
from app.models.program import Program, ProgramPrerequisite, University
from app.models.review import ReviewCriterion
from app.models.roadmap import MaterialTemplate
from app.models.source import Source, SourceVersion


def _cited_elsewhere(session: Session, source_ids: set[str]) -> set[str]:
    """The sources in `source_ids` that a program, a material template or a criterion still cites."""
    if not source_ids:
        return set()
    cited: set[str] = set()
    for column in (Program.source_id, MaterialTemplate.source_id, ReviewCriterion.source_id):
        cited |= set(session.scalars(select(column).where(column.in_(source_ids))))
    return cited


def remove_university(session: Session, university_id: str) -> dict:
    programs = set(session.scalars(select(Program.id).where(Program.university_id == university_id)))
    held: set[str] = set()
    if programs:
        held |= set(session.scalars(select(Application.program_id).where(Application.program_id.in_(programs))))
        held |= set(session.scalars(select(Document.program_id).where(Document.program_id.in_(programs))))
    removable = programs - held

    candidates: set[str] = set(session.scalars(select(Source.id).where(Source.publisher == university_id)))
    if removable:
        candidates |= set(session.scalars(select(Program.source_id).where(Program.id.in_(removable))))
        session.execute(delete(ProgramPrerequisite).where(ProgramPrerequisite.program_id.in_(removable)))
        session.execute(delete(Program).where(Program.id.in_(removable)))
        session.flush()

    sources = candidates - _cited_elsewhere(session, candidates)
    if sources:
        session.execute(delete(SourceVersion).where(SourceVersion.source_id.in_(sources)))
        session.execute(delete(Source).where(Source.id.in_(sources)))

    university_removed = False
    if not held and session.get(University, university_id) is not None:
        session.execute(delete(University).where(University.id == university_id))
        university_removed = True
    session.flush()
    return {
        "university": university_id,
        "programs_removed": len(removable),
        "sources_removed": len(sources),
        "kept_programs": sorted(held),
        "university_removed": university_removed,
    }


def remove_universities(session: Session, university_ids: list[str]) -> list[dict]:
    """Remove each university as above. The caller commits or rolls back."""
    return [remove_university(session, uid) for uid in university_ids]


def main(argv: list[str]) -> int:
    from app.db import SessionLocal

    apply = "--apply" in argv
    ids = [a for a in argv if a != "--apply"]
    if not ids:
        print(__doc__, file=sys.stderr)
        return 2
    with SessionLocal() as session:
        report = remove_universities(session, ids)
        if apply:
            session.commit()
        else:
            session.rollback()
    for row in report:
        print(json.dumps({**row, "applied": apply}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
