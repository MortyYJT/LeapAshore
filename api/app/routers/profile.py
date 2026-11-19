from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import get_subject, load_or_create_profile
from app.models.client import Profile
from app.schemas.profile import ProfileOut, ProfileUpdate
from app.services.versions import stale_response

router = APIRouter(prefix="/api/profile", tags=["profile"])


@router.get("", response_model=ProfileOut)
def read_profile(
    client_id: Annotated[str, Depends(get_subject)],
    session: Annotated[Session, Depends(get_session)],
) -> Profile:
    """Return the caller's profile, creating the subject on first contact.

    The subject is loaded or created here rather than in a dependency, so a request FastAPI rejects
    cannot leave a client and profile pair behind that no cookie can ever address. A `GET` has no
    body to reject, so this is only about staying consistent with the `PATCH` below; the cookie
    itself is still minted by `get_client_id`, which never touches the database.
    """
    return load_or_create_profile(session, client_id)


@router.patch("", response_model=ProfileOut)
def update_profile(
    patch: ProfileUpdate,
    client_id: Annotated[str, Depends(get_subject)],
    session: Annotated[Session, Depends(get_session)],
):
    """Apply only the fields the caller actually sent, so a partial edit cannot blank the rest.

    `patch` is validated before this function runs, so a body that fails validation returns 422 with
    the database untouched. That is the point of loading the subject in the body: a dependency would
    have committed the rows first, and because a 422 response carries no `Set-Cookie`, the applicant
    who triggered it could never reach them again. `ProfileFields` sets `extra="forbid"`, so one
    unexpected key was enough to leak a pair.

    The edit states the profile version it was based on (`baseVersion`). The row is locked before the
    two are compared, so of two devices saving at once exactly one is applied; the other gets 409 with
    the profile as it is stored, and nothing of its edit is written.
    """
    load_or_create_profile(session, client_id)
    profile = session.scalar(
        select(Profile)
        .where(Profile.client_id == client_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if patch.base_version != profile.version:
        return stale_response(ProfileOut.model_validate(profile).model_dump(by_alias=True, mode="json"))
    for name, value in patch.model_dump(exclude_unset=True, exclude={"base_version"}).items():
        setattr(profile, name, value)
    session.commit()
    session.refresh(profile)
    return profile
