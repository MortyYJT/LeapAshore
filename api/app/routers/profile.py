from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import get_client_id, load_or_create_profile
from app.models.client import Profile
from app.schemas.profile import ProfileFields, ProfilePatch

router = APIRouter(prefix="/api/profile", tags=["profile"])


@router.get("", response_model=ProfileFields)
def read_profile(
    client_id: Annotated[str, Depends(get_client_id)],
    session: Annotated[Session, Depends(get_session)],
) -> Profile:
    """Return the caller's profile, creating the subject on first contact.

    The subject is loaded or created here rather than in a dependency, so a request FastAPI rejects
    cannot leave a client and profile pair behind that no cookie can ever address. A `GET` has no
    body to reject, so this is only about staying consistent with the `PATCH` below; the cookie
    itself is still minted by `get_client_id`, which never touches the database.
    """
    return load_or_create_profile(session, client_id)


@router.patch("", response_model=ProfileFields)
def update_profile(
    patch: ProfilePatch,
    client_id: Annotated[str, Depends(get_client_id)],
    session: Annotated[Session, Depends(get_session)],
) -> Profile:
    """Apply only the fields the caller actually sent, so a partial edit cannot blank the rest.

    `patch` is validated before this function runs, so a body that fails validation returns 422 with
    the database untouched. That is the point of loading the subject in the body: a dependency would
    have committed the rows first, and because a 422 response carries no `Set-Cookie`, the applicant
    who triggered it could never reach them again. `ProfileFields` sets `extra="forbid"`, so one
    unexpected key was enough to leak a pair.
    """
    profile = load_or_create_profile(session, client_id)
    for name, value in patch.model_dump(exclude_unset=True).items():
        setattr(profile, name, value)
    session.commit()
    session.refresh(profile)
    return profile
