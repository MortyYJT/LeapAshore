"""First contact under concurrency.

Two requests can carry the same fresh cookie: the mount effect and a second tab or a reload can fire
at the same moment, and any shared cache or proxy can replay one. Both then reach the "no client row
yet" branch, and the loser of the insert used to fail with a 500 on the `clients` primary key. This
test reproduces that collision deterministically instead of racing the scheduler, so it fails every
time the bare check-then-insert returns.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.deps import get_client_id
from app.main import app
from app.models.client import Client, new_client_id

COOKIE = "offerpilot_client"
# The barrier needs both threads; the test would hang rather than pass if only one ever arrived.
BOTH_ARRIVED = 2


class FirstContactBarrier:
    """A dependency that holds the first two concurrent requests at the race window.

    Installed in place of `get_client_id`, so both requests have already decided that their client
    row is missing by the time either one tries to insert it. The wait is bounded: a request that
    arrives alone still gets an answer instead of hanging the suite.
    """

    def __init__(self) -> None:
        self.client_id = new_client_id()
        self.barrier = threading.Barrier(BOTH_ARRIVED, timeout=10)

    def __call__(self) -> str:
        self.barrier.wait()
        return self.client_id


def ask(client_id: str) -> tuple[int, dict[str, Any]]:
    client = TestClient(app)
    client.cookies.set(COOKIE, client_id)
    response = client.get("/api/profile")
    return response.status_code, response.json()


def test_two_concurrent_first_contacts_share_one_client_row(require_db):
    """Both requests must be answered, and the client row must be created exactly once."""
    barrier = FirstContactBarrier()
    app.dependency_overrides[get_client_id] = barrier

    try:
        with ThreadPoolExecutor(max_workers=BOTH_ARRIVED) as pool:
            results = list(pool.map(lambda _: ask(barrier.client_id), range(BOTH_ARRIVED)))
    finally:
        app.dependency_overrides.clear()

    statuses = [status for status, _ in results]
    assert statuses == [200, 200], f"a first contact failed: {results}"

    with SessionLocal() as session:
        rows = session.query(Client).filter(Client.id == barrier.client_id).all()
    assert len(rows) == 1
