"""First contact under concurrency.

One subject cookie can be in flight twice: two connections of the same browser, a reloading proxy, a
replayed request, or a cookie whose row was deleted between visits. Both requests then reach the "no
client row yet" branch, and the loser of the insert used to fail with a 500 on the `clients` primary
key. This test forces that collision instead of racing the scheduler: it holds both requests until
each has read its client row as missing, so the bare check-then-insert fails every time.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.main import app
from app.models.client import Client, new_client_id

COOKIE = "offerpilot_client"
BOTH_ARRIVED = 2
# Long enough that a slow machine still reaches the window, short enough that a request which never
# does fails the test instead of hanging the suite.
PATIENCE_SECONDS = 10


class HoldAfterTheCheck:
    """Hold each request between its "is there a client row?" check and the insert that follows it.

    Patching the client lookup is what makes the collision certain rather than hoped for. A barrier
    anywhere earlier — in the cookie dependency, where the first version of this test put it — only
    lines the two requests up; each then free-runs its own check, so a request that arrives after the
    winner's commit reads the row, skips the insert, and the test passes without reproducing
    anything. Waiting after the check means both requests have already read "missing" before either
    one inserts.

    The two halves cannot be the same call: the request that loses the insert raises before it ever
    reads its profile, so the profile lookup must stay unpatched or the winner would wait forever.
    """

    def __init__(self) -> None:
        self._state = threading.Condition()
        self._release = threading.Event()
        self.lookups: list[Any] = []

    def lookup(self, original: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(session: Session, entity: Any, ident: Any, *args: Any, **kwargs: Any) -> Any:
            found = original(session, entity, ident, *args, **kwargs)
            if entity is Client:
                with self._state:
                    self.lookups.append(ident)
                    self._state.notify_all()
                self._release.wait(timeout=PATIENCE_SECONDS)
            return found

        return wrapper

    def wait_for_both_requests(self) -> bool:
        """Release the requests once both have read their client row as missing."""
        with self._state:
            held = self._state.wait_for(lambda: len(self.lookups) >= BOTH_ARRIVED, PATIENCE_SECONDS)
        if held:
            self._release.set()
        return held


def ask(client_id: str) -> tuple[int, dict[str, Any]]:
    client = TestClient(app)
    client.cookies.set(COOKIE, client_id)
    response = client.get("/api/profile")
    return response.status_code, response.json()


def test_two_concurrent_first_contacts_share_one_client_row(require_db):
    """Both requests must be answered, and the client row must be created exactly once."""
    client_id = new_client_id()
    held = HoldAfterTheCheck()

    with (
        patch.object(Session, "get", held.lookup(Session.get)),
        ThreadPoolExecutor(max_workers=BOTH_ARRIVED) as pool,
    ):
        futures = [pool.submit(ask, client_id) for _ in range(BOTH_ARRIVED)]
        both_checked = held.wait_for_both_requests()
        results = [future.result() for future in futures]

    assert both_checked, f"only {len(held.lookups)} request(s) reached the race window"
    statuses = [status for status, _ in results]
    assert statuses == [200, 200], f"a first contact failed: {results}"

    with SessionLocal() as session:
        rows = session.query(Client).filter(Client.id == client_id).all()
    assert len(rows) == 1
