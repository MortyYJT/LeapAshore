"""The applicant's own material library, addressed by the anonymous subject cookie.

Every route here resolves the subject the same way the rest of the API does, and every route that
touches a material resolves it *for that subject*: another subject's material is answered as absent
rather than as forbidden, because a 403 distinguishes "not yours" from "does not exist" and that is
one bit of someone else's data this route has no reason to give away.

A read writes nothing. `get_client_id` mints the cookie, and the `clients` row is created by the
first write to arrive with it — the same split `GET /api/applications` keeps, and for the same
reason: `load_or_create_profile` runs after FastAPI has accepted the body, so a request the API
rejects cannot leave a subject behind.

The write routes repeat the cookie on their refusals. The subject may have been created moments
earlier in this same request, and a 4xx that dropped the cookie would strand the rows it owns — this
is the failure `app/deps.py` records having stranded 221 subject and profile pairs with.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import get_client_id, load_or_create_profile
from app.models.document import Document, DocumentVersion
from app.models.review import DocumentReview, DocumentReviewFinding, ReviewCriterion
from app.models.source import Source
from app.schemas.document import (
    CriterionRefOut,
    DocumentDetailOut,
    DocumentSummaryOut,
    FindingOut,
    ReviewOut,
    VersionOut,
)
from app.schemas.roadmap import SourceRef
from app.services.documents import UploadRejected, add_version, storage_root, store_upload

router = APIRouter(prefix="/api/documents", tags=["documents"])

NO_SUCH_DOCUMENT = "找不到这份材料。"
NO_SUCH_VERSION = "找不到这个版本。"
FILE_MISSING = "这份材料的文件缺失，请联系支持。"


def _own_document(session: Session, client_id: str, document_id: str) -> Document:
    """The caller's own material, or a 404. Never another subject's, and never a 403.

    A 403 would tell the caller that the id exists and belongs to someone else, which is a fact about
    another subject's library that this route has no reason to disclose.
    """
    document = session.execute(
        select(Document).where(Document.id == document_id, Document.client_id == client_id)
    ).scalar_one_or_none()
    if document is None:
        raise HTTPException(status_code=404, detail=NO_SUCH_DOCUMENT)
    return document


def _versions(session: Session, document_id: str) -> list[DocumentVersion]:
    """Every version of one material, newest first."""
    return list(
        session.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version_no.desc())
        )
    )


def _reviews(session: Session, document_id: str) -> list[ReviewOut]:
    """The material's reviews with each finding's criterion and that criterion's source.

    Three queries rather than one per row: the reviews, the criteria they cite, and those criteria's
    sources. A finding that could not name a criterion is impossible by constraint, but this still
    tolerates one rather than raising — a catalogue defect must not hide a review the applicant is
    entitled to read, which is the same call `GET /api/applications` makes for a missing program.
    """
    reviews = list(
        session.scalars(
            select(DocumentReview)
            .where(DocumentReview.document_id == document_id)
            .order_by(DocumentReview.created_at.desc(), DocumentReview.id)
        )
    )
    if not reviews:
        return []

    findings = list(
        session.scalars(
            select(DocumentReviewFinding).where(
                DocumentReviewFinding.review_id.in_([review.id for review in reviews])
            )
        )
    )
    criteria = {
        criterion.id: criterion
        for criterion in session.scalars(
            select(ReviewCriterion).where(
                ReviewCriterion.id.in_([finding.criterion_id for finding in findings] or [""])
            )
        )
    }
    sources = {
        source.id: source
        for source in session.scalars(
            select(Source).where(Source.id.in_([row.source_id for row in criteria.values()] or [""]))
        )
    }

    by_review: dict[str, list[FindingOut]] = {review.id: [] for review in reviews}
    for finding in findings:
        criterion = criteria.get(finding.criterion_id)
        if criterion is None:
            continue
        source = sources.get(criterion.source_id)
        by_review[finding.review_id].append(
            FindingOut(
                id=finding.id,
                severity=finding.severity,
                finding=finding.finding,
                evidence_quote=finding.evidence_quote,
                criterion=CriterionRefOut(
                    code=criterion.code,
                    scope=criterion.scope,
                    title=criterion.title,
                    description=criterion.description,
                    source=SourceRef(
                        url=source.url if source is not None else "",
                        title=source.title if source is not None else "",
                        status=source.status if source is not None else "",
                    ),
                ),
            )
        )

    return [
        ReviewOut(
            id=review.id,
            version_id=review.version_id,
            overall=review.overall,
            summary=review.summary,
            reviewed_by=review.reviewed_by,
            created_at=review.created_at,
            findings=by_review[review.id],
        )
        for review in reviews
    ]


def _summary(document: Document, current: DocumentVersion | None) -> DocumentSummaryOut:
    return DocumentSummaryOut(
        id=document.id,
        title=document.title,
        kind=document.kind,
        status=document.status,
        task_id=document.task_id,
        program_id=document.program_id,
        archived_by=document.archived_by,
        archived_at=document.archived_at,
        created_at=document.created_at,
        updated_at=document.updated_at,
        current_version=VersionOut.model_validate(current) if current is not None else None,
    )


def _detail(session: Session, document: Document) -> DocumentDetailOut:
    current = (
        session.get(DocumentVersion, document.current_version_id)
        if document.current_version_id is not None
        else None
    )
    summary = _summary(document, current)
    return DocumentDetailOut(
        **summary.model_dump(),
        versions=[VersionOut.model_validate(row) for row in _versions(session, document.id)],
        reviews=_reviews(session, document.id),
    )


def _refusal(exc: UploadRejected, response: Response) -> HTTPException:
    """A refusal from the upload service, as an HTTP error that keeps the subject's cookie."""
    return HTTPException(
        status_code=exc.status_code,
        detail=exc.detail,
        headers={"set-cookie": response.headers["set-cookie"]},
    )


@router.get("", response_model=list[DocumentSummaryOut])
def read_documents(
    client_id: Annotated[str, Depends(get_client_id)],
    session: Annotated[Session, Depends(get_session)],
) -> list[DocumentSummaryOut]:
    """The caller's own materials, newest first.

    Reading does not create the subject, and it does not create a material: an applicant who has
    uploaded nothing has an empty list, which is a different statement from a list that failed to
    load and is rendered differently for that reason.
    """
    documents = list(
        session.scalars(
            select(Document)
            .where(Document.client_id == client_id)
            .order_by(Document.created_at.desc(), Document.id)
        )
    )
    current = {
        version.id: version
        for version in session.scalars(
            select(DocumentVersion).where(
                DocumentVersion.id.in_(
                    [row.current_version_id for row in documents if row.current_version_id] or [""]
                )
            )
        )
    }
    return [_summary(document, current.get(document.current_version_id)) for document in documents]


@router.get("/{document_id}", response_model=DocumentDetailOut)
def read_document(
    document_id: str,
    client_id: Annotated[str, Depends(get_client_id)],
    session: Annotated[Session, Depends(get_session)],
) -> DocumentDetailOut:
    """One material with its version list and its reviews."""
    return _detail(session, _own_document(session, client_id, document_id))


@router.get("/{document_id}/reviews", response_model=list[ReviewOut])
def read_reviews(
    document_id: str,
    client_id: Annotated[str, Depends(get_client_id)],
    session: Annotated[Session, Depends(get_session)],
) -> list[ReviewOut]:
    """Just the reviews of one material. Read-only: reviews are recorded by an operator command."""
    document = _own_document(session, client_id, document_id)
    return _reviews(session, document.id)


@router.post("", response_model=DocumentDetailOut, status_code=201)
def upload_document(
    file: Annotated[UploadFile, File()],
    client_id: Annotated[str, Depends(get_client_id)],
    session: Annotated[Session, Depends(get_session)],
    response: Response,
    title: Annotated[str | None, Form()] = None,
    task_id: Annotated[str | None, Form()] = None,
) -> DocumentDetailOut:
    """Create a material and its first version from one multipart upload.

    The form fields are named here rather than left to the client: `file` for the bytes, `title` and
    `task_id` for the two things a caller may state. FastAPI cannot take a JSON body on a route that
    also parses a form, so there is no second spelling of this request.
    """
    load_or_create_profile(session, client_id)
    try:
        document = store_upload(session, client_id, file, title=title, task_id=task_id)
    except UploadRejected as exc:
        raise _refusal(exc, response) from exc
    return _detail(session, document)


@router.post("/{document_id}/versions", response_model=DocumentDetailOut, status_code=201)
def upload_version(
    document_id: str,
    file: Annotated[UploadFile, File()],
    client_id: Annotated[str, Depends(get_client_id)],
    session: Annotated[Session, Depends(get_session)],
    response: Response,
) -> DocumentDetailOut:
    """Append a version to one of the caller's materials and make it the current one."""
    document = _own_document(session, client_id, document_id)
    try:
        add_version(session, document, file)
    except UploadRejected as exc:
        raise _refusal(exc, response) from exc
    return _detail(session, document)


@router.get("/{document_id}/versions/{version_no}/file")
def download_version(
    document_id: str,
    version_no: int,
    client_id: Annotated[str, Depends(get_client_id)],
    session: Annotated[Session, Depends(get_session)],
) -> FileResponse:
    """Serve the stored bytes to the owning subject as an attachment.

    `nosniff` and the attachment disposition are both load-bearing: the detected type is on the row
    precisely so a file cannot be interpreted as a page on this origin, and a browser that is willing
    to render an upload is the risk that detection exists to close.

    A version whose row exists but whose file does not is reported as missing rather than as a 500.
    The foreign key and the write order make that state unreachable, so reaching it means something
    outside this code removed a file, and saying so is more useful than a stack trace.
    """
    document = _own_document(session, client_id, document_id)
    version = session.execute(
        select(DocumentVersion).where(
            DocumentVersion.document_id == document.id, DocumentVersion.version_no == version_no
        )
    ).scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=404, detail=NO_SUCH_VERSION)

    path = storage_root() / version.storage_path
    if not path.is_file():
        raise HTTPException(status_code=404, detail=FILE_MISSING)

    return FileResponse(
        path,
        media_type=version.mime_type,
        filename=version.filename,
        headers={"X-Content-Type-Options": "nosniff"},
    )
