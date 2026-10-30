"""add source verifications and the guard on sources.verified_at

Revision ID: c8e1f4a7b2d9
Revises: a3d5f8c1e2b7
Create Date: 2026-10-30 21:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'c8e1f4a7b2d9'
down_revision: Union[str, Sequence[str], None] = 'a3d5f8c1e2b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# openspec source-verification D4. A new non-null date needs a confirmation row written in the same
# transaction, for the same page and moment, by an account whose role is admin. Clearing is always
# allowed: it only withdraws a claim. 42501 is insufficient_privilege.
GUARD = """
CREATE FUNCTION sources_verified_at_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.status = '已核验' AND NEW.verified_at IS NULL THEN
        RAISE EXCEPTION 'sources.status 已核验 needs a verified_at set by an admin''s confirmation'
            USING ERRCODE = '42501';
    END IF;
    IF NEW.verified_at IS NULL THEN
        RETURN NEW;
    END IF;
    IF TG_OP = 'UPDATE' AND NEW.verified_at IS NOT DISTINCT FROM OLD.verified_at THEN
        RETURN NEW;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM source_verifications v JOIN accounts a ON a.id = v.account_id
        WHERE v.source_id = NEW.id AND v.action = 'verify' AND v.decided_at = NEW.verified_at
          AND v.txid = txid_current() AND a.role = 'admin'
    ) THEN
        RAISE EXCEPTION 'sources.verified_at is written only by an admin''s confirmation (source_verifications)'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER sources_verified_at_guard BEFORE INSERT OR UPDATE ON sources
    FOR EACH ROW EXECUTE FUNCTION sources_verified_at_guard();
"""


def upgrade() -> None:
    """Add-only: one table, one function, one trigger."""
    op.create_table(
        'source_verifications',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('source_id', sa.String(length=36), nullable=False),
        sa.Column('action', sa.String(length=16), nullable=False),
        sa.Column('content_sha256', sa.String(length=64), nullable=False),
        sa.Column('account_id', sa.String(length=36), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('txid', sa.BigInteger(), server_default=sa.text('txid_current()'), nullable=False),
        sa.CheckConstraint("action IN ('verify', 'revoke')", name='ck_source_verifications_action'),
        sa.ForeignKeyConstraint(['source_id'], ['sources.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_source_verifications_source_id', 'source_verifications', ['source_id'])
    op.execute(GUARD)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS sources_verified_at_guard ON sources")
    op.execute("DROP FUNCTION IF EXISTS sources_verified_at_guard()")
    op.drop_index('ix_source_verifications_source_id', table_name='source_verifications')
    op.drop_table('source_verifications')
