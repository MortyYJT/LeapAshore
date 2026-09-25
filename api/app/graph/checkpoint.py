from contextlib import asynccontextmanager
from hashlib import sha256
from pathlib import Path
from typing import AsyncIterator

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


def opaque_thread_key(user_ref: str, thread_ref: str, *, key: str) -> str:
    """Return a stable checkpoint key without persisting account or thread identifiers."""
    material = f"{user_ref}\0{thread_ref}".encode()
    return sha256(key.encode() + b"\0" + material).hexdigest()


def validate_checkpoint_path(path: str | Path, *, production: bool) -> Path:
    raw_path = Path(path).expanduser().absolute()
    if production and (raw_path == Path("/tmp") or Path("/tmp") in raw_path.parents):
        raise ValueError("生产环境图检查点必须使用持久化卷，不能放在 /tmp")
    resolved = raw_path.resolve()
    if resolved.exists() and not resolved.is_file():
        raise ValueError("图检查点路径必须指向文件")
    if not resolved.parent.exists():
        raise ValueError("图检查点目录必须预先挂载且可写")
    return resolved


@asynccontextmanager
async def create_checkpointer(path: str | Path, *, production: bool = False) -> AsyncIterator[AsyncSqliteSaver]:
    checkpoint_path = validate_checkpoint_path(path, production=production)
    async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
        await saver.setup()
        yield saver
