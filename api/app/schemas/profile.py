"""The profile schema, and with it the contract the frontend reads.

`web/lib/types.ts` is the other half of that contract: every key here has to match the field the
frontend reads, because Task 8 hands the response body straight to the `Profile` type.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import _camel


class ProfileFields(BaseModel):
    """Mirrors ProfileView's fields. Aliases keep the wire format camelCase like the frontend."""

    model_config = ConfigDict(
        alias_generator=_camel,
        populate_by_name=True,
        from_attributes=True,
        extra="forbid",
    )

    # Two columns are named for the database rather than for the frontend: the row spells them
    # `current_education_level` and `target_degree_level`, while `web/lib/types.ts` reads
    # `educationLevel` and `targetDegree`. The alias_generator alone would answer
    # `currentEducationLevel` / `targetDegreeLevel` and the UI would show both fields empty, so the
    # explicit aliases below restore the frontend names. Field names stay identical to the ORM
    # attributes, which is what lets the router `setattr` a patch straight onto the row.
    current_education_level: str | None = Field(default=None, alias="educationLevel")
    school_origin: str | None = None
    school_name: str | None = None
    domestic_tier: str | None = None
    overseas_band: str | None = None
    major: str | None = None
    gpa_score: float | None = None
    gpa_scale: float | None = None
    target_degree_level: str | None = Field(default=None, alias="targetDegree")
    target_field: str | None = None
    intake: str | None = None
    english_score: str | None = None
    annual_budget_cny: float | None = None


class ProfilePatch(ProfileFields):
    """Every field optional. `extra="forbid"` inherited from ProfileFields rejects typos."""
