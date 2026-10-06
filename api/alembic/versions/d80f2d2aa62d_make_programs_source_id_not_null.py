"""make programs.source_id not null

A program is a claim about an official page. The schema enforced that for
`review_criteria.source_id` and `document_review_findings.criterion_id` but left `programs.source_id`
to the seed, and the router's guard was the only thing standing between one sourceless row and a
500 for the whole catalogue. The column becomes mandatory here, and the router learns to serve the
healthy rows and name the defective ids instead of failing the request outright.

`SET NOT NULL` scans the table and refuses to run if any row is null, so a database that holds such
a row fails the migration instead of silently keeping it; the seed fills the column for every row,
so the live database passes. The reverse is unrestricted: the column was nullable before this
revision and a downgrade restores exactly that.

Revision ID: d80f2d2aa62d
Revises: 0465b9338c20
Create Date: 2026-10-06 19:17:07.664007

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd80f2d2aa62d'
down_revision: Union[str, Sequence[str], None] = '0465b9338c20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        "programs",
        "source_id",
        existing_type=sa.String(length=36),
        nullable=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "programs",
        "source_id",
        existing_type=sa.String(length=36),
        nullable=True,
    )
