"""The constraints this batch exists for, pinned at the database rather than in a service.

Each test inserts the row the rule forbids and asserts the database refuses it. A later migration
that relaxed a constraint fails here instead of quietly restoring the hole. The rules themselves are
the specs in `openspec/changes/stage-2-m3-document-library/specs/`; what these tests pin is that the
database, and not only a service, is what enforces them.

Every row these tests write is either swept by the autouse client sweep or removed by the test's own
`finally`, because the development database is the one they run against.
"""

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.models.client import Client
from app.models.document import Document, DocumentVersion
from app.models.review import (
    CheckType,
    CriterionScope,
    DocumentReview,
    DocumentReviewFinding,
    FindingSeverity,
    ReviewCriterion,
    ReviewOverall,
)
from app.models.roadmap import MaterialTemplate, RoadmapPhase
from app.models.source import Source
from app.models.task import RoadmapTask


def new_id() -> str:
    return str(uuid.uuid4())


def a_source(session) -> Source:
    """An official page, unique per call so a leftover row cannot collide with the next run."""
    source = Source(id=new_id(), url=f"https://example.edu.au/{uuid.uuid4()}", title="测试来源")
    session.add(source)
    session.commit()
    return source


def a_criterion(session, source, **overrides) -> ReviewCriterion:
    values = {
        "id": new_id(),
        "code": f"test-{uuid.uuid4().hex[:8]}",
        "scope": CriterionScope.GENERAL,
        "title": "测试要点",
        "description": "只用于测试",
        "check_type": CheckType.PRESENCE,
        "source_id": source.id,
    }
    values.update(overrides)
    criterion = ReviewCriterion(**values)
    session.add(criterion)
    session.commit()
    return criterion


def a_client(session) -> Client:
    client = Client(id=new_id())
    session.add(client)
    session.commit()
    return client


def a_document(session, client, **overrides) -> Document:
    values = {"id": new_id(), "client_id": client.id, "title": "本科成绩单"}
    values.update(overrides)
    document = Document(**values)
    session.add(document)
    session.commit()
    return document


def a_version(session, document, version_no=1) -> DocumentVersion:
    digest = uuid.uuid4().hex * 2
    version = DocumentVersion(
        id=new_id(),
        document_id=document.id,
        version_no=version_no,
        filename="成绩单.pdf",
        mime_type="application/pdf",
        byte_size=12,
        sha256=digest,
        storage_path=f"blobs/{digest[:2]}/{digest}",
    )
    session.add(version)
    session.commit()
    return version


def an_uncommitted_finding(session, review, criterion=None) -> DocumentReviewFinding:
    return DocumentReviewFinding(
        id=new_id(),
        review_id=review.id,
        criterion_id=criterion.id if criterion is not None else None,
        severity=FindingSeverity.WARNING,
        finding="成绩单缺少教务处盖章",
    )


def discard(session, *rows) -> None:
    """Delete what a test wrote, in the order the foreign keys require.

    Called from `finally`, so a failing assertion cannot leave a criterion behind for the next run.
    """
    session.rollback()
    for model, key in rows:
        row = session.get(model, key)
        if row is not None:
            session.delete(row)
            session.flush()
    session.commit()


def test_a_criterion_without_a_source_is_refused(db_session, require_db):
    """A requirement with no official page behind it must not be storable at all.

    `source_id` is NOT NULL in the schema, so this fails if a later migration makes it nullable and
    lets a service default it.
    """
    db_session.add(
        ReviewCriterion(
            id=new_id(),
            code=f"test-{uuid.uuid4().hex[:8]}",
            scope=CriterionScope.GENERAL,
            title="没有来源的要点",
            description="只用于测试",
            check_type=CheckType.PRESENCE,
            source_id=None,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_a_criterion_cannot_cite_a_source_that_does_not_exist(db_session, require_db):
    db_session.add(
        ReviewCriterion(
            id=new_id(),
            code=f"test-{uuid.uuid4().hex[:8]}",
            scope=CriterionScope.GENERAL,
            title="指向不存在的来源",
            description="只用于测试",
            check_type=CheckType.PRESENCE,
            source_id=new_id(),
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_a_scope_outside_the_set_is_refused(db_session, require_db):
    """`passport` is a document kind, not a criterion scope, and the database says so."""
    source = a_source(db_session)
    try:
        db_session.add(
            ReviewCriterion(
                id=new_id(),
                code=f"test-{uuid.uuid4().hex[:8]}",
                scope="passport",
                title="越界的范围",
                description="只用于测试",
                check_type=CheckType.PRESENCE,
                source_id=source.id,
            )
        )
        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()
    finally:
        discard(db_session, (Source, source.id))


def test_a_check_type_outside_the_set_is_refused(db_session, require_db):
    source = a_source(db_session)
    try:
        db_session.add(
            ReviewCriterion(
                id=new_id(),
                code=f"test-{uuid.uuid4().hex[:8]}",
                scope=CriterionScope.GENERAL,
                title="越界的检查方式",
                description="只用于测试",
                check_type="vibes",
                source_id=source.id,
            )
        )
        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()
    finally:
        discard(db_session, (Source, source.id))


def test_a_finding_without_a_criterion_is_refused(db_session, require_db):
    """The whole product promise: a conclusion that cannot name its basis is not storable."""
    client = a_client(db_session)
    document = a_document(db_session, client)
    version = a_version(db_session, document)
    review = DocumentReview(
        id=new_id(),
        document_id=document.id,
        version_id=version.id,
        overall=ReviewOverall.NEEDS_REVISION,
        reviewed_by="审查者",
    )
    db_session.add(review)
    db_session.commit()

    db_session.add(an_uncommitted_finding(db_session, review, criterion=None))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_a_finding_severity_outside_the_set_is_refused(db_session, require_db):
    source = a_source(db_session)
    criterion = a_criterion(db_session, source)
    client = a_client(db_session)
    document = a_document(db_session, client)
    version = a_version(db_session, document)
    review = DocumentReview(
        id=new_id(),
        document_id=document.id,
        version_id=version.id,
        overall=ReviewOverall.NEEDS_REVISION,
        reviewed_by="审查者",
    )
    db_session.add(review)
    db_session.commit()
    try:
        finding = an_uncommitted_finding(db_session, review, criterion)
        finding.severity = "fatal"
        db_session.add(finding)
        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()
    finally:
        discard(db_session, (ReviewCriterion, criterion.id), (Source, source.id))


def test_a_version_number_is_unique_within_a_document(db_session, require_db):
    client = a_client(db_session)
    document = a_document(db_session, client)
    a_version(db_session, document, version_no=1)

    digest = uuid.uuid4().hex * 2
    db_session.add(
        DocumentVersion(
            id=new_id(),
            document_id=document.id,
            version_no=1,
            filename="again.pdf",
            mime_type="application/pdf",
            byte_size=3,
            sha256=digest,
            storage_path=f"blobs/{digest[:2]}/{digest}",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_a_document_kind_outside_the_set_is_refused(db_session, require_db):
    """A kind the archive route could never produce must not be storable by any other route.

    Built here rather than through `a_document`, which commits: the violation has to surface inside
    the `pytest.raises` block for the test to be about the constraint.
    """
    client = a_client(db_session)
    db_session.add(Document(id=new_id(), client_id=client.id, title="本科成绩单", kind="diploma"))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_a_cited_source_cannot_be_deleted(db_session, require_db):
    """The criterion outlives any attempt to remove the page it was read from."""
    source = a_source(db_session)
    criterion = a_criterion(db_session, source)
    try:
        with SessionLocal() as remove:
            with pytest.raises(IntegrityError):
                remove.delete(remove.get(Source, source.id))
                remove.commit()
            remove.rollback()

        with SessionLocal() as check:
            assert check.get(Source, source.id) is not None
            assert check.get(ReviewCriterion, criterion.id) is not None
    finally:
        discard(db_session, (ReviewCriterion, criterion.id), (Source, source.id))


def test_a_cited_criterion_cannot_be_deleted(db_session, require_db):
    source = a_source(db_session)
    criterion = a_criterion(db_session, source)
    client = a_client(db_session)
    document = a_document(db_session, client)
    version = a_version(db_session, document)
    review = DocumentReview(
        id=new_id(),
        document_id=document.id,
        version_id=version.id,
        overall=ReviewOverall.NEEDS_REVISION,
        reviewed_by="审查者",
    )
    db_session.add(review)
    db_session.commit()
    finding = an_uncommitted_finding(db_session, review, criterion)
    db_session.add(finding)
    db_session.commit()

    try:
        with SessionLocal() as remove:
            with pytest.raises(IntegrityError):
                remove.delete(remove.get(ReviewCriterion, criterion.id))
                remove.commit()
            remove.rollback()

        with SessionLocal() as check:
            assert check.get(ReviewCriterion, criterion.id) is not None
            assert check.get(DocumentReviewFinding, finding.id) is not None
    finally:
        discard(
            db_session,
            (DocumentReviewFinding, finding.id),
            (DocumentReview, review.id),
            (ReviewCriterion, criterion.id),
            (Source, source.id),
        )


def test_deleting_a_client_takes_its_materials_with_it(db_session, require_db):
    """The client sweep in `conftest` deletes `clients` and relies on the database cascade.

    Versions, reviews and findings hang off the material, so this also proves that nothing in the
    chain refuses the delete or tries to null a NOT NULL foreign key on the way down.
    """
    client = a_client(db_session)
    document = a_document(db_session, client)
    version = a_version(db_session, document)
    review = DocumentReview(
        id=new_id(),
        document_id=document.id,
        version_id=version.id,
        overall=ReviewOverall.PASS,
        reviewed_by="审查者",
    )
    db_session.add(review)
    db_session.commit()

    document_id, version_id, review_id = document.id, version.id, review.id
    with SessionLocal() as remove:
        remove.delete(remove.get(Client, client.id))
        remove.commit()

    with SessionLocal() as check:
        assert check.get(Document, document_id) is None
        assert check.get(DocumentVersion, version_id) is None
        assert check.get(DocumentReview, review_id) is None


def test_deleting_a_task_leaves_the_document_without_one(db_session, require_db):
    """A recomputation deletes the applicant's system task rows; the material has to survive it.

    `documents.task_id` is SET NULL for this reason. A RESTRICT there would let one linked material
    abort the whole recomputation with a foreign key error.
    """
    phase_key = f"test-phase-{uuid.uuid4().hex[:8]}"
    material_key = f"test-material-{uuid.uuid4().hex[:8]}"
    client = a_client(db_session)
    db_session.add(RoadmapPhase(key=phase_key, title="测试阶段", offset_days=30, sort_order=0))
    db_session.flush()
    db_session.add(
        MaterialTemplate(
            key=material_key, phase=phase_key, title="测试材料", applies_to="all", sort_order=0
        )
    )
    db_session.commit()

    task = RoadmapTask(
        id=new_id(), client_id=client.id, material_key=material_key, program_id="", phase=phase_key
    )
    db_session.add(task)
    db_session.commit()

    document = a_document(db_session, client, task_id=task.id)
    document_id = document.id

    try:
        with SessionLocal() as remove:
            remove.delete(remove.get(RoadmapTask, task.id))
            remove.commit()

        with SessionLocal() as check:
            stored = check.get(Document, document_id)
            assert stored is not None, "the material went with the task it was prepared for"
            assert stored.task_id is None
    finally:
        discard(db_session, (MaterialTemplate, material_key), (RoadmapPhase, phase_key))
