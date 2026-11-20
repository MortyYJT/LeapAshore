"""Add the deadline reminder tables.

Deadline reminders by email (`docs/product/PRD-multi-device.md`, 3.4). Three new tables and nothing
else: no existing table, column or row is touched, so the previous release runs unchanged against
the upgraded schema and rolling the code back needs no downgrade and no data restore.
"""

from alembic import op
import sqlalchemy as sa

revision = "a9c4e7d2b6f1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "reminder_settings",
        sa.Column("account_id", sa.String(36), sa.ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("lead_days", sa.JSON(), nullable=False),
        sa.Column("unsubscribe_key", sa.String(64), nullable=False),
        sa.Column("unsubscribed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_table(
        "reminder_emails",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("send_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(120), nullable=True),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_reminder_emails_account_day", "reminder_emails", ["account_id", "send_date"])
    op.create_table(
        "reminder_deliveries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("record_key", sa.String(80), nullable=False),
        sa.Column("deadline", sa.Date(), nullable=False),
        sa.Column("lead_days", sa.Integer(), nullable=False),
        sa.Column(
            "email_id", sa.String(36), sa.ForeignKey("reminder_emails.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "account_id", "record_key", "deadline", "lead_days", name="uq_reminder_deliveries_once"
        ),
    )
    op.create_index("ix_reminder_deliveries_email", "reminder_deliveries", ["email_id"])


def downgrade():
    op.drop_table("reminder_deliveries")
    op.drop_table("reminder_emails")
    op.drop_table("reminder_settings")
