"""The rules a recorded review has to satisfy, and the operator command that records one.

There is no HTTP way to write a review in this batch, and that is the point: this repository has no
login and no role, so a route here would let any visitor record a verdict on anyone's material and
mark a requirement as verified. The command in `review_cli.py` runs on the machine that holds the
database, which is the only place with any authority to say a page was checked.

Every rule below refuses rather than stores, because a review is a claim about someone's application
and a stored one that contradicts itself is worse than a refusal the operator can act on:

- a review names the version it judged, and only the current version may be judged — a revision that
  arrived while the operator was reading means the verdict describes bytes that are no longer there;
- every finding cites a criterion, and that criterion has to apply to this kind of material, so a
  conclusion about a CV can never be justified by a requirement read for a Genuine Student statement;
- a passing verdict cannot carry a blocker, and a failing one has to name something to fix.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document import Document, DocumentStatus, DocumentVersion
from app.models.review import (
    OVERALL_VALUES,
    SEVERITY_VALUES,
    CriterionScope,
    CriterionStatus,
    DocumentReview,
    DocumentReviewFinding,
    ReviewCriterion,
    ReviewOverall,
)
from app.services.refusals import Refused

NO_SUCH_DOCUMENT = "找不到这份材料。"
NO_SUCH_VERSION = "找不到这个版本。"
SUPERSEDED_VERSION = "这份材料的当前版本已经变了，请重新审阅最新版本。"
NOT_UNDER_REVIEW = "这份材料不在送审状态，不能写入审核结论。"
EMPTY_REVIEWER = "审核结论必须写明是谁审的。"
UNKNOWN_OVERALL = "审核结论只能是 pass、needs_revision 或 insufficient_evidence。"
UNKNOWN_CRITERION = "找不到这条审核要点：{code}"
UNKNOWN_SEVERITY = "建议的严重程度只能是 info、warning 或 blocker。"
CRITERION_OUT_OF_SCOPE = "要点 {code} 的范围是 {scope}，不能用在 {kind} 这类材料上。"
PASS_WITH_BLOCKER = "结论是 pass 时不能有 blocker 级别的建议。"
FAILURE_WITHOUT_FINDINGS = "结论不是 pass 时至少要写一条具体建议。"

# The overall verdicts that decide a material's state, and the ones that leave it alone.
SETTLED_BY_OVERALL = {
    ReviewOverall.PASS: DocumentStatus.ACCEPTED,
    ReviewOverall.NEEDS_REVISION: DocumentStatus.NEEDS_REVISION,
}


def verify_criterion(session: Session, code: str, *, verified: bool) -> ReviewCriterion:
    """Mark a criterion as checked by a person, or take that back.

    The only writer of `verified_at` anywhere in this repository. It stamps the moment it runs rather
    than any written-out date, which is what `scripts/check-no-fake-dates.cjs` exists to enforce and
    what the schema's missing default is for: a record may only claim verification when a human sets
    the date, and a seeded or defaulted date would make every requirement look checked.
    """
    criterion = session.execute(
        select(ReviewCriterion).where(ReviewCriterion.code == code)
    ).scalar_one_or_none()
    if criterion is None:
        raise Refused(404, UNKNOWN_CRITERION.format(code=code))

    if verified:
        criterion.status = CriterionStatus.VERIFIED
        criterion.verified_at = datetime.now(UTC)
    else:
        criterion.status = CriterionStatus.UNVERIFIED
        criterion.verified_at = None
    session.commit()
    return criterion


def _resolve_findings(
    session: Session, document: Document, findings: list[dict]
) -> list[DocumentReviewFinding]:
    """Turn the operator's findings into rows, refusing any that cannot be justified.

    Resolved before anything is written so a refusal leaves no half-review behind, and checked against
    the material's own kind so a finding can only cite a requirement that applies to it.
    """
    resolved: list[DocumentReviewFinding] = []
    for entry in findings:
        severity = entry["severity"]
        if severity not in SEVERITY_VALUES:
            raise Refused(422, UNKNOWN_SEVERITY)

        criterion = session.execute(
            select(ReviewCriterion).where(ReviewCriterion.code == entry["code"])
        ).scalar_one_or_none()
        if criterion is None:
            raise Refused(422, UNKNOWN_CRITERION.format(code=entry["code"]))

        # `general` applies to anything; every other scope names the kind of material it is about, and
        # the two vocabularies are deliberately the same strings. Without this, "this CV does not
        # answer the Genuine Student questions" would be a storable conclusion.
        if criterion.scope != CriterionScope.GENERAL and criterion.scope != document.kind:
            raise Refused(
                422,
                CRITERION_OUT_OF_SCOPE.format(
                    code=criterion.code, scope=criterion.scope, kind=document.kind
                ),
            )

        resolved.append(
            DocumentReviewFinding(
                id=str(uuid.uuid4()),
                severity=severity,
                criterion_id=criterion.id,
                finding=entry["finding"],
                evidence_quote=entry.get("evidence_quote"),
            )
        )
    return resolved


def record_review(
    session: Session,
    document_id: str,
    *,
    version_no: int,
    overall: str,
    reviewed_by: str,
    summary: str | None = None,
    findings: list[dict] | None = None,
) -> DocumentReview:
    """Record one verdict on one version of one material, and move the material accordingly.

    `version_no` is named by the caller rather than taken from the document, because the rule this
    command exists to enforce is that the verdict describes the bytes the operator actually read. Asking
    for the current version silently would defeat it: a revision arriving mid-review would have the
    verdict attach itself to a file nobody looked at, and nothing in the row would say so.
    """
    overall_value = overall
    if overall_value not in OVERALL_VALUES:
        raise Refused(422, UNKNOWN_OVERALL)
    if not reviewed_by or not reviewed_by.strip():
        raise Refused(422, EMPTY_REVIEWER)

    document = session.get(Document, document_id)
    if document is None:
        raise Refused(404, NO_SUCH_DOCUMENT)
    if document.status != DocumentStatus.UNDER_REVIEW:
        raise Refused(409, NOT_UNDER_REVIEW)

    version = session.execute(
        select(DocumentVersion).where(
            DocumentVersion.document_id == document.id, DocumentVersion.version_no == version_no
        )
    ).scalar_one_or_none()
    if version is None:
        raise Refused(404, NO_SUCH_VERSION)
    if document.current_version_id != version.id:
        raise Refused(409, SUPERSEDED_VERSION)

    supplied = findings or []
    if overall_value == ReviewOverall.PASS and any(
        entry["severity"] == "blocker" for entry in supplied
    ):
        raise Refused(422, PASS_WITH_BLOCKER)
    if overall_value != ReviewOverall.PASS and not supplied:
        raise Refused(422, FAILURE_WITHOUT_FINDINGS)

    review = DocumentReview(
        id=str(uuid.uuid4()),
        document_id=document.id,
        version_id=version.id,
        overall=overall_value,
        summary=summary,
        reviewed_by=reviewed_by,
    )
    session.add(review)
    # The review row has to exist before a finding may name it, the same ordering the version pointer
    # needs, and for the same reason: no ORM relationship declares the dependency.
    session.flush()

    for finding in _resolve_findings(session, document, supplied):
        finding.review_id = review.id
        session.add(finding)

    settled = SETTLED_BY_OVERALL.get(ReviewOverall(overall_value))
    if settled is not None:
        document.status = settled
    # `insufficient_evidence` is deliberately absent from the table above: the review reached no
    # conclusion, so the material is still waiting for one rather than moved to a state that would
    # claim the question was answered.

    session.commit()
    return review
