"""The material library at the wire: upload, read, download, and what is deliberately absent.

Three claims are asserted here that the service tests cannot make:

- the routes are addressed by the cookie, and another subject's material is reported as *absent*
  rather than as forbidden — a 403 would confirm that the id exists;
- a download is served as an attachment with the detected type and `nosniff`, because a stored file
  that a browser is willing to render is the risk the type detection exists to close;
- the paths that offer a method also refuse every other one, so "this batch deletes nothing" is a
  behaviour rather than an absence nobody tested.
"""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.deps import COOKIE_NAME
from app.main import app
from app.models.client import Client
from app.models.document import Document, DocumentVersion
from app.services.documents import MAX_UPLOAD_BYTES, MIME_PDF, MIME_PNG
from tests.test_documents_service import A_PNG


def an_upload(name: str = "护照首页.png", data: bytes = A_PNG, content_type: str = MIME_PNG) -> dict:
    return {"file": (name, data, content_type)}


def files_under(root) -> list[str]:
    return sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file())


def test_the_list_starts_empty_and_still_names_the_subject(db_session, require_db):
    """A read writes nothing, but it does name the subject it answered for.

    The same split `GET /api/applications` keeps: the cookie is minted on the way out, while the
    `clients` row is created by the first write. Without the cookie a first-time visitor's upload
    would land under a subject the next request could not name.
    """
    client = TestClient(app)
    response = client.get("/api/documents")

    assert response.status_code == 200
    assert response.json() == []
    assert COOKIE_NAME in client.cookies, "the read must still name the subject it answered for"
    assert db_session.get(Client, client.cookies[COOKIE_NAME]) is None, (
        "a read created the subject it answered for"
    )


def test_an_upload_is_listed_for_its_own_subject_only(db_session, require_db):
    owner = TestClient(app)
    visitor = TestClient(app)

    created = owner.post("/api/documents", files=an_upload())
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["title"] == "护照首页.png"
    assert body["kind"] is None, "a material nobody has classified must not claim a kind"
    assert body["status"] == "uploaded"
    assert body["currentVersion"]["versionNo"] == 1
    assert body["currentVersion"]["mimeType"] == MIME_PNG

    assert len(owner.get("/api/documents").json()) == 1
    assert visitor.get("/api/documents").json() == []


def test_another_subject_cannot_read_the_detail(db_session, require_db):
    owner = TestClient(app)
    visitor = TestClient(app)
    document_id = owner.post("/api/documents", files=an_upload()).json()["id"]

    assert visitor.get(f"/api/documents/{document_id}").status_code == 404
    assert visitor.get(f"/api/documents/{document_id}/reviews").status_code == 404
    assert owner.get(f"/api/documents/{document_id}").status_code == 200


def test_another_subject_cannot_download_the_file(db_session, require_db):
    owner = TestClient(app)
    visitor = TestClient(app)
    document_id = owner.post("/api/documents", files=an_upload()).json()["id"]

    assert visitor.get(f"/api/documents/{document_id}/versions/1/file").status_code == 404


def test_an_upload_naming_a_task_that_does_not_exist_is_refused(db_session, require_db):
    """A `task_id` that names nothing is the caller's mistake, answered with 422 rather than a 500."""
    client = TestClient(app)
    response = client.post(
        "/api/documents", files=an_upload(), data={"task_id": str(uuid.uuid4())}
    )

    assert response.status_code == 422
    assert files_under(settings.document_storage_root) == []


def test_an_upload_with_no_task_is_stored_without_one(db_session, require_db):
    client = TestClient(app)
    body = client.post("/api/documents", files=an_upload()).json()

    assert body["taskId"] is None


def test_the_download_is_an_attachment_of_the_detected_type(db_session, require_db):
    client = TestClient(app)
    document_id = client.post("/api/documents", files=an_upload()).json()["id"]

    response = client.get(f"/api/documents/{document_id}/versions/1/file")

    assert response.status_code == 200
    assert response.content == A_PNG
    assert response.headers["content-type"] == MIME_PNG
    assert response.headers["x-content-type-options"] == "nosniff"
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment")
    # RFC 5987, because the filename is Chinese and a bare `filename="护照首页.png"` is not decodable.
    assert "filename*=utf-8''" in disposition


def test_an_unknown_version_number_is_absent(db_session, require_db):
    client = TestClient(app)
    document_id = client.post("/api/documents", files=an_upload()).json()["id"]

    assert client.get(f"/api/documents/{document_id}/versions/9/file").status_code == 404


def test_a_second_upload_appends_a_version(db_session, require_db):
    client = TestClient(app)
    document_id = client.post("/api/documents", files=an_upload()).json()["id"]

    appended = client.post(
        f"/api/documents/{document_id}/versions",
        files=an_upload("成绩单.pdf", b"%PDF-1.4 scan", MIME_PDF),
    )

    assert appended.status_code == 201, appended.text
    body = appended.json()
    assert body["currentVersion"]["versionNo"] == 2
    assert [version["versionNo"] for version in body["versions"]] == [2, 1]


def test_the_list_carries_only_the_current_version(db_session, require_db):
    """The list is the library view's payload; every version of every material is the detail's job."""
    client = TestClient(app)
    document_id = client.post("/api/documents", files=an_upload()).json()["id"]
    client.post(
        f"/api/documents/{document_id}/versions",
        files=an_upload("成绩单.pdf", b"%PDF-1.4 scan", MIME_PDF),
    )

    listed = client.get("/api/documents").json()[0]
    assert "versions" not in listed
    assert listed["currentVersion"]["versionNo"] == 2


def test_a_document_with_no_reviews_reports_none(db_session, require_db):
    client = TestClient(app)
    document_id = client.post("/api/documents", files=an_upload()).json()["id"]

    assert client.get(f"/api/documents/{document_id}").json()["reviews"] == []
    assert client.get(f"/api/documents/{document_id}/reviews").json() == []


def test_an_oversized_upload_is_refused_over_http(db_session, require_db):
    client = TestClient(app)
    response = client.post(
        "/api/documents",
        files=an_upload("big.pdf", b"\x00" * (MAX_UPLOAD_BYTES + 1), MIME_PDF),
    )

    assert response.status_code == 413
    assert files_under(settings.document_storage_root) == []


def test_a_delete_is_refused(db_session, require_db):
    """This batch removes nothing, and the refusal is a tested behaviour rather than an absence."""
    client = TestClient(app)
    document_id = client.post("/api/documents", files=an_upload()).json()["id"]

    assert client.delete(f"/api/documents/{document_id}").status_code == 405

    with SessionLocal() as check:
        assert check.get(Document, document_id) is not None
        stored = check.execute(
            select(DocumentVersion).where(DocumentVersion.document_id == document_id)
        ).scalars().all()
        assert stored, "the versions went with the refused delete"
    assert client.get(f"/api/documents/{document_id}/versions/1/file").status_code == 200


def test_a_write_to_the_file_route_is_refused(db_session, require_db):
    client = TestClient(app)
    document_id = client.post("/api/documents", files=an_upload()).json()["id"]

    assert client.post(f"/api/documents/{document_id}/versions/1/file").status_code == 405


def test_a_version_row_pointing_outside_the_storage_root_is_refused(db_session, require_db, tmp_path):
    """The one place a stored string becomes a file on disk confines it to the root.

    Every writer builds that path from the file's own digest, so such a row is unreachable through any
    route. This writes one directly, which is what a hand edit or a future migration could do, and
    asserts the download refuses rather than serving whatever the row happens to name.
    """
    client = TestClient(app)
    document_id = client.post("/api/documents", files=an_upload()).json()["id"]

    outside = tmp_path / "outside-the-root.txt"
    outside.write_text("not this applicant's material", encoding="utf-8")
    with SessionLocal() as session:
        version = session.execute(
            select(DocumentVersion).where(DocumentVersion.document_id == document_id)
        ).scalar_one()
        version.storage_path = f"../{outside.name}"
        session.commit()

    response = client.get(f"/api/documents/{document_id}/versions/1/file")

    assert response.status_code == 404
    assert b"not this applicant" not in response.content


def test_a_put_to_the_document_route_is_refused(db_session, require_db):
    """This batch has no way to rewrite a material, and the refusal is tested rather than assumed."""
    client = TestClient(app)
    document_id = client.post("/api/documents", files=an_upload()).json()["id"]

    with SessionLocal() as check:
        before = check.get(Document, document_id).title
    response = client.put(f"/api/documents/{document_id}", json={"title": "改名"})

    assert response.status_code == 405
    with SessionLocal() as check:
        assert check.get(Document, document_id).title == before
