"""Uploading a material: turning one request into one immutable version.

Three rules shape this module, and each exists because of a concrete failure it prevents.

**The bytes are written before the row is.** A version row that points at a file which is not there
would be a permanent, silent defect: the applicant would see their material listed and get an error
every time they opened it. The reverse — a file with no row — is an orphan that a later upload of the
same bytes reuses, so the failure mode is wasted disk rather than a broken record.

**The type is detected, never taken from the caller.** `UploadFile.content_type` is whatever the
client wrote in the request, and the value that ends up on the row is the value the file is served
back with. Believing the declaration would let a caller store `<script>` as `application/pdf` and
have this origin hand it to a browser as a page. So PDF, PNG and JPEG are recognised by their own
signatures, and a DOCX has to be a ZIP container that actually holds `word/document.xml` — a ZIP
signature only proves the file is an archive.

**The size limit is enforced while copying, not after.** The multipart parser spools the whole body
to a temporary file before an endpoint runs, so this module cannot stop the request arriving; what it
can guarantee is that nothing past the limit is ever written under the storage root, which is the
directory the product owns. `app/middleware.py` refuses a declared oversize body earlier still.

The path stored on the row is relative to `settings.document_storage_root`, and the root is read per
call rather than captured at import time, so a test can point it at a temporary directory.
"""

import hashlib
import os
import uuid
import zipfile
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from app.config import settings
from app.models.document import Document, DocumentStatus, DocumentVersion, UploadedBy
from app.models.task import RoadmapTask

MAX_UPLOAD_BYTES = 20 * 1024 * 1024

# The copy size. 64 KiB matches what Starlette uses to stream responses, and it keeps a 20 MiB upload
# to a few hundred iterations without holding the file in memory.
CHUNK = 64 * 1024

# Enough for every signature below; the shortest is PNG's eight bytes.
SIGNATURE_BYTES = 16

MIME_PDF = "application/pdf"
MIME_PNG = "image/png"
MIME_JPEG = "image/jpeg"
MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

ALLOWED_MIME_TYPES = (MIME_PDF, MIME_PNG, MIME_JPEG, MIME_DOCX)

# The part that makes a ZIP a Word document rather than any other archive.
DOCX_PART = "word/document.xml"

TOO_LARGE = f"单个材料不能超过 {MAX_UPLOAD_BYTES // (1024 * 1024)} MB。"
UNSUPPORTED_TYPE = "材料只支持 PDF、PNG、JPEG 或 DOCX 格式。"
EMPTY_UPLOAD = "上传的文件是空的。"
MISSING_FILENAME = "上传缺少文件名。"
NO_SUCH_TASK = "找不到这个材料要求，或它不属于你。"
SUPERSEDED = "这份材料刚被另一个上传改动过，请重试。"


class UploadRejected(Exception):
    """A refusal with an HTTP status and a message the interface can show as-is.

    Carried as an exception rather than returned because every caller up the stack — the service, the
    route — has to do the same thing with it, and a return value is the one a later edit forgets to
    check.
    """

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def storage_root() -> Path:
    """The directory every stored file lives under. Read per call so tests can redirect it."""
    return Path(settings.document_storage_root)


def blob_relpath(digest: str) -> str:
    """Where a file with this digest lives, relative to the storage root.

    Content addressing is what makes "the same bytes are stored once" true without a lookup table:
    the digest is the address, and two uploads of the same bytes compute the same path. The two-level
    split keeps any one directory from collecting every file the way a flat layout would.
    """
    return f"blobs/{digest[:2]}/{digest}"


def detect_mime(staged: Path, head: bytes) -> str | None:
    """The type these bytes are, or None when this build does not accept them.

    `staged` is passed as well as `head` because the DOCX check needs to open the container, which
    needs the whole file, and the container is the only way to tell a Word document from any other
    archive.
    """
    if head.startswith(b"%PDF-"):
        return MIME_PDF
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return MIME_PNG
    if head.startswith(b"\xff\xd8\xff"):
        return MIME_JPEG
    if head.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(staged) as archive:
                if DOCX_PART in archive.namelist():
                    return MIME_DOCX
        except (zipfile.BadZipFile, OSError):
            return None
    return None


def _stage(upload: UploadFile) -> tuple[Path, str, int]:
    """Copy the upload into a temporary file under the storage root, hashing and counting as it goes.

    The temporary file is created inside the storage root rather than in the system temp directory so
    that the move into place below is a rename within one filesystem, which is atomic. Every failure
    path removes it: a rejected upload must leave nothing behind.
    """
    staging = storage_root() / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    temp = staging / f"{uuid.uuid4().hex}.part"

    digest = hashlib.sha256()
    size = 0
    try:
        with temp.open("wb") as sink:
            while True:
                chunk = upload.file.read(CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise UploadRejected(413, TOO_LARGE)
                digest.update(chunk)
                sink.write(chunk)
        if size == 0:
            raise UploadRejected(422, EMPTY_UPLOAD)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    return temp, digest.hexdigest(), size


def _accept(staged: Path) -> str:
    """The detected type, or a refusal that removes the staged file."""
    with staged.open("rb") as handle:
        head = handle.read(SIGNATURE_BYTES)
    mime_type = detect_mime(staged, head)
    if mime_type is None:
        staged.unlink(missing_ok=True)
        raise UploadRejected(415, UNSUPPORTED_TYPE)
    return mime_type


def _place(staged: Path, digest: str) -> str:
    """Move the staged file to its content-addressed home, or drop it if those bytes are here already."""
    relpath = blob_relpath(digest)
    destination = storage_root() / relpath
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        staged.unlink(missing_ok=True)
    else:
        os.replace(staged, destination)
    return relpath


def _require_own_task(session: Session, client_id: str, task_id: str | None) -> None:
    """Refuse a task that is someone else's, or that names nothing.

    Checked before anything is staged, so a rejected upload does not even write a temporary file. An
    absent task is a different case from a foreign one only in what it means to the caller; both are
    a `task_id` that must not be attached, and both are refused.
    """
    if task_id is None:
        return
    owned = session.execute(
        select(RoadmapTask.id).where(RoadmapTask.id == task_id, RoadmapTask.client_id == client_id)
    ).scalar_one_or_none()
    if owned is None:
        raise UploadRejected(422, NO_SUCH_TASK)


def store_upload(
    session: Session,
    client_id: str,
    upload: UploadFile,
    *,
    title: str | None = None,
    task_id: str | None = None,
) -> Document:
    """Create a material and its first version from one upload.

    The title falls back to the uploaded filename, and an upload with no filename at all is refused
    rather than given a made-up one: a material the applicant cannot recognise in their own list is
    worse than a refusal they can act on.
    """
    _require_own_task(session, client_id, task_id)

    filename = upload.filename
    if not filename:
        raise UploadRejected(422, MISSING_FILENAME)

    staged, digest, size = _stage(upload)
    mime_type = _accept(staged)
    relpath = _place(staged, digest)

    document = Document(
        id=str(uuid.uuid4()),
        client_id=client_id,
        title=title or filename,
        kind=None,
        status=DocumentStatus.UPLOADED,
        task_id=task_id,
    )
    version = DocumentVersion(
        id=str(uuid.uuid4()),
        document_id=document.id,
        version_no=1,
        filename=filename,
        mime_type=mime_type,
        byte_size=size,
        sha256=digest,
        storage_path=relpath,
        uploaded_by=UploadedBy.USER,
    )
    session.add(document)
    session.add(version)
    # Both rows are new, so the insert order is documents then versions and the pointer is written
    # after the row it names exists. See `add_version` for what happens when it is not.
    session.flush()
    document.current_version_id = version.id
    session.commit()
    return document


def add_version(session: Session, document: Document, upload: UploadFile) -> DocumentVersion:
    """Append a version to an existing material and make it the current one.

    The classification survives and the review state does not: the kind answers "what is this
    material", which a new file does not change, while `status` describes a review of bytes that have
    just been replaced. Reviews themselves stay attached to the version they judged, so an earlier
    verdict is not lost — it just stops describing the current file.

    Two uploads racing for the same number are resolved by retrying once: the loser's unique
    constraint violation is a fact about timing, not about the request.
    """
    filename = upload.filename
    if not filename:
        raise UploadRejected(422, MISSING_FILENAME)

    staged, digest, size = _stage(upload)
    mime_type = _accept(staged)
    relpath = _place(staged, digest)

    for attempt in (1, 2):
        next_no = (
            session.execute(
                select(func.coalesce(func.max(DocumentVersion.version_no), 0)).where(
                    DocumentVersion.document_id == document.id
                )
            ).scalar_one()
            + 1
        )
        version = DocumentVersion(
            id=str(uuid.uuid4()),
            document_id=document.id,
            version_no=next_no,
            filename=filename,
            mime_type=mime_type,
            byte_size=size,
            sha256=digest,
            storage_path=relpath,
            uploaded_by=UploadedBy.USER,
        )
        session.add(version)
        try:
            # The row has to exist before the pointer may name it. `documents` and
            # `document_versions` share no ORM relationship (see the model module), so SQLAlchemy has
            # no dependency to sort by and would otherwise emit the UPDATE on `documents` first —
            # measured: `insert or update on table "documents" violates foreign key constraint
            # "fk_documents_current_version_id"`.
            session.flush()
            document.current_version_id = version.id
            document.status = DocumentStatus.UPLOADED
            session.flush()
        except IntegrityError:
            session.rollback()
            if attempt == 2:
                raise UploadRejected(409, SUPERSEDED) from None
            document = session.get(Document, document.id)
            continue
        session.commit()
        return version
    raise UploadRejected(409, SUPERSEDED)
