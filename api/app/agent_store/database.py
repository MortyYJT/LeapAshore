import os
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine


@dataclass(frozen=True)
class AgentDatabaseSettings:
    url: str
    connect_timeout_seconds: int = 3
    pool_size: int = 5


def settings_from_env() -> AgentDatabaseSettings:
    return AgentDatabaseSettings(
        url=os.getenv("MYSQL_AGENT_URL", ""),
        connect_timeout_seconds=max(1, int(os.getenv("MYSQL_AGENT_CONNECT_TIMEOUT", "3"))),
        pool_size=max(1, int(os.getenv("MYSQL_AGENT_POOL_SIZE", "5"))),
    )


def create_agent_engine(settings: AgentDatabaseSettings) -> AsyncEngine:
    if not settings.url:
        raise ValueError("MYSQL_AGENT_URL is required")
    if not settings.url.startswith("mysql+asyncmy://"):
        raise ValueError("MYSQL_AGENT_URL must use mysql+asyncmy")
    return create_async_engine(
        settings.url,
        pool_size=settings.pool_size,
        pool_pre_ping=True,
        connect_args={"connect_timeout": settings.connect_timeout_seconds},
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)
