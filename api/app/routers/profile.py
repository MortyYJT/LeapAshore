from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import get_profile
from app.models.client import Profile
from app.schemas.profile import ProfileFields, ProfilePatch

router = APIRouter(prefix="/api/profile", tags=["profile"])


@router.get("", response_model=ProfileFields)
def read_profile(profile: Annotated[Profile, Depends(get_profile)]) -> Profile:
    return profile


@router.patch("", response_model=ProfileFields)
def update_profile(
    patch: ProfilePatch,
    profile: Annotated[Profile, Depends(get_profile)],
    session: Annotated[Session, Depends(get_session)],
) -> Profile:
    """Apply only the fields the caller actually sent, so a partial edit cannot blank the rest."""
    for name, value in patch.model_dump(exclude_unset=True).items():
        setattr(profile, name, value)
    session.commit()
    session.refresh(profile)
    return profile
