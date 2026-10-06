import uuid
from typing import Annotated

from fastapi import Cookie, Depends, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_session
from app.models.client import Client, Profile, new_client_id

COOKIE_NAME = "offerpilot_client"


def get_client_id(
    response: Response,
    offerpilot_client: Annotated[str | None, Cookie()] = None,
) -> str:
    """Resolve the anonymous subject, minting one on the first request.

    An id that is not a well-formed uuid is replaced rather than trusted, so a malformed cookie can
    never address a row that belongs to someone else. A well-formed id is stored in its canonical
    spelling, since the column holds canonical text and another spelling of the same uuid would
    otherwise miss the row it names and start a second subject.
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


def get_profile(
    client_id: Annotated[str, Depends(get_client_id)],
    session: Annotated[Session, Depends(get_session)],
) -> Profile:
    """Return the caller's profile, creating the client and profile rows on first contact.

    First contact is an insert, so it cannot be "check, then insert": two requests carrying the same
    cookie both find no row, and the loser of the insert would fail with a 500 on the primary key.
    That is reachable without a bug in the caller — a browser fires the mount read while a reload or
    a second tab is arriving, and any shared cache or proxy can replay one request into two.

    The insert therefore runs inside a savepoint whose `IntegrityError` is the second caller losing
    that race. Releasing the savepoint undoes only the failed insert, then the row is read back, which
    is the same answer the winner returns. The savepoint is used rather than an `ON CONFLICT` upsert
    because two different tables can collide here — whichever statement lost, `session.get` answers
    with the committed row afterwards.
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
