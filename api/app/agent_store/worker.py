import argparse
import asyncio
from dataclasses import asdict
import json
import os

from .database import create_agent_engine, create_session_factory, settings_from_env
from .projector import project_batch
from .repository import AgentStore


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Project PostgreSQL Agent outbox events to MySQL")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--once", action="store_true", help="process one bounded batch and exit")
    args = parser.parse_args(argv)
    if not 1 <= args.batch_size <= 500:
        parser.error("--batch-size must be between 1 and 500")
    if not 0.1 <= args.poll_seconds <= 60:
        parser.error("--poll-seconds must be between 0.1 and 60")
    return args


async def run_worker(*, batch_size: int, poll_seconds: float, once: bool = False) -> None:
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for the Agent projection worker")
    engine = create_agent_engine(settings_from_env())
    sessions = create_session_factory(engine)
    agent_store = AgentStore(sessions)
    from ..postgres_store import PostgresStore

    postgres_store = PostgresStore(database_url)
    try:
        while True:
            result = await project_batch(postgres_store, agent_store, limit=batch_size)
            print(json.dumps(asdict(result), ensure_ascii=False, sort_keys=True))
            if once:
                return
            if result.claimed == 0:
                await asyncio.sleep(poll_seconds)
    finally:
        postgres_store._connection.close()
        await engine.dispose()


def main() -> None:
    args = parse_args()
    asyncio.run(run_worker(batch_size=args.batch_size, poll_seconds=args.poll_seconds, once=args.once))


if __name__ == "__main__":
    main()
