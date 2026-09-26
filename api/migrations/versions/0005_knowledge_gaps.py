"""Add privacy-minimized, deduplicated knowledge gap review candidates."""

from alembic import op


revision = "0005_knowledge_gaps"
down_revision = "0004_agent_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE knowledge_gap_candidates (
            candidate_id TEXT PRIMARY KEY,
            candidate_hash TEXT NOT NULL UNIQUE CHECK (length(candidate_hash) = 64),
            program_slug TEXT,
            topic_class TEXT NOT NULL CHECK (topic_class IN ('academic', 'prerequisite', 'language', 'tuition', 'deadline', 'policy', 'general')),
            status TEXT NOT NULL CHECK (status IN ('new', 'reviewing', 'source_pending', 'published', 'eval_failed', 'resolved', 'rejected')),
            occurrence_count INTEGER NOT NULL CHECK (occurrence_count >= 1),
            revision INTEGER NOT NULL CHECK (revision >= 0),
            payload JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL
        );
        CREATE INDEX idx_knowledge_gap_review_queue
            ON knowledge_gap_candidates(status, occurrence_count DESC, updated_at DESC);
        CREATE TABLE knowledge_gap_events (
            candidate_id TEXT NOT NULL REFERENCES knowledge_gap_candidates(candidate_id),
            event_id TEXT NOT NULL,
            PRIMARY KEY (candidate_id, event_id)
        );
    """)


def downgrade() -> None:
    # Candidate history is review evidence; the table is intentionally retained.
    pass
