"""A review criterion as the interface reads it.

`rule` is `null` when only a person can judge the criterion, and the source travels with the
criterion because a requirement whose page cannot be shown is one the reader has no way to check.
`verified_at` is served as `null` until a human sets it; the interface shows the difference between
"someone checked this page" and "nobody has yet", which is the same distinction `SourceRef` carries
for a program's or a material's citation.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.common import _camel
from app.schemas.roadmap import SourceRef


class ReviewCriterionOut(BaseModel):
    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True, from_attributes=True)

    id: str
    code: str
    scope: str
    title: str
    description: str
    check_type: str
    rule: dict | None = None
    status: str
    verified_at: datetime | None = None
    source: SourceRef
