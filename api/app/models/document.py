"""The material library: an identity per material, and one row per uploaded file.

A material is a lifecycle, not a row of metadata — uploaded, classified, sent for review, revised —
so it is two tables rather than one. `documents` is the identity the applicant sees and the state
the review moves; `document_versions` is the immutable list of files, one per upload.

The file itself is deliberately absent from both: bytes live on disk under
`settings.document_storage_root`, addressed by their SHA-256 digest, and the row carries only a path
relative to that root. Storing them here would make backup and migration carry every scan the
applicant ever uploaded, and the parent design (`note/superpowers/specs/2026-10-06-stage-2-database-design.md`
§3.3) already rejected it.

No ORM relationship is declared between these two tables, on purpose. They reference each other —
`documents.current_version_id` points forward, `document_versions.document_id` points back — and a
declared relationship would make SQLAlchemy null a NOT NULL foreign key before the database's own
`ON DELETE CASCADE` ever ran; `app/models/roadmap.py` records the same trap for `MaterialTemplate`.
With no relationship the ORM emits a plain DELETE and the database decides, which is what the
`ondelete` rules below are for. Reads use explicit `select()` statements, as
`app/services/applications.py` does.
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# The kinds a material can be classified as. `kind` stays null until the applicant archives it,
# because what a file is, is their claim to make rather than the system's guess.
KIND_VALUES = (
    "transcript",
    "cv",
    "ps",
    "recommendation",
    "language",
    "passport",
    "gs",
    "other",
)


class DocumentKind(StrEnum):
    TRANSCRIPT = "transcript"
    CV = "cv"
    PS = "ps"
    RECOMMENDATION = "recommendation"
    LANGUAGE = "language"
    PASSPORT = "passport"
    GS = "gs"
    OTHER = "other"


class DocumentStatus(StrEnum):
    """The review lifecycle. Independent of `kind`: a revision does not unclassify a material."""

    UPLOADED = "uploaded"
    ARCHIVED = "archived"
    UNDER_REVIEW = "under_review"
    NEEDS_REVISION = "needs_revision"
    ACCEPTED = "accepted"


class UploadedBy(StrEnum):
    """Who put this version there. Only `user` is reachable until the agent lands in M4."""

    USER = "user"
    AGENT = "agent"


def sql_in_list(values: tuple[str, ...]) -> str:
    """The values as a SQL `IN` list.

    Shared with `app/models/review.py`, which constrains its own enumerations the same way. Built
    from a module's own constants and never from input, so the string that reaches the constraint is
    a literal list rather than anything a caller supplied.
    """
    return ", ".join(f"'{value}'" for value in values)


class Document(Base):
    """One material the applicant owns."""

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            f"kind IS NULL OR kind IN ({sql_in_list(KIND_VALUES)})",
            name="ck_documents_kind",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    client_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clients.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(Text)
    kind: Mapped[str | None] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(16), default=DocumentStatus.UPLOADED)

    # SET NULL on both, not RESTRICT. A recomputation deletes the applicant's system task rows
    # (`app/services/roadmap_tasks.py`), and `api/tests/test_seed.py` deletes every program; a
    # material outlives the requirement it happened to be prepared for.
    task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("roadmap_tasks.id", ondelete="SET NULL")
    )
    program_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("programs.id", ondelete="SET NULL")
    )

    # The database's foreign key to `document_versions` is added by the migration after both tables
    # exist; the two tables reference each other, so one of the two constraints has to be created
    # second whoever writes it.
    current_version_id: Mapped[str | None] = mapped_column(String(36))

    archived_by: Mapped[str | None] = mapped_column(String(8))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DocumentVersion(Base):
    """One uploaded file. Immutable: a revision is a new row, never an edit of this one."""

    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version_no"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE")
    )
    version_no: Mapped[int] = mapped_column(Integer)

    filename: Mapped[str] = mapped_column(Text)
    # The type detected from the bytes, not the one the caller declared: this value is what the file
    # is served back as, so trusting a claim here would let a caller choose how their upload is
    # interpreted by a browser later.
    mime_type: Mapped[str] = mapped_column(String(128))
    byte_size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    # Relative to `settings.document_storage_root`, never absolute: an absolute path would bake one
    # machine's layout into the database, and the repository's own rules keep local paths out.
    storage_path: Mapped[str] = mapped_column(Text)

    uploaded_by: Mapped[str] = mapped_column(String(8), default=UploadedBy.USER)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
