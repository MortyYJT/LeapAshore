"""The material library as the interface reads it.

Two shapes, deliberately different sizes. `DocumentSummaryOut` is the list view's payload and
carries only the current version, because the library renders one row per material and every version
of every material would be most of the response for none of the screen. `DocumentDetailOut` is what
opening one material reads: the whole version list, newest first, and the reviews with the criteria
and official pages they cite.

`kind` and `archived_at` stay `null` when nobody has established them. An empty string would be a
classification someone made, and `other` would be a decision nobody took.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.common import _camel
from app.schemas.roadmap import SourceRef


class VersionOut(BaseModel):
    """One uploaded file. Everything except the path, which never leaves the server."""

    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True, from_attributes=True)

    id: str
    version_no: int
    filename: str
    mime_type: str
    byte_size: int
    sha256: str
    created_at: datetime


class CriterionRefOut(BaseModel):
    """The requirement a finding failed, with the page that requirement was read from."""

    code: str
    scope: str
    title: str
    description: str
    source: SourceRef


class FindingOut(BaseModel):
    """One concrete thing to fix, and what it fails against."""

    id: str
    severity: str
    finding: str
    evidence_quote: str | None = None
    criterion: CriterionRefOut


class ReviewOut(BaseModel):
    """One human verdict on one version, with its findings."""

    id: str
    version_id: str
    overall: str
    summary: str | None = None
    reviewed_by: str
    created_at: datetime
    findings: list[FindingOut]


class DocumentSummaryOut(BaseModel):
    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True)

    id: str
    title: str
    kind: str | None = None
    status: str
    task_id: str | None = None
    program_id: str | None = None
    archived_by: str | None = None
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    current_version: VersionOut | None = None


class DocumentDetailOut(DocumentSummaryOut):
    """The summary plus everything that only matters once a material is open."""

    versions: list[VersionOut] = []
    reviews: list[ReviewOut] = []


class ArchiveRequest(BaseModel):
    """The classification the applicant is asserting.

    Required, with no default: `kind` drives which criteria can ever apply to this material, and a
    default would be the system deciding what someone else's file is.
    """

    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True)

    kind: str
