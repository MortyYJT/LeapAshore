"""Persist immutable official-program source versions and review state."""

from alembic import op


revision = "0003_program_source_versions"
down_revision = "0002_terms_acceptance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS program_source_versions (
            version_id TEXT PRIMARY KEY,
            program_slug TEXT NOT NULL,
            source_id TEXT NOT NULL,
            content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
            base_hash TEXT CHECK (base_hash IS NULL OR length(base_hash) = 64),
            status TEXT NOT NULL CHECK (status IN ('pending_review', 'published', 'superseded', 'rejected')),
            payload JSONB NOT NULL,
            submitted_at TIMESTAMPTZ NOT NULL,
            reviewed_at TIMESTAMPTZ
        );
        CREATE INDEX IF NOT EXISTS idx_source_versions_program_submitted
            ON program_source_versions(program_slug, submitted_at DESC);
        CREATE INDEX IF NOT EXISTS idx_source_versions_program_status
            ON program_source_versions(program_slug, status);
    """)


def downgrade() -> None:
    # Source review history is audit evidence and is never dropped automatically.
    pass
