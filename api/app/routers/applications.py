from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import get_session
from app.deps import get_client_id, load_or_create_profile
from app.models.application import Application, ApplicationTier
from app.models.program import Program
from app.schemas.application import (
    ApplicationOut,
    ApplicationReplaceRequest,
    ApplicationReplaceResult,
    ProgramRef,
)
from app.services.applications import InvalidApplicationPayload, replace_applications

router = APIRouter(prefix="/api/applications", tags=["applications"])

# Where a row whose band is not one of the model's three sorts. The column is a plain string, so a
# value the model never defined can still be stored by a hand edit; giving it an explicit position
# keeps such a row at the end of the list instead of letting an absent-key default of 0 put it first.
UNKNOWN_BAND_ORDER = 1 << 30

# The bands in the order a portfolio is read: the reach, then the match, then the safety.
BAND_ORDER = {tier.value: index for index, tier in enumerate(ApplicationTier)}


@router.get("", response_model=list[ApplicationOut])
def read_applications(
    client_id: Annotated[str, Depends(get_client_id)],
    session: Annotated[Session, Depends(get_session)],
) -> list[ApplicationOut]:
    """Serve the caller's own portfolio, with the program each row names.

    `applications` is per-applicant state, so the response is addressed by the cookie and the route
    resolves the subject for exactly that reason: a first-time visitor has no cookie to present, so
    the response mints one. Reading it still writes nothing — a subject with no rows yet simply has no
    rows, and the `clients` row is created by the first write, not by a read. That is the same split
    `GET /api/roadmap` keeps and the opposite of `GET /api/profile`, which creates the subject it
    answers for.

    The order is the portfolio's own, decided here rather than left to the database: the first choice
    leads, then the bands run 冲 / 稳 / 保, then the program id breaks any tie. Ordering by
    `program_id` alone would be deterministic and meaningless — the frontend renders the list in the
    order it arrives, so the first choice would appear wherever the alphabet put it. A band the model
    never defined is not dropped: it sorts last, which is where a row nobody can place belongs.

    Every row is served with the program it names, projected to what the portfolio lists render. A row
    whose program cannot be read is served with `program: null` rather than dropped or filled in: the
    foreign key makes that state unreachable, so this is a backstop, and a catalogue defect must not
    hide a choice the applicant made. The program's institution is eager-loaded because every row
    needs it and a lazy load per row would turn one query into one per program.

    The deadline fields are served as they are stored, `null` included. A row whose deadline nobody
    has looked up has no deadline, and the response says so rather than substituting a date.
    """
    rows = list(
        session.scalars(select(Application).where(Application.client_id == client_id))
    )
    rows.sort(
        key=lambda row: (
            not row.is_primary,
            BAND_ORDER.get(row.tier, UNKNOWN_BAND_ORDER),
            row.program_id,
        )
    )

    programs = {
        program.id: program
        for program in session.scalars(
            select(Program)
            .options(selectinload(Program.university))
            .where(Program.id.in_([row.program_id for row in rows] or [""]))
        )
    }

    served: list[ApplicationOut] = []
    for row in rows:
        program = programs.get(row.program_id)
        reference = (
            ProgramRef(
                slug=program.id,
                name=program.name,
                name_en=program.name_en,
                university=program.university.name,
                city=program.city,
                degree_level=program.degree_level,
                data_status=program.data_status,
            )
            if program is not None
            else None
        )
        served.append(
            ApplicationOut.model_validate(row).model_copy(update={"program": reference})
        )
    return served


@router.put("", response_model=ApplicationReplaceResult)
def replace_the_applications(
    payload: ApplicationReplaceRequest,
    client_id: Annotated[str, Depends(get_client_id)],
    session: Annotated[Session, Depends(get_session)],
    response: Response,
) -> dict:
    """Replace the caller's portfolio whole: what the payload names is what the subject holds.

    A row the payload names that the subject does not hold is created, a row it restates is moved,
    and a program it no longer names is removed. The whole replacement runs in one transaction inside
    `replace_applications`, so a failure cannot leave half a portfolio behind.

    The subject is created here, in the endpoint body, exactly as `app/routers/roadmap.py` and
    `app/routers/profile.py` do it. `get_client_id` only mints the cookie, and the read above
    deliberately writes nothing, so the subject a read just named has no `clients` row yet: this route
    is the first write to arrive with that cookie, and without this call the insert would violate
    `applications_client_id_fkey`. Calling it here rather than in a dependency keeps the other
    property `deps.py` documents — FastAPI validates the body first, so a request it rejects cannot
    leave a client and profile pair behind.

    The counts come back rather than the rows, because the caller just sent the rows: what it cannot
    compute is how the write landed against what was stored, and the four counts are that — see
    `ApplicationReplaceResult` for what each one means.

    A payload the table or the catalogue cannot accept is a mapped 422 naming what is wrong, never a
    raw 500 from a unique index or a foreign key: the same program twice, more than one first choice,
    or a program id that names nothing. The cookie is repeated on that response on purpose. The
    subject was created before the payload could be checked — the checks are facts about the rows the
    catalogue holds, so they need the session — and a 422 that dropped the cookie would strand the
    rows the way `deps.py` records having stranded 221 of them.
    """
    load_or_create_profile(session, client_id)
    try:
        return replace_applications(session, client_id, payload.rows)
    except InvalidApplicationPayload as exc:
        raise HTTPException(
            status_code=422, detail=str(exc), headers=dict(response.headers)
        ) from exc
