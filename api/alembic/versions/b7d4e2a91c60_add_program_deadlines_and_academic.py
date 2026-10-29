"""add program deadlines and the academic requirement

Revision ID: b7d4e2a91c60
Revises: 5c1e7f0a2b3d
Create Date: 2026-10-30 12:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'b7d4e2a91c60'
down_revision: Union[str, Sequence[str], None] = '5c1e7f0a2b3d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add-only (openspec requirement-dates D1): a nullable column and a new table, nothing dropped or
    rewritten. Existing rows read NULL / no deadlines until the importer runs."""
    op.add_column('programs', sa.Column('academic_requirement', sa.Text(), nullable=True))
    op.add_column('programs', sa.Column('academic_source_url', sa.Text(), nullable=True))
    op.create_table(
        'program_deadlines',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('program_id', sa.String(length=64), nullable=False),
        sa.Column('label', sa.Text(), nullable=True),
        sa.Column('deadline', sa.Date(), nullable=False),
        sa.Column('quote', sa.Text(), nullable=False),
        sa.Column('source_url', sa.Text(), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['program_id'], ['programs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_program_deadlines_program_id'), 'program_deadlines', ['program_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_program_deadlines_program_id'), table_name='program_deadlines')
    op.drop_table('program_deadlines')
    op.drop_column('programs', 'academic_source_url')
    op.drop_column('programs', 'academic_requirement')
