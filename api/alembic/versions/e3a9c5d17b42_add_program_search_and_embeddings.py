"""add program full-text search and embeddings

Revision ID: e3a9c5d17b42
Revises: c4e8a1d2f6b9
Create Date: 2026-10-30 18:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector


revision: str = 'e3a9c5d17b42'
down_revision: Union[str, Sequence[str], None] = 'c4e8a1d2f6b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Kept in step with `app.models.program.SEARCH_TSV_SQL` (a test compares the two).
SEARCH_TSV_SQL = (
    "to_tsvector('english'::regconfig, coalesce(name_en, '') || ' ' || "
    "CASE WHEN name IS DISTINCT FROM name_en THEN coalesce(name, '') ELSE '' END)"
)


def upgrade() -> None:
    """Add-only (openspec hybrid-retrieval D2): an extension, a generated column with its index, and a
    new table. Nothing existing is dropped or rewritten except that the generated column is filled in
    for every program row."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column(
        'programs',
        sa.Column('search_tsv', sa.dialects.postgresql.TSVECTOR(), sa.Computed(SEARCH_TSV_SQL, persisted=True)),
    )
    op.create_index('ix_programs_search_tsv', 'programs', ['search_tsv'], postgresql_using='gin')
    op.create_table(
        'program_embeddings',
        sa.Column('program_id', sa.String(length=64), nullable=False),
        sa.Column('model', sa.Text(), nullable=False),
        sa.Column('content_sha256', sa.String(length=64), nullable=False),
        sa.Column('embedding', Vector(1024), nullable=False),
        sa.Column('embedded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['program_id'], ['programs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('program_id'),
    )


def downgrade() -> None:
    op.drop_table('program_embeddings')
    op.drop_index('ix_programs_search_tsv', table_name='programs')
    op.drop_column('programs', 'search_tsv')
    # The extension stays: another database object may use it, and dropping it is not add-only.
