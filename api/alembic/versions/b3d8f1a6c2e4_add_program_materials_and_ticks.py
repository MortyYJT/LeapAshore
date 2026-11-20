"""Add per-program application materials and per-material ticks.

Material merging (`docs/product/PRD-multi-device.md`, 3.7). Add-only:

- `program_materials`: one row per material a program's official page asks for, as collected.
- `programs.materials_snapshot_sha256`: the snapshot the materials were read from; NULL means nobody
  has read the page for materials yet.
- `application_plans.material_ticks` and `custom_materials`: the applicant's ticks on the catalogue's
  materials, and their own checklist lines.

`application_plans.materials_ready` stays, unread, so an image from before this revision still runs.
A row that had it set keeps what the applicant said, as one ticked line of their own checklist: the
flag covered "everything" at a time when the tool listed nothing, so it is not turned into ticks on
materials the applicant was never shown. A downgrade drops the new columns and leaves the flag as it
was, so it loses only ticks made after the upgrade.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b3d8f1a6c2e4"
down_revision = "a9c4e7d2b6f1"
branch_labels = None
depends_on = None

# The applicant's earlier whole-application tick, kept as a line they can untick or delete.
LEGACY_ITEM_ID = "legacy-all"
LEGACY_ITEM_LABEL = "全部材料（改版前的整体自查）"


def upgrade():
    op.create_table(
        "program_materials",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("program_id", sa.String(64), sa.ForeignKey("programs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(48), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("count", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_program_materials_program_id", "program_materials", ["program_id"])
    op.add_column("programs", sa.Column("materials_snapshot_sha256", sa.String(64), nullable=True))
    op.add_column(
        "application_plans",
        sa.Column("material_ticks", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "application_plans",
        sa.Column("custom_materials", postgresql.JSONB(), nullable=False, server_default="[]"),
    )
    plans = sa.table(
        "application_plans",
        sa.column("materials_ready", sa.Boolean()),
        sa.column("custom_materials", postgresql.JSONB()),
    )
    op.execute(
        plans.update()
        .where(plans.c.materials_ready.is_(True))
        .values(custom_materials=[{"id": LEGACY_ITEM_ID, "label": LEGACY_ITEM_LABEL, "done": True}])
    )


def downgrade():
    op.drop_column("application_plans", "custom_materials")
    op.drop_column("application_plans", "material_ticks")
    op.drop_column("programs", "materials_snapshot_sha256")
    op.drop_index("ix_program_materials_program_id", table_name="program_materials")
    op.drop_table("program_materials")
