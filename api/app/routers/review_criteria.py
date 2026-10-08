"""The review criteria, read-only.

These are shared configuration rather than anyone's data, so the route resolves no subject cookie: two
callers get the same list, and an applicant who has never written anything can still read what a
review would check.

There is deliberately no write route. This repository has no login and no role, so an HTTP write here
would let any visitor mark a requirement as verified — the one field the product promises a human sets.
The operator command in `review_cli.py` is the only writer, and `GET` is the only method declared
here, which is what makes every other method answer 405 without a route to forget.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models.review import ReviewCriterion
from app.models.source import Source
from app.schemas.review_criterion import ReviewCriterionOut
from app.schemas.roadmap import SourceRef

router = APIRouter(prefix="/api/review-criteria", tags=["review-criteria"])


@router.get("", response_model=list[ReviewCriterionOut])
def read_review_criteria(
    session: Annotated[Session, Depends(get_session)],
) -> list[ReviewCriterionOut]:
    """Every criterion with the page it was read from, in code order.

    The order is a stable one rather than the seed's insertion order, because the interface groups by
    scope and a list that reordered itself between requests would make a criterion look like it had
    moved. The source is joined in one query rather than one per criterion; a criterion whose source
    row has gone is unreachable by the foreign key, so an absent source leaves the citation fields
    empty rather than raising — the same call `GET /api/applications` makes for a missing program.
    """
    criteria = list(
        session.scalars(select(ReviewCriterion).order_by(ReviewCriterion.code))
    )
    sources = {
        source.id: source
        for source in session.scalars(
            select(Source).where(Source.id.in_([row.source_id for row in criteria] or [""]))
        )
    }

    served: list[ReviewCriterionOut] = []
    for criterion in criteria:
        source = sources.get(criterion.source_id)
        served.append(
            ReviewCriterionOut(
                id=criterion.id,
                code=criterion.code,
                scope=criterion.scope,
                title=criterion.title,
                description=criterion.description,
                check_type=criterion.check_type,
                rule=criterion.rule,
                status=criterion.status,
                verified_at=criterion.verified_at,
                source=SourceRef(
                    url=source.url if source is not None else "",
                    title=source.title if source is not None else "",
                    status=source.status if source is not None else "",
                ),
            )
        )
    return served
