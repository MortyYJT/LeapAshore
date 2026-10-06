import uuid
from typing import Annotated

from fastapi import Cookie, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.client import Client, Profile, new_client_id

COOKIE_NAME = "offerpilot_client"


def get_client_id(
    response: Response,
    offerpilot_client: Annotated[str | None, Cookie()] = None,
) -> str:
    """Resolve the anonymous subject id, minting one on the first request.

    An id that is not a well-formed uuid is replaced rather than trusted, so a malformed cookie can
    never address a row that belongs to someone else. A well-formed id is stored in its canonical
    spelling, since the column holds canonical text and another spelling of the same uuid would
    otherwise miss the row it names and start a second subject.

    This dependency reads a cookie and writes a response header; it deliberately does not touch the
    database. FastAPI resolves dependencies before it validates the request body, so a dependency
    that inserted and committed the subject left a `clients` and `profiles` pair behind for a
    request it then rejected with a 422 — and a 422 carries no `Set-Cookie`, so no browser could
    ever present the id that addresses those rows. The development database accumulated 221 such
    pairs, 184 of them with a null `school_name`, before this moved. `load_or_create_profile` does
    the writing instead, and the endpoints call it once FastAPI has accepted the request.
    """
    client_id = offerpilot_client
    if client_id:
        try:
            client_id = str(uuid.UUID(client_id))
        except ValueError:
            client_id = None

    if not client_id:
        client_id = new_client_id()

    response.set_cookie(
        COOKIE_NAME, client_id, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 365
    )
    return client_id


def load_or_create_profile(session: Session, client_id: str) -> Profile:
    """Return the caller's profile, creating the client and profile rows on first contact.

    First contact is an insert, so it cannot be "check, then insert": the loser of the insert would
    fail with a 500 on the primary key. The trigger is one cookie in flight twice, not two first
    contacts racing each other — a first contact cannot collide, because no cookie exists until a
    response has arrived. What does happen is the same cookie used concurrently: two connections or
    two tabs of one browser, a reloading or retrying proxy, a replayed request, or a cookie whose row
    was deleted between visits. Neither request needs a bug in the caller, and the browser cannot be
    relied on to serialise them.

    The insert therefore runs inside a savepoint whose `IntegrityError` is the second caller losing
    that race. Releasing the savepoint undoes only the failed insert, then the row is read back, which
    is the same answer the winner returns. The savepoint is used rather than an `ON CONFLICT` upsert
    because two different tables can collide here — whichever statement lost, `session.get` answers
    with the committed row afterwards.

    This is a plain function rather than a `Depends` on purpose: a dependency runs before FastAPI
    validates the request body, and the rows it creates for a rejected request are unreachable
    forever. A function called from the endpoint body runs after the body is valid, so an invalid
    request leaves the database untouched while a valid one still gets its subject exactly once.
    """
    if session.get(Client, client_id) is None:
        try:
            with session.begin_nested():
                session.add(Client(id=client_id))
                session.flush()
                session.add(Profile(client_id=client_id))
                session.commit()
        except IntegrityError:
            # Another request inserted this subject between the check and the insert.
            pass
    return session.get(Profile, client_id)
