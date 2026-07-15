"""Record the terms version accepted by each newly registered user."""

from alembic import op


revision = "0002_terms_acceptance"
down_revision = "0001_beta_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE users ADD COLUMN IF NOT EXISTS terms_accepted_at TIMESTAMPTZ;
        ALTER TABLE users ADD COLUMN IF NOT EXISTS terms_version TEXT;
    """)


def downgrade() -> None:
    # Consent evidence is retained instead of being destructively removed.
    pass
