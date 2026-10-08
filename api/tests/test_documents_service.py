"""The upload rules, checked at the service rather than through HTTP.

Two of these are security rules rather than conveniences: the stored type is detected from the bytes
rather than taken from the caller, and the size limit is enforced while the file is copied. Both are
the kind that a later refactor can quietly undo, so they are pinned here.
"""

import base64
import io
import threading
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select
from starlette.datastructures import Headers, UploadFile

from app.config import settings
from app.db import SessionLocal
from app.models.client import Client
from app.models.document import Document, DocumentStatus, DocumentVersion
from app.models.roadmap import MaterialTemplate, RoadmapPhase
from app.models.task import RoadmapTask
from app.services.documents import (
    MAX_UPLOAD_BYTES,
    MIME_DOCX,
    MIME_PDF,
    MIME_PNG,
    Refused,
    add_version,
    store_upload,
)

# A real 1x1 PNG. The service detects a type by its signature, so a file that is only a signature
# with a `.png` name would test the same branch while proving less about a real upload.
A_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def an_upload(data: bytes, filename: str, content_type: str = "application/octet-stream") -> UploadFile:
    return UploadFile(
        file=io.BytesIO(data),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


def a_word_document() -> bytes:
    """The smallest archive that is a Word document as far as the container check is concerned."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<w:document/>")
    return buffer.getvalue()


def a_zip_that_is_not_a_word_document() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("hello.txt", "not a word document")
    return buffer.getvalue()


def a_client(session) -> Client:
    client = Client(id=str(uuid.uuid4()))
    session.add(client)
    session.commit()
    return client


def files_under(root) -> list[str]:
    return sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file())


@pytest.fixture
def upload_root():
    """The temporary storage root `conftest` already redirected every test to.

    Named here rather than created here so the redirect is one autouse fixture instead of one per
    module: a module that forgot it would write into the developer's own upload directory.
    """
    return settings.document_storage_root


def test_an_oversized_upload_is_refused_and_leaves_nothing(db_session, require_db, upload_root):
    client = a_client(db_session)
    oversized = an_upload(b"\x00" * (MAX_UPLOAD_BYTES + 1), "big.pdf", MIME_PDF)

    with pytest.raises(Refused) as rejected:
        store_upload(db_session, client.id, oversized)

    assert rejected.value.status_code == 413
    assert files_under(upload_root) == []
    assert db_session.query(Document).filter(Document.client_id == client.id).count() == 0


def test_an_empty_upload_is_refused(db_session, require_db, upload_root):
    client = a_client(db_session)
    with pytest.raises(Refused) as rejected:
        store_upload(db_session, client.id, an_upload(b"", "empty.pdf", MIME_PDF))

    assert rejected.value.status_code == 422
    assert files_under(upload_root) == []


def test_a_text_file_claiming_to_be_a_pdf_is_refused(db_session, require_db, upload_root):
    """The declared type is the caller's claim, and this is why the claim is not believed.

    A stored file is served back to a browser later. If the declared type were the stored one, this
    upload would arrive as `<html>` and be rendered as a page on this origin.
    """
    client = a_client(db_session)
    with pytest.raises(Refused) as rejected:
        store_upload(
            db_session,
            client.id,
            an_upload(b"<html><script>alert(1)</script></html>", "transcript.pdf", MIME_PDF),
        )

    assert rejected.value.status_code == 415
    assert files_under(upload_root) == []


def test_a_zip_that_is_not_a_word_document_is_refused(db_session, require_db, upload_root):
    """A ZIP signature only proves the file is an archive, so the container is opened and asked."""
    client = a_client(db_session)
    with pytest.raises(Refused) as rejected:
        store_upload(
            db_session,
            client.id,
            an_upload(a_zip_that_is_not_a_word_document(), "cv.docx", MIME_DOCX),
        )

    assert rejected.value.status_code == 415
    assert files_under(upload_root) == []


def test_a_word_document_is_accepted(db_session, require_db, upload_root):
    client = a_client(db_session)
    document = store_upload(
        db_session, client.id, an_upload(a_word_document(), "cv.docx", "application/octet-stream")
    )

    version = db_session.get(DocumentVersion, document.current_version_id)
    assert version.mime_type == MIME_DOCX


def test_the_stored_type_is_the_detected_one(db_session, require_db, upload_root):
    client = a_client(db_session)
    document = store_upload(
        db_session, client.id, an_upload(A_PNG, "passport.png", "application/octet-stream")
    )

    version = db_session.get(DocumentVersion, document.current_version_id)
    assert version.mime_type == MIME_PNG


def test_a_title_defaults_to_the_uploaded_filename(db_session, require_db, upload_root):
    client = a_client(db_session)
    document = store_upload(db_session, client.id, an_upload(A_PNG, "护照首页.png"))

    assert document.title == "护照首页.png"


def test_a_given_title_is_kept(db_session, require_db, upload_root):
    client = a_client(db_session)
    document = store_upload(db_session, client.id, an_upload(A_PNG, "a.png"), title="护照首页")

    assert document.title == "护照首页"


def test_the_stored_path_is_relative_and_the_file_is_there(db_session, require_db, upload_root):
    client = a_client(db_session)
    document = store_upload(db_session, client.id, an_upload(A_PNG, "a.png"))

    version = db_session.get(DocumentVersion, document.current_version_id)
    assert not version.storage_path.startswith("/")
    assert (upload_root / version.storage_path).is_file()
    assert (upload_root / version.storage_path).read_bytes() == A_PNG


def test_the_same_bytes_are_stored_once(db_session, require_db, upload_root):
    """Content addressing, across documents: the same bytes are one file, not two."""
    client = a_client(db_session)
    first = store_upload(db_session, client.id, an_upload(A_PNG, "one.png"))
    second = store_upload(db_session, client.id, an_upload(A_PNG, "two.png"))

    one = db_session.get(DocumentVersion, first.current_version_id)
    two = db_session.get(DocumentVersion, second.current_version_id)
    assert one.sha256 == two.sha256
    assert one.storage_path == two.storage_path
    assert files_under(upload_root) == [one.storage_path]


def test_a_second_upload_appends_a_version(db_session, require_db, upload_root):
    client = a_client(db_session)
    document = store_upload(db_session, client.id, an_upload(A_PNG, "one.png"))

    version = add_version(db_session, document, an_upload(b"%PDF-1.4 scan", "two.pdf", MIME_PDF))

    assert version.version_no == 2
    assert version.document_id == document.id
    fresh = db_session.get(Document, document.id)
    assert fresh.current_version_id == version.id
    assert len(files_under(upload_root)) == 2


def test_a_new_version_keeps_the_classification_and_resets_the_status(
    db_session, require_db, upload_root
):
    client = a_client(db_session)
    document = store_upload(db_session, client.id, an_upload(A_PNG, "one.png"))
    document.kind = "transcript"
    document.status = DocumentStatus.ACCEPTED
    db_session.commit()

    add_version(db_session, document, an_upload(b"%PDF-1.4 scan", "two.pdf", MIME_PDF))

    fresh = db_session.get(Document, document.id)
    assert fresh.kind == "transcript"
    assert fresh.status == DocumentStatus.UPLOADED


def test_a_task_that_belongs_to_another_subject_is_refused(db_session, require_db, upload_root):
    owner = a_client(db_session)
    visitor = a_client(db_session)
    phase_key = f"test-phase-{uuid.uuid4().hex[:8]}"
    material_key = f"test-material-{uuid.uuid4().hex[:8]}"
    db_session.add(RoadmapPhase(key=phase_key, title="测试阶段", offset_days=1, sort_order=0))
    db_session.flush()
    db_session.add(
        MaterialTemplate(
            key=material_key, phase=phase_key, title="测试材料", applies_to="all", sort_order=0
        )
    )
    db_session.commit()
    task = RoadmapTask(
        id=str(uuid.uuid4()),
        client_id=owner.id,
        material_key=material_key,
        program_id="",
        phase=phase_key,
    )
    db_session.add(task)
    db_session.commit()

    try:
        with pytest.raises(Refused) as rejected:
            store_upload(db_session, visitor.id, an_upload(A_PNG, "a.png"), task_id=task.id)
        assert rejected.value.status_code == 422
        assert files_under(upload_root) == []

        with pytest.raises(Refused):
            store_upload(db_session, visitor.id, an_upload(A_PNG, "a.png"), task_id=str(uuid.uuid4()))
        assert files_under(upload_root) == []
    finally:
        # The task first: `roadmap_tasks.material_key` is RESTRICT, so the material cannot go while
        # a task still names it.
        with SessionLocal() as cleanup:
            task_row = cleanup.get(RoadmapTask, task.id)
            if task_row is not None:
                cleanup.delete(task_row)
                cleanup.flush()
            for model, key in ((MaterialTemplate, material_key), (RoadmapPhase, phase_key)):
                row = cleanup.get(model, key)
                if row is not None:
                    cleanup.delete(row)
                    cleanup.flush()
            cleanup.commit()


def test_an_upload_with_no_task_is_stored_without_one(db_session, require_db, upload_root):
    client = a_client(db_session)
    document = store_upload(db_session, client.id, an_upload(A_PNG, "a.png"))

    assert document.task_id is None


def test_the_uploaded_bytes_are_not_left_in_a_staging_file(db_session, require_db, upload_root):
    """Everything under the root after a successful upload is the blob itself."""
    client = a_client(db_session)
    document = store_upload(db_session, client.id, an_upload(A_PNG, "a.png"))

    version = db_session.get(DocumentVersion, document.current_version_id)
    assert files_under(upload_root) == [version.storage_path]


# Long enough that a slow machine still reaches the overlap, short enough that a thread which never
# does fails the test instead of hanging the suite.
PATIENCE_SECONDS = 10


def test_two_uploads_racing_for_the_next_version_number(db_session, require_db, upload_root):
    """Both uploads are stored, and the numbers stay exactly 1, 2, 3.

    This is the spec's own scenario: two uploads for one material reach for the same next number. The
    loser must not become a 500, and it must not become a 409 either — the number is chosen under a lock
    on the material, so the second upload waits and then reads what the first committed. Removing that
    lock while the retry reuses the number it chose (rather than recomputing one, which is what could
    skip a number) turns the loser into a refusal and this test red.
    """
    client = a_client(db_session)
    document = store_upload(db_session, client.id, an_upload(A_PNG, "one.png"))
    document_id = document.id
    both_arrived = threading.Barrier(2)

    def append(payload: bytes, name: str) -> int:
        with SessionLocal() as session:
            current = session.get(Document, document_id)
            both_arrived.wait(timeout=PATIENCE_SECONDS)
            return add_version(
                session, current, an_upload(payload, name, MIME_PDF)
            ).version_no

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(append, b"%PDF-1.4 second", "two.pdf"),
            pool.submit(append, b"%PDF-1.4 third", "three.pdf"),
        ]
        numbers = sorted(future.result() for future in futures)

    assert numbers == [2, 3], "the two racing uploads did not take the next two numbers"
    with SessionLocal() as session:
        stored = sorted(
            session.scalars(
                select(DocumentVersion.version_no).where(
                    DocumentVersion.document_id == document_id
                )
            )
        )
    assert stored == [1, 2, 3], "a version number was skipped"


def test_a_truncated_blob_is_repaired_rather_than_reused(db_session, require_db, upload_root):
    """The path is the digest, so what is at the path has to be those bytes.

    A blob left truncated — a full disk on some older write, or something outside this code — would
    otherwise be reused by every later upload of that content, while the row went on recording a digest
    and a byte size the file does not have.
    """
    client = a_client(db_session)
    first = store_upload(db_session, client.id, an_upload(A_PNG, "one.png"))
    version = db_session.get(DocumentVersion, first.current_version_id)
    blob = upload_root / version.storage_path
    blob.write_bytes(b"")

    again = store_upload(db_session, client.id, an_upload(A_PNG, "two.png"))

    stored = db_session.get(DocumentVersion, again.current_version_id)
    assert stored.storage_path == version.storage_path, "the two uploads stopped sharing one blob"
    assert blob.read_bytes() == A_PNG, "a truncated blob was reused instead of repaired"
    assert blob.stat().st_size == stored.byte_size
