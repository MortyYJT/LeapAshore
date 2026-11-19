"""Add a version to applicant-editable rows and a create key to application plans.

Sync conflict handling (`docs/product/PRD-multi-device.md`, 3.3). Every existing row starts at
version 1; the constant default makes each `ADD COLUMN` a catalogue change, not a table rewrite.
Add-only: no column or constraint is dropped by the upgrade.
"""

from alembic import op
import sqlalchemy as sa

revision = "e5f6a7b8c9d0"
down_revision = "d1a2b3c4d5e6"
branch_labels = None
depends_on = None

VERSIONED_TABLES = ("application_plans", "applications", "roadmap_tasks", "profiles")


def upgrade():
    for table in VERSIONED_TABLES:
        op.add_column(
            table,
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        )
    op.add_column(
        "application_plans", sa.Column("create_key", sa.String(64), nullable=True)
    )
    op.create_unique_constraint(
        "uq_application_plans_create_key",
        "application_plans",
        ["client_id", "create_key"],
    )


def downgrade():
    op.drop_constraint(
        "uq_application_plans_create_key", "application_plans", type_="unique"
    )
    op.drop_column("application_plans", "create_key")
    for table in VERSIONED_TABLES:
        op.drop_column(table, "version")
