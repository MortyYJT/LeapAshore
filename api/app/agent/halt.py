"""Stopping a turn that is still running.

The applicant's stop does not cancel the turn's task: a model call cut off before its last chunk
reports no usage, and the daily caps count what calls report (openspec advisor-limits D4). Instead the
graph is asked to end at its next edge. The call in flight finishes and is charged, and nothing new
starts: no further tool runs, no further model call.

The requests are kept in this process's memory, which is enough while the API is one process
(`api/Dockerfile` starts a single uvicorn). With several workers the flag has to move to Redis.
"""

from langchain_core.runnables import RunnableConfig

_requested: set[str] = set()


def request(thread: str) -> None:
    _requested.add(thread)


def clear(thread: str) -> None:
    _requested.discard(thread)


def requested(thread: str | None) -> bool:
    return thread in _requested


def halted(config: RunnableConfig | None) -> bool:
    """Whether the thread this run belongs to has been asked to stop."""
    return requested(((config or {}).get("configurable") or {}).get("thread_id"))
