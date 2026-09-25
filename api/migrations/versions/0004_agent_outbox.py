"""Add durable projection outbox for Agent-derived stores."""

from alembic import op

revision = "0004_agent_outbox"
down_revision = "0003_program_source_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE agent_projection_outbox (
            event_id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            aggregate_type TEXT NOT NULL,
            aggregate_id TEXT NOT NULL,
            source_revision INTEGER NOT NULL CHECK (source_revision >= 0),
            payload JSONB NOT NULL,
            occurred_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            lease_owner TEXT,
            lease_expires_at TIMESTAMPTZ,
            attempts INTEGER NOT NULL DEFAULT 0,
            acknowledged_at TIMESTAMPTZ,
            last_error_class TEXT
        );
        CREATE INDEX idx_agent_outbox_pending
            ON agent_projection_outbox(available_at, created_at)
            WHERE acknowledged_at IS NULL;
        CREATE INDEX idx_agent_outbox_aggregate
            ON agent_projection_outbox(aggregate_id, source_revision);
    """)


def downgrade() -> None:
    # Projection events are operational recovery evidence; never drop automatically.
    pass
