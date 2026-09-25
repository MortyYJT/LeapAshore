"""Initial Agent projection tables, separate from product data."""

from alembic import op
import sqlalchemy as sa

revision = "agent_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projection_receipts",
        sa.Column("event_id", sa.String(64), primary_key=True),
        sa.Column("projection_name", sa.String(64), primary_key=True),
        sa.Column("outcome", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "advisor_thread_projection",
        sa.Column("aggregate_id", sa.String(128), primary_key=True),
        sa.Column("owner_ref", sa.String(64), nullable=False),
        sa.Column("source_revision", sa.Integer(), nullable=False),
        sa.Column("source_ref", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("content_hash", sa.String(64)),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_advisor_thread_projection_owner_ref", "advisor_thread_projection", ["owner_ref"])
    op.create_table(
        "advisor_audit",
        sa.Column("request_ref", sa.String(128), primary_key=True),
        sa.Column("workflow_version", sa.String(64), nullable=False),
        sa.Column("provider_class", sa.String(32), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
    )
    op.create_table(
        "review_candidate",
        sa.Column("candidate_ref", sa.String(128), primary_key=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("candidate_hash", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("review_candidate")
    op.drop_table("advisor_audit")
    op.drop_table("advisor_thread_projection")
    op.drop_table("projection_receipts")
