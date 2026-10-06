"""First contact under concurrency.

One subject cookie can be in flight twice: two connections of the same browser, a reloading proxy, a
replayed request, or a cookie whose row was deleted between visits. Both requests then reach the "no
client row yet" branch, and the loser of the insert used to fail with a 500 on the `clients` primary
key. This test forces that collision instead of racing the scheduler: it holds both requests until
each has read its client row as missing, so the bare check-then-insert fails every time.
"""

import contextvars
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

# Which request a lookup belongs to. Set once per request by `TagTheRequest` and copied into
# whichever worker thread that request's synchronous code runs on, so the barrier can tell two
# lookups made by one request from one lookup made by each of two.
REQUEST: contextvars.ContextVar[Any] = contextvars.ContextVar("race_barrier_request", default=None)


class TagTheRequest:
    """Wrap the app so every request carries an identity of its own.

    The barrier has to count arrivals per request, and a lookup cannot say which request it belongs
    to. Counting lookups instead is only correct while each request makes exactly one. `get_profile`
    looks the client row up once today, so a second lookup added later — a new dependency, or a
    re-read before the insert — would let one request move the counter twice, releasing the barrier
    while the other request is still outside the window. The token rides in the request's context,
    which `to_thread` copies into the threadpool, so the request stays recognisable even though its
    synchronous dependencies run on threads the request does not own.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self._inner(scope, receive, send)
            return
        token = REQUEST.set(object())
        try:
            await self._inner(scope, receive, send)
        finally:
            REQUEST.reset(token)


TAGGED_APP = TagTheRequest(app)


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
        self.arrivals: list[Any] = []

    def lookup(self, original: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(session: Session, entity: Any, ident: Any, *args: Any, **kwargs: Any) -> Any:
            found = original(session, entity, ident, *args, **kwargs)
            if entity is Client and self.arrive():
                self._release.wait(timeout=PATIENCE_SECONDS)
            return found

        return wrapper

    def arrive(self) -> bool:
        """Record this request at the window, and report whether it is the request's first arrival.

        The second half of that is what keeps the barrier about requests: a request that reads its
        client row twice has still arrived once, so it cannot be the second arrival on its own.
        """
        request = REQUEST.get()
        with self._state:
            first = request not in self.arrivals
            if first:
                self.arrivals.append(request)
                self._state.notify_all()
        return first

    def wait_for_both_requests(self) -> bool:
        """Release the requests once both have read their client row as missing."""
        with self._state:
            held = self._state.wait_for(lambda: len(self.arrivals) >= BOTH_ARRIVED, PATIENCE_SECONDS)
        if held:
            self._release.set()
        return held


def ask(client_id: str) -> tuple[int, dict[str, Any]]:
    client = TestClient(TAGGED_APP)
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

    assert both_checked, f"only {len(held.arrivals)} request(s) reached the window"
    statuses = [status for status, _ in results]
    assert statuses == [200, 200], f"a first contact failed: {results}"

    with SessionLocal() as session:
        rows = session.query(Client).filter(Client.id == client_id).all()
    assert len(rows) == 1
