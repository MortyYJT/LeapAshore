"""Where the advisor keeps its conversations: LangGraph's Postgres checkpointer (openspec
advisor-persistence).

A thread is one conversation, keyed ``{subject}:{conversation_id}``. Everything the graph needs to
pick a turn up again lives in three tables, ``checkpoints``, ``checkpoint_blobs`` and
``checkpoint_writes``, created by Alembic revision ``c4e8a1d2f6b9`` rather than by the library's
``setup()`` (D2). A turn paused on a portfolio change therefore survives a restart of the API.

The saver is the library's synchronous ``PostgresSaver`` over a ``psycopg_pool.ConnectionPool``, with
its async methods run in a worker thread (D3). The async saver binds itself to the event loop it was
created on; the synchronous one works from uvicorn's loop, from a test client's per-request loop and
from a Celery worker alike.
"""

import asyncio
import hashlib
import threading
from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import contextmanager
from typing import Any

import psycopg
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import ChannelVersions, Checkpoint, CheckpointMetadata, CheckpointTuple
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from sqlalchemy.engine import make_url

from app.config import settings

# How many of the library's own migrations revision c4e8a1d2f6b9 applies (v0..v9), and a digest of
# their text. A version of langgraph-checkpoint-postgres that adds or changes one fails
# `test_advisor_persistence.py` until a new Alembic revision carries it (D2).
MIGRATIONS_APPLIED = 10
MIGRATIONS_DIGEST = "c9180fdd1fd0c6b30e7fe999a68a394197fce554f87623f0776281b333e3f48e"


def conninfo(url: str | None = None) -> str:
    """The libpq connection string for the application's database URL (`postgresql+psycopg://...`)."""
    return make_url(url or settings.database_url).set(drivername="postgresql").render_as_string(
        hide_password=False
    )


class Checkpointer(PostgresSaver):
    """``PostgresSaver`` whose pool opens on first use and whose async methods run in a thread."""

    def __init__(self, url: str | None = None, *, max_size: int | None = None) -> None:
        pool = ConnectionPool(
            conninfo(url),
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
            min_size=1,
            max_size=max_size or settings.checkpoint_pool_size,
            # A connection the database dropped (a restart, an idle timeout) is replaced on checkout
            # instead of failing the turn, as `pool_pre_ping` does for SQLAlchemy.
            check=ConnectionPool.check_connection,
            open=False,
            name="advisor-checkpoints",
        )
        super().__init__(pool)
        self._opening = threading.Lock()

    @property
    def pool(self) -> ConnectionPool:
        return self.conn  # type: ignore[return-value]

    def _ensure_open(self) -> None:
        # Importing the API must not need a database, so the pool opens on the first checkpoint.
        if self.pool.closed:
            with self._opening:
                if self.pool.closed:
                    self.pool.open(wait=True, timeout=10)

    @contextmanager
    def _cursor(self, *, pipeline: bool = False) -> Iterator[Any]:
        self._ensure_open()
        with super()._cursor(pipeline=pipeline) as cur:
            yield cur

    def close(self) -> None:
        if not self.pool.closed:
            self.pool.close()

    # --- async API: the same work in a worker thread (the saver's own lock serialises it) ---

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        return await asyncio.to_thread(self.get_tuple, config)

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        items = await asyncio.to_thread(lambda: list(self.list(config, filter=filter, before=before, limit=limit)))
        for item in items:
            yield item

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        return await asyncio.to_thread(self.put, config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        await asyncio.to_thread(self.put_writes, config, writes, task_id, task_path)

    async def adelete_thread(self, thread_id: str) -> None:
        await asyncio.to_thread(self.delete_thread, thread_id)

    async def aprune(self, thread_ids: Sequence[str], *, strategy: str = "keep_latest") -> None:
        await asyncio.to_thread(self.prune, thread_ids, strategy=strategy)

    async def aget_delta_channel_history(self, *, config: RunnableConfig, channels: Sequence[str]):
        return await asyncio.to_thread(self.get_delta_channel_history, config=config, channels=channels)


# The API process's saver. Tests that need a "restarted" service build a second one.
checkpointer = Checkpointer()


def thread_id(subject: str, conversation_id: str) -> str:
    """The checkpoint thread for one conversation of one subject. Conversation ids never contain
    ``:`` (the advisor router validates them), so ``{subject}:`` is a prefix only that subject has."""
    return f"{subject}:{conversation_id}"


def lock_key(thread: str) -> int:
    """A signed 64-bit advisory-lock key for a thread."""
    return int.from_bytes(hashlib.blake2b(thread.encode(), digest_size=8).digest(), "big", signed=True)


class TurnLock:
    """The resume lock of one thread (D5): one confirm at a time may resume a paused turn.

    A session-level advisory lock on a connection of its own, held from ``acquire`` until ``release``,
    which the detached turn calls when it ends. Releasing closes the connection rather than returning it
    to a pool, so the lock cannot outlive the turn on a pooled connection, and a process that dies
    mid-turn releases it with its socket.
    """

    def __init__(self, thread: str) -> None:
        self.thread = thread
        self._conn: psycopg.AsyncConnection | None = None

    async def acquire(self) -> bool:
        conn = await psycopg.AsyncConnection.connect(conninfo(), autocommit=True, connect_timeout=5)
        try:
            cur = await conn.execute("SELECT pg_try_advisory_lock(%s)", (lock_key(self.thread),))
            row = await cur.fetchone()
        except BaseException:
            await conn.close()
            raise
        if row and row[0]:
            self._conn = conn
            return True
        await conn.close()
        return False

    async def release(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            await conn.close()
