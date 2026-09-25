from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
import psycopg
import pytest

from app.postgres_store import POSTGRES_SCHEMA_REVISIONS, PostgresStore, _MeasuredConnectionLock


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
    cursor = FakeCursor([{"version_num": "0004_agent_outbox"}])
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
            "expected 0004_agent_outbox, "
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


def test_connection_lock_reports_only_measured_queue_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[float] = []
    clock = iter([10.0, 10.125])
    monkeypatch.setattr("app.postgres_store.perf_counter", lambda: next(clock))
    monkeypatch.setattr(
        "app.postgres_store.record_postgres_connection_slot_wait",
        observed.append,
    )

    with _MeasuredConnectionLock():
        pass

    assert observed == [0.125]


def test_transaction_and_advisory_lock_report_success_and_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Transaction:
        def __enter__(self) -> None:
            return None

        def __exit__(self, *_args: object) -> None:
            return None

    class TransactionConnection:
        def transaction(self) -> Transaction:
            return Transaction()

    class AdvisoryCursor:
        def __init__(self) -> None:
            self.fail = False
            self.parameters: list[tuple[str, ...]] = []

        def execute(self, _query: str, parameters: tuple[str, ...]) -> None:
            self.parameters.append(parameters)
            if self.fail:
                raise RuntimeError("database unavailable")

    store = object.__new__(PostgresStore)
    store._connection = TransactionConnection()
    transaction_observations: list[tuple[str, float]] = []
    advisory_observations: list[tuple[str, float]] = []
    monkeypatch.setattr(
        "app.postgres_store.record_postgres_transaction",
        lambda outcome, duration: transaction_observations.append((outcome, duration)),
    )
    monkeypatch.setattr(
        "app.postgres_store.record_postgres_advisory_lock_wait",
        lambda outcome, duration: advisory_observations.append((outcome, duration)),
    )

    clock = iter([20.0, 20.25, 30.0, 30.5, 40.0, 40.75, 50.0, 51.0])
    monkeypatch.setattr("app.postgres_store.perf_counter", lambda: next(clock))
    with store._transaction():
        pass
    with pytest.raises(RuntimeError, match="transaction failed"):
        with store._transaction():
            raise RuntimeError("transaction failed")

    cursor = AdvisoryCursor()
    store._acquire_advisory_lock(cursor, "private:user:run")
    cursor.fail = True
    with pytest.raises(RuntimeError, match="database unavailable"):
        store._acquire_advisory_lock(cursor, "private:user:run")

    assert transaction_observations == [("success", 0.25), ("error", 0.5)]
    assert advisory_observations == [("success", 0.75), ("error", 1.0)]
    assert cursor.parameters == [("private:user:run",), ("private:user:run",)]
