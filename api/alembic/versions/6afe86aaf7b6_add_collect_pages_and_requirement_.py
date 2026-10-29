"""add collect pages and requirement changes

Revision ID: 6afe86aaf7b6
Revises: b7d4e2a91c60
Create Date: 2026-10-30 15:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '6afe86aaf7b6'
down_revision: Union[str, Sequence[str], None] = 'b7d4e2a91c60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add-only (openspec collect-queue D1, D7): two new tables, nothing existing is touched."""
    op.create_table('collect_pages',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('school_key', sa.String(length=96), nullable=False),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('program_name', sa.Text(), nullable=False),
    sa.Column('cricos_code', sa.String(length=16), nullable=True),
    sa.Column('render', sa.Boolean(), nullable=False),
    sa.Column('origin', sa.String(length=16), nullable=False),
    sa.Column('state', sa.String(length=16), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('snapshot_sha256', sa.String(length=64), nullable=True),
    sa.Column('text_sha256', sa.String(length=64), nullable=True),
    sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('rejected', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('model', sa.String(length=64), nullable=True),
    sa.Column('cost_cny', sa.Numeric(precision=10, scale=4), nullable=False),
    sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('extracted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('school_key', 'url')
    )
    op.create_index(op.f('ix_collect_pages_school_key'), 'collect_pages', ['school_key'], unique=False)
    op.create_index(op.f('ix_collect_pages_state'), 'collect_pages', ['state'], unique=False)
    op.create_table('requirement_changes',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('page_id', sa.String(length=36), nullable=False),
    sa.Column('school_key', sa.String(length=96), nullable=False),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('program_name', sa.Text(), nullable=False),
    sa.Column('field', sa.String(length=32), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('old_value', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('new_value', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('old_sha256', sa.String(length=64), nullable=True),
    sa.Column('new_sha256', sa.String(length=64), nullable=True),
    sa.Column('detected_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['page_id'], ['collect_pages.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_requirement_changes_detected_at'), 'requirement_changes', ['detected_at'], unique=False)
    op.create_index(op.f('ix_requirement_changes_page_id'), 'requirement_changes', ['page_id'], unique=False)
    op.create_index(op.f('ix_requirement_changes_school_key'), 'requirement_changes', ['school_key'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_requirement_changes_school_key'), table_name='requirement_changes')
    op.drop_index(op.f('ix_requirement_changes_page_id'), table_name='requirement_changes')
    op.drop_index(op.f('ix_requirement_changes_detected_at'), table_name='requirement_changes')
    op.drop_table('requirement_changes')
    op.drop_index(op.f('ix_collect_pages_state'), table_name='collect_pages')
    op.drop_index(op.f('ix_collect_pages_school_key'), table_name='collect_pages')
    op.drop_table('collect_pages')
