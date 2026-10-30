"""add snapshot pages, chunks and chunk embeddings

Revision ID: f7c2d9a4e816
Revises: e3a9c5d17b42
Create Date: 2026-10-30 21:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector


revision: str = 'f7c2d9a4e816'
down_revision: Union[str, Sequence[str], None] = 'e3a9c5d17b42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Kept in step with `app.models.snapshot.CHUNK_TSV_SQL` (a test compares the two).
CHUNK_TSV_SQL = "to_tsvector('english'::regconfig, text)"


def upgrade() -> None:
    """Add-only (openspec snapshot-rag D4): three new tables, nothing existing is touched."""
    op.create_table(
        'snapshot_pages',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column('school_key', sa.String(length=96), nullable=False),
        sa.Column('university_id', sa.String(length=64), nullable=False),
        sa.Column('program_id', sa.String(length=64), nullable=True),
        sa.Column('title', sa.Text(), nullable=True),
        sa.Column('snapshot_sha256', sa.String(length=64), nullable=False),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('content_sha256', sa.String(length=64), nullable=False),
        sa.Column('chunker', sa.String(length=32), nullable=False),
        sa.Column('chunk_count', sa.Integer(), nullable=False),
        sa.Column('ingested_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['university_id'], ['universities.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['program_id'], ['programs.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('url'),
    )
    op.create_index('ix_snapshot_pages_school_key', 'snapshot_pages', ['school_key'])
    op.create_index('ix_snapshot_pages_university_id', 'snapshot_pages', ['university_id'])
    op.create_index('ix_snapshot_pages_program_id', 'snapshot_pages', ['program_id'])
    op.create_table(
        'snapshot_chunks',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('page_id', sa.String(length=36), nullable=False),
        sa.Column('ordinal', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('content_sha256', sa.String(length=64), nullable=False),
        sa.Column('search_tsv', sa.dialects.postgresql.TSVECTOR(), sa.Computed(CHUNK_TSV_SQL, persisted=True)),
        sa.ForeignKeyConstraint(['page_id'], ['snapshot_pages.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_snapshot_chunks_page_id', 'snapshot_chunks', ['page_id'])
    op.create_index('ix_snapshot_chunks_search_tsv', 'snapshot_chunks', ['search_tsv'], postgresql_using='gin')
    op.create_table(
        'snapshot_chunk_embeddings',
        sa.Column('chunk_id', sa.String(length=36), nullable=False),
        sa.Column('model', sa.Text(), nullable=False),
        sa.Column('content_sha256', sa.String(length=64), nullable=False),
        sa.Column('embedding', Vector(1024), nullable=False),
        sa.Column('embedded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['chunk_id'], ['snapshot_chunks.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('chunk_id'),
    )


def downgrade() -> None:
    op.drop_table('snapshot_chunk_embeddings')
    op.drop_index('ix_snapshot_chunks_search_tsv', table_name='snapshot_chunks')
    op.drop_index('ix_snapshot_chunks_page_id', table_name='snapshot_chunks')
    op.drop_table('snapshot_chunks')
    op.drop_index('ix_snapshot_pages_program_id', table_name='snapshot_pages')
    op.drop_index('ix_snapshot_pages_university_id', table_name='snapshot_pages')
    op.drop_index('ix_snapshot_pages_school_key', table_name='snapshot_pages')
    op.drop_table('snapshot_pages')
