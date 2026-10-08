"""Archiving and the review lifecycle: which moves are allowed, and which are refused.

The lifecycle is a small state machine and the refusals are the point of it. Two of them are not
obvious and both exist to stop a document from meaning two things at once:

- a material cannot be sent for review until it has been classified, because the criteria that apply
  are chosen by its kind and the system must not guess which ones a file was meant to satisfy;
- a material cannot be re-archived while a review is running, because that review cites the criteria
  for its kind and reclassifying mid-review moves the ground under it.

Written over the wire rather than against the service: the transitions are what a caller observes,
and a rule that only holds when the service is called directly is not a rule the product has.
"""

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models.document import Document, DocumentStatus
from app.main import app
from app.services.documents import MIME_PDF, MIME_PNG
from tests.test_documents_service import A_PNG

def an_upload(name: str = "护照首页.png", data: bytes = A_PNG, content_type: str = MIME_PNG) -> dict:
    return {"file": (name, data, content_type)}


def a_material(client: TestClient) -> str:
    return client.post("/api/documents", files=an_upload()).json()["id"]


def store(document_id: str, **columns) -> Document:
    """Write one column pair straight to the row.

    Some of the lifecycle's starting points are produced by the operator command, which this batch
    does not have yet, so the test sets the row up directly rather than going through a path that
    does not exist. What is being tested is the transition, not how the state was reached.
    """
    with SessionLocal() as session:
        document = session.get(Document, document_id)
        for name, value in columns.items():
            setattr(document, name, value)
        session.commit()
        session.refresh(document)
        return document


def test_archiving_records_the_classification(db_session, require_db):
    client = TestClient(app)
    document_id = a_material(client)

    response = client.post(f"/api/documents/{document_id}/archive", json={"kind": "transcript"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "transcript"
    assert body["status"] == "archived"
    assert body["archivedBy"] == "user"
    assert body["archivedAt"] is not None


def test_archiving_without_a_kind_is_refused(db_session, require_db):
    """A classification nobody stated must not be filled in by a default."""
    client = TestClient(app)
    document_id = a_material(client)

    response = client.post(f"/api/documents/{document_id}/archive", json={})

    assert response.status_code == 422
    assert client.get(f"/api/documents/{document_id}").json()["kind"] is None


def test_an_unknown_kind_is_refused(db_session, require_db):
    client = TestClient(app)
    document_id = a_material(client)

    response = client.post(f"/api/documents/{document_id}/archive", json={"kind": "diploma"})

    assert response.status_code == 422
    body = client.get(f"/api/documents/{document_id}").json()
    assert body["kind"] is None
    assert body["status"] == "uploaded"


def test_submitting_an_unclassified_material_is_refused(db_session, require_db):
    """The criteria are chosen by kind, so a material with no kind cannot be reviewed at all."""
    client = TestClient(app)
    document_id = a_material(client)

    response = client.post(f"/api/documents/{document_id}/submit")

    assert response.status_code == 409
    assert client.get(f"/api/documents/{document_id}").json()["status"] == "uploaded"


def test_submitting_an_archived_material_moves_it_under_review(db_session, require_db):
    client = TestClient(app)
    document_id = a_material(client)
    client.post(f"/api/documents/{document_id}/archive", json={"kind": "transcript"})

    response = client.post(f"/api/documents/{document_id}/submit")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "under_review"


def test_a_material_needing_revision_can_be_resubmitted(db_session, require_db):
    client = TestClient(app)
    document_id = a_material(client)
    client.post(f"/api/documents/{document_id}/archive", json={"kind": "transcript"})
    store(document_id, status=DocumentStatus.NEEDS_REVISION)

    response = client.post(f"/api/documents/{document_id}/submit")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "under_review"


def test_an_accepted_material_cannot_be_resubmitted_unchanged(db_session, require_db):
    """A verdict describes bytes; revising the request without revising the file means nothing."""
    client = TestClient(app)
    document_id = a_material(client)
    client.post(f"/api/documents/{document_id}/archive", json={"kind": "transcript"})
    store(document_id, status=DocumentStatus.ACCEPTED)

    response = client.post(f"/api/documents/{document_id}/submit")

    assert response.status_code == 409
    assert client.get(f"/api/documents/{document_id}").json()["status"] == "accepted"


def test_archiving_while_under_review_is_refused_even_without_changing_the_kind(
    db_session, require_db
):
    """The refusal is about the moment, not about the value: re-stating the same kind would still
    re-stamp `archived_at` and let a classification change in a second call."""
    client = TestClient(app)
    document_id = a_material(client)
    store(document_id, kind="transcript", status=DocumentStatus.UNDER_REVIEW)

    response = client.post(f"/api/documents/{document_id}/archive", json={"kind": "transcript"})

    assert response.status_code == 409
    assert client.get(f"/api/documents/{document_id}").json()["status"] == "under_review"


def test_a_new_version_returns_the_material_to_uploaded_and_keeps_the_classification(
    db_session, require_db
):
    client = TestClient(app)
    document_id = a_material(client)
    client.post(f"/api/documents/{document_id}/archive", json={"kind": "transcript"})
    store(document_id, status=DocumentStatus.ACCEPTED)
    archived_before = client.get(f"/api/documents/{document_id}").json()["archivedAt"]

    appended = client.post(
        f"/api/documents/{document_id}/versions",
        files=an_upload("成绩单.pdf", b"%PDF-1.4 revised", MIME_PDF),
    )

    assert appended.status_code == 201, appended.text
    body = appended.json()
    assert body["status"] == "uploaded"
    assert body["kind"] == "transcript", "the new file did not unclassify the material"
    assert body["archivedAt"] == archived_before, "the classification time was re-stamped"
    assert body["currentVersion"]["versionNo"] == 2


def test_another_subject_cannot_archive_someone_elses_material(db_session, require_db):
    owner = TestClient(app)
    visitor = TestClient(app)
    document_id = a_material(owner)

    response = visitor.post(f"/api/documents/{document_id}/archive", json={"kind": "transcript"})

    assert response.status_code == 404
    assert owner.get(f"/api/documents/{document_id}").json()["kind"] is None


def test_another_subject_cannot_submit_someone_elses_material(db_session, require_db):
    owner = TestClient(app)
    visitor = TestClient(app)
    document_id = a_material(owner)
    owner.post(f"/api/documents/{document_id}/archive", json={"kind": "transcript"})

    assert visitor.post(f"/api/documents/{document_id}/submit").status_code == 404
    assert owner.get(f"/api/documents/{document_id}").json()["status"] == "archived"


def test_a_put_to_the_archive_route_is_refused(db_session, require_db):
    client = TestClient(app)
    document_id = a_material(client)

    assert client.put(f"/api/documents/{document_id}/archive", json={"kind": "cv"}).status_code == 405
