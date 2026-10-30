"""add the advisor's checkpoint tables

Revision ID: c4e8a1d2f6b9
Revises: 6afe86aaf7b6
Create Date: 2026-10-30 20:00:00

The four tables LangGraph's Postgres checkpointer (langgraph-checkpoint-postgres 3.2.0) reads and
writes, created here instead of by the library's `setup()` (openspec advisor-persistence D2). The
statements are a copy of the library's `MIGRATIONS[0..9]` at that version, so this revision does not
change when the library does; the versions are recorded in `checkpoint_migrations`, which makes the
library's own `setup()` a no-op on this schema. Two differences from the library's text, both because
these tables are new and empty: the three thread indexes are built without `CONCURRENTLY` (which
cannot run in Alembic's transaction), and the `blob` column is created nullable rather than created
NOT NULL and altered (migration 4).

`IF NOT EXISTS` everywhere, as in the library, so a database where someone already ran `setup()`
upgrades cleanly. Add-only: nothing existing is touched.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c4e8a1d2f6b9'
down_revision: Union[str, Sequence[str], None] = '6afe86aaf7b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS checkpoint_migrations (
    v INTEGER PRIMARY KEY
)""",
    """CREATE TABLE IF NOT EXISTS checkpoints (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    type TEXT,
    checkpoint JSONB NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
)""",
    """CREATE TABLE IF NOT EXISTS checkpoint_blobs (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL,
    version TEXT NOT NULL,
    type TEXT NOT NULL,
    blob BYTEA,
    PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
)""",
    """CREATE TABLE IF NOT EXISTS checkpoint_writes (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    channel TEXT NOT NULL,
    type TEXT,
    blob BYTEA NOT NULL,
    task_path TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
)""",
    # Library migration 4, for a database whose checkpoint_blobs predates this revision.
    "ALTER TABLE checkpoint_blobs ALTER COLUMN blob DROP NOT NULL",
    "CREATE INDEX IF NOT EXISTS checkpoints_thread_id_idx ON checkpoints(thread_id)",
    "CREATE INDEX IF NOT EXISTS checkpoint_blobs_thread_id_idx ON checkpoint_blobs(thread_id)",
    "CREATE INDEX IF NOT EXISTS checkpoint_writes_thread_id_idx ON checkpoint_writes(thread_id)",
    # Library migration 9, likewise.
    "ALTER TABLE checkpoint_writes ADD COLUMN IF NOT EXISTS task_path TEXT NOT NULL DEFAULT ''",
    # The library's migrations 0..9 are now in place.
    "INSERT INTO checkpoint_migrations (v) SELECT generate_series(0, 9) ON CONFLICT (v) DO NOTHING",
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS checkpoint_writes")
    op.execute("DROP TABLE IF EXISTS checkpoint_blobs")
    op.execute("DROP TABLE IF EXISTS checkpoints")
    op.execute("DROP TABLE IF EXISTS checkpoint_migrations")
