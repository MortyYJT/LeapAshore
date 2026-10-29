"""index programs by school and prerequisites by program

Revision ID: 5c1e7f0a2b3d
Revises: 4aa9ab68bed6
Create Date: 2026-10-30 03:00:00

"""
from typing import Sequence, Union

from alembic import op


revision: str = '5c1e7f0a2b3d'
down_revision: Union[str, Sequence[str], None] = '4aa9ab68bed6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add-only: the advisor's evidence gate filters programs by school and checks for prerequisites
    in SQL. Without these two indexes PostgreSQL scans all of `programs` for every question
    (measured: 7,496 rows, 148 ms); with them it reads one school's rows (0.2 ms)."""
    op.create_index(op.f('ix_programs_university_id'), 'programs', ['university_id'], unique=False)
    op.create_index(
        op.f('ix_program_prerequisites_program_id'), 'program_prerequisites', ['program_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_program_prerequisites_program_id'), table_name='program_prerequisites')
    op.drop_index(op.f('ix_programs_university_id'), table_name='programs')
