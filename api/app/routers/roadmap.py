from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import get_client_id, load_or_create_profile
from app.models.roadmap import MaterialTemplate, RoadmapPhase
from app.models.source import Source
from app.models.task import RoadmapTask
from app.schemas.roadmap import MaterialOut, PhaseOut, RoadmapDefinition, SourceRef
from app.schemas.task import TaskOut, TaskReplaceRequest, TaskReplaceResult
from app.services.roadmap_tasks import InvalidTaskPayload, replace_system_tasks

router = APIRouter(prefix="/api/roadmap", tags=["roadmap"])

# Where a material whose `phase` names no row in `roadmap_phases` would sort. The foreign key makes
# that unreachable, so this is a backstop rather than a case: the number only has to be larger than
# every real phase order, and it keeps such a material at the end of the list instead of letting it
# ride in at position zero, which is where an absent-key default of 0 would silently put it.
UNKNOWN_PHASE_ORDER = 1 << 30


@router.get("", response_model=RoadmapDefinition)
def read_roadmap(
    client_id: Annotated[str, Depends(get_client_id)],
    session: Annotated[Session, Depends(get_session)],
) -> RoadmapDefinition:
    """Serve the definition plus the caller's own task rows: the whole timeline in one response.

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

    `tasks` is the applicant's own half, and it arrives in the same response so the timeline can be
    rendered without a second round trip. It is not shared configuration the way the other two lists
    are, which is what brings `get_client_id` into this route: the cookie identifies the subject the
    tasks belong to, and the response sets it because that is how a first-time visitor gets a subject
    at all. Reading it here does not write anything — a fresh subject simply has no tasks yet, and
    the row is created by the first write, not by a read.
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

    # The applicant's rows, ordered by `(material_key, program_id)` so the list is deterministic.
    # `phase` would be the natural order for display, but it is redundant with the definition's own
    # phase order and can be stale on a row a human edited, so the stable identity is what this
    # orders by and the consumer places the rows against the definition it already has.
    tasks = list(
        session.execute(
            select(RoadmapTask)
            .where(RoadmapTask.client_id == client_id)
            .order_by(RoadmapTask.material_key, RoadmapTask.program_id)
        ).scalars()
    )

    return RoadmapDefinition(
        phases=[PhaseOut.model_validate(phase) for phase in phases],
        materials=out,
        tasks=[TaskOut.model_validate(task) for task in tasks],
    )


@router.put("/tasks", response_model=TaskReplaceResult)
def replace_tasks(
    payload: TaskReplaceRequest,
    client_id: Annotated[str, Depends(get_client_id)],
    session: Annotated[Session, Depends(get_session)],
    response: Response,
) -> dict:
    """Replace only the rows the client itself generated.

    The caller states which material keys are applicable this round, because "absent from this
    payload" and "no longer applicable" are different claims: treating the first as the second would
    delete the visa tasks whenever the definition was served from the built-in fallback, and the next
    run with the real definition would recreate them as `pending` with the applicant's completed
    marks gone. A key the rows carry and the applicable list does not is a contradiction rather than a
    third claim, and it is refused with a 422 instead of being interpreted — see
    `app.services.roadmap_tasks` for the create-then-delete it used to cause.

    The subject is created here, in the endpoint body, exactly as `app/routers/profile.py` does it.
    `get_client_id` only mints the cookie, so the subject that `GET /api/roadmap` just named has no
    `clients` row yet: that read writes nothing by design. This route is the first write to arrive
    with that cookie, and without this call the insert would violate `roadmap_tasks_client_id_fkey`
    and the applicant's first recompute would answer 500. Calling it here rather than in a dependency
    keeps the other property `deps.py` documents: FastAPI has already validated the body, so a
    rejected request cannot leave a client and profile pair behind.

    The counts come back — `created`, `updated`, `removed`, `kept` — rather than the rows, because the
    caller just computed them: what it cannot compute is what happened to the rows it does not own,
    and `kept` is that number: every existing row this call left exactly as it was. The write commits
    once, inside `replace_system_tasks`.

    A payload the definition cannot satisfy — an unknown material key or phase, or a contradiction
    between its two lists — is a mapped 422 with the reason, never a raw 500 from the foreign key. The
    cookie is repeated on that response on purpose: the subject was created before the payload could
    be checked, so a response that dropped the cookie would strand the rows the way `deps.py` records
    having stranded 221 of them.
    """
    load_or_create_profile(session, client_id)
    try:
        return replace_system_tasks(
            session,
            client_id,
            applicable_keys=payload.applicable_keys,
            rows=payload.rows,
        )
    except InvalidTaskPayload as exc:
        raise HTTPException(
            status_code=422, detail=str(exc), headers=dict(response.headers)
        ) from exc
