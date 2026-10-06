from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models.roadmap import MaterialTemplate, RoadmapPhase
from app.models.source import Source
from app.schemas.roadmap import MaterialOut, PhaseOut, RoadmapDefinition, SourceRef

router = APIRouter(prefix="/api/roadmap", tags=["roadmap"])

# Where a material whose `phase` names no row in `roadmap_phases` would sort. The foreign key makes
# that unreachable, so this is a backstop rather than a case: the number only has to be larger than
# every real phase order, and it keeps such a material at the end of the list instead of letting it
# ride in at position zero, which is where an absent-key default of 0 would silently put it.
UNKNOWN_PHASE_ORDER = 1 << 30


@router.get("", response_model=RoadmapDefinition)
def read_roadmap(session: Annotated[Session, Depends(get_session)]) -> RoadmapDefinition:
    """Serve the whole timeline definition: the phases and every material under them.

    The order is the timeline, not the alphabet. `sort_order` runs from the earliest suggested date
    to the latest — selection at 330 days before intake down to the visa at 30 — so a consumer
    rendering the lists in place shows the stages in the sequence the applicant works through.
    Ordering by `key` would open on `academic` and close on `visa` and look just as plausible,
    which is why the ordering is stated rather than left to the database's default.

    Materials are ordered by their phase's position and then by their own `sort_order`, so they
    arrive grouped in timeline order with each phase's requirements in the sequence the frontend
    renders today.

    Each material's source is read from the row its `source_id` names, and a material with no
    `source_id` serves `source: null`. That is the honest answer for the six transcribed phases:
    they are placeholder copy with no official page behind them, and manufacturing a citation would
    be worse than reporting none. `source_id` is `NULL` for all of them, so the extra lookup only
    runs for the two visa materials that have one.

    Tasks land in the same response in the next batch. They are per-applicant and will need the
    subject cookie this route deliberately does not have: the definition is shared configuration,
    identical for every caller, so reading or minting a cookie here would hand a visitor a subject
    they never asked for and imply the timeline is theirs. Nothing in this function touches the
    client dependency for that reason.
    """
    # The phase order is decided here, in one place: `key` is only a tiebreak, so two phases that
    # ever shared an order would still come back deterministically.
    phases = list(
        session.execute(
            select(RoadmapPhase).order_by(RoadmapPhase.sort_order, RoadmapPhase.key)
        ).scalars()
    )
    # Every material, ordered in Python rather than in SQL, because the sort key is the *phase's*
    # position while a material's own `sort_order` only counts within its phase: `selection`'s first
    # and `decision`'s first both carry 0. Sorting in Python means no inner join is needed, and so
    # no material can be dropped for naming a phase that does not exist; the foreign key makes that
    # unreachable, but a query that silently loses a requirement is the wrong failure mode for it.
    materials = list(session.execute(select(MaterialTemplate)).scalars())
    order = {phase.key: phase.sort_order for phase in phases}
    materials.sort(
        key=lambda material: (
            order.get(material.phase, UNKNOWN_PHASE_ORDER),
            material.sort_order,
            material.key,
        )
    )

    out: list[MaterialOut] = []
    for material in materials:
        source = session.get(Source, material.source_id) if material.source_id else None
        out.append(
            MaterialOut(
                key=material.key,
                phase=material.phase,
                title=material.title,
                detail=material.detail,
                applies_to=material.applies_to,
                sort_order=material.sort_order,
                source=(
                    SourceRef(url=source.url, title=source.title, status=source.status)
                    if source
                    else None
                ),
            )
        )

    return RoadmapDefinition(
        phases=[PhaseOut.model_validate(phase) for phase in phases], materials=out
    )
