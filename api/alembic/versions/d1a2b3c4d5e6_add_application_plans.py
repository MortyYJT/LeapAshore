"""Add applicant-owned application preparation records."""

from alembic import op
import sqlalchemy as sa

revision = "d1a2b3c4d5e6"
down_revision = "c8e1f4a7b2d9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "application_plans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "client_id",
            sa.String(36),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "catalog_program_id",
            sa.String(64),
            sa.ForeignKey("programs.id"),
            nullable=True,
        ),
        sa.Column("school", sa.String(200), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("round", sa.String(120), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("deadline_override", sa.Boolean(), nullable=False),
        sa.Column("deadline", sa.Date(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("materials_ready", sa.Boolean(), nullable=False),
        sa.Column("material_notes", sa.Text(), nullable=False),
        sa.UniqueConstraint("client_id", "catalog_program_id"),
    )
    op.create_index(
        "ix_application_plans_client_id", "application_plans", ["client_id"]
    )


def downgrade():
    op.drop_table("application_plans")
