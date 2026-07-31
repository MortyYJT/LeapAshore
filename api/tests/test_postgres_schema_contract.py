from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
import psycopg
import pytest

from app.postgres_store import POSTGRES_SCHEMA_REVISIONS, PostgresStore


class FakeCursor:
    def __init__(
        self,
        rows: list[dict[str, str]] | None = None,
        execute_error: Exception | None = None,
    ) -> None:
        self.rows = rows or []
        self.execute_error = execute_error
        self.queries: list[str] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str) -> None:
        self.queries.append(" ".join(query.split()))
        if self.execute_error is not None:
            raise self.execute_error

    def fetchall(self) -> list[dict[str, str]]:
        return self.rows


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self._cursor

    def close(self) -> None:
        self.closed = True


def install_connection(monkeypatch: pytest.MonkeyPatch, connection: FakeConnection) -> None:
    def connect(
        database_url: str,
        *,
        autocommit: bool,
        row_factory: Any,
    ) -> FakeConnection:
        assert database_url == "postgresql://offerpilot"
        assert autocommit is True
        assert row_factory is not None
        return connection

    monkeypatch.setattr(psycopg, "connect", connect)


def test_declared_schema_revision_matches_alembic_heads() -> None:
    api_root = Path(__file__).resolve().parents[1]
    config = Config(str(api_root / "alembic.ini"))
    config.set_main_option("script_location", str(api_root / "migrations"))
    scripts = ScriptDirectory.from_config(config)
    assert frozenset(scripts.get_heads()) == POSTGRES_SCHEMA_REVISIONS


def test_postgres_store_only_reads_current_alembic_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = FakeCursor([{"version_num": "0003_program_source_versions"}])
    connection = FakeConnection(cursor)
    install_connection(monkeypatch, connection)

    store = PostgresStore("postgresql://offerpilot")

    assert store._connection is connection
    assert cursor.queries == ["SELECT version_num FROM alembic_version"]
    assert connection.closed is False


def test_postgres_store_rejects_outdated_alembic_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = FakeCursor([{"version_num": "0002_terms_acceptance"}])
    connection = FakeConnection(cursor)
    install_connection(monkeypatch, connection)

    with pytest.raises(
        RuntimeError,
        match=(
            "expected 0003_program_source_versions, "
            "found 0002_terms_acceptance.*alembic upgrade head"
        ),
    ):
        PostgresStore("postgresql://offerpilot")

    assert connection.closed is True


def test_postgres_store_rejects_database_without_alembic_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = FakeCursor(execute_error=RuntimeError('relation "alembic_version" does not exist'))
    connection = FakeConnection(cursor)
    install_connection(monkeypatch, connection)

    with pytest.raises(
        RuntimeError,
        match="not initialized by Alembic.*alembic upgrade head",
    ):
        PostgresStore("postgresql://offerpilot")

    assert connection.closed is True
