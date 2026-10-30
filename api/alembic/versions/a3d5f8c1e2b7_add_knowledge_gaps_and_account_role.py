"""add knowledge gaps, their reports and the account role

Revision ID: a3d5f8c1e2b7
Revises: f7c2d9a4e816
Create Date: 2026-10-30 18:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = 'a3d5f8c1e2b7'
down_revision: Union[str, Sequence[str], None] = 'f7c2d9a4e816'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add-only (openspec knowledge-gaps): two new tables and one nullable column."""
    op.add_column('accounts', sa.Column('role', sa.String(length=16), nullable=True))
    op.create_table(
        'knowledge_gaps',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('gap_key', sa.String(length=64), nullable=False),
        sa.Column('route', sa.String(length=16), nullable=False),
        sa.Column('reason', sa.String(length=32), nullable=False),
        sa.Column('university_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('fields', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('subject_words', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('topics', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('report_count', sa.Integer(), nullable=False),
        sa.Column('first_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reviewed_by', sa.String(length=36), nullable=True),
        sa.Column('review_note', sa.Text(), nullable=True),
        sa.Column('recollect', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(['reviewed_by'], ['accounts.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('gap_key'),
    )
    op.create_index('ix_knowledge_gaps_status', 'knowledge_gaps', ['status'])
    op.create_table(
        'knowledge_gap_reports',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('gap_id', sa.String(length=36), nullable=False),
        sa.Column('reporter_hash', sa.String(length=64), nullable=True),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['gap_id'], ['knowledge_gaps.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_knowledge_gap_reports_gap_id', 'knowledge_gap_reports', ['gap_id'])
    op.create_index('ix_knowledge_gap_reports_reporter_hash', 'knowledge_gap_reports', ['reporter_hash'])
    op.create_index('ix_knowledge_gap_reports_created_at', 'knowledge_gap_reports', ['created_at'])


def downgrade() -> None:
    op.drop_table('knowledge_gap_reports')
    op.drop_index('ix_knowledge_gaps_status', table_name='knowledge_gaps')
    op.drop_table('knowledge_gaps')
    op.drop_column('accounts', 'role')
