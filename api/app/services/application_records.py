"""Reading and writing one applicant's application records.

A record is what 「我的申请」 lists: a catalogue program the applicant chose (a portfolio row, plus an
overlay once they have edited it) or an application they entered by hand. Two callers write them, the
HTTP routes (`app.routers.application_records`) and the advisor's confirmed changes
(`app.agent.application_tools`), and both come through here, so a rule is stated once: what a payload
may carry, which version an edit must be based on, when a date stops counting as checked.

A refusal is an exception the caller words for its own reader: `RecordNotFound`, `InvalidRecord`
(the message is the reason) and `StaleVersion` with the record as it is stored.
"""

from datetime import UTC, date, datetime
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import load_or_create_profile
from app.models.application import Application, ApplicationStatus
from app.models.application_plan import ApplicationPlan
from app.routers.applications import read_applications
from app.schemas.common import _camel
from app.services.accounts import lock_client
from app.services.versions import StaleVersion, token_of

NOT_FOUND = "申请项目不存在"

# Where a record's deadline came from: the catalogue's collected page, or the applicant's own entry.
COLLECTED, ENTERED = "collected", "entered"


class RecordNotFound(LookupError):
    """The key names no record of this subject (another subject's record reads the same)."""

    def __init__(self) -> None:
        super().__init__(NOT_FOUND)


class InvalidRecord(ValueError):
    """An edit the record cannot take, with the reason in the message."""


class RecordFields(BaseModel):
    model_config = ConfigDict(
        alias_generator=_camel, populate_by_name=True, extra="forbid"
    )
    school: str | None = Field(None, max_length=200)
    name: str | None = Field(None, max_length=300)
    round: str | None = Field(None, max_length=120)
    status: ApplicationStatus | None = None
    deadline: date | None = None
    source_url: str | None = Field(None, max_length=2000)
    confirm_deadline: bool = False
    materials_ready: bool = False
    material_notes: str = Field("", max_length=10000)

    @model_validator(mode="after")
    def non_null_status(self):
        if "status" in self.model_fields_set and self.status is None:
            raise ValueError("申请状态不能为空")
        return self

    @field_validator("source_url")
    @classmethod
    def safe_url(cls, value):
        if not value:
            return None
        parts = urlsplit(value)
        if (
            parts.scheme not in ("http", "https")
            or not parts.hostname
            or parts.username
            or parts.password
        ):
            raise ValueError("来源必须是 HTTP(S) 网页地址")
        return value

    @field_validator("school", "name")
    @classmethod
    def required_names(cls, value):
        if value is None or not value.strip():
            raise ValueError("学校和项目名称不能为空")
        return value.strip()


class RecordPatch(RecordFields):
    # The record version this edit was based on, as the read served it. An edit based on a version
    # the server no longer holds is refused and answered with the record as it is stored.
    base_version: str = Field(min_length=1, max_length=64)


class RecordCreate(RecordFields):
    school: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def complete_confirmation(self):
        if self.confirm_deadline and (not self.deadline or not self.source_url):
            raise ValueError("确认日期需要截止日期与来源")
        return self


def _is_the_catalogue_s(program, deadline, source) -> bool:
    """Whether this date, with this source, is one the catalogue holds for the program."""
    if program is None or deadline is None or not source:
        return False
    return any(d.date == deadline and d.source_url == source for d in program.deadlines)


def view(plan, selection=None):
    catalog = selection is not None
    deadline, source = (None, None)
    origin = None
    if catalog:
        if selection.official_deadline and selection.deadline_source_url:
            deadline, source = (
                selection.official_deadline,
                selection.deadline_source_url,
            )
            origin = ENTERED
        else:
            dates = sorted(
                selection.program.deadlines if selection.program else [],
                key=lambda d: d.date,
            )
            today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
            chosen = next(
                (d for d in dates if d.date >= today), dates[-1] if dates else None
            )
            if chosen:
                deadline, source, origin = chosen.date, chosen.source_url, COLLECTED
    if plan and (not catalog or plan.deadline_override):
        deadline, source, origin = plan.deadline, plan.source_url, ENTERED
    # A stored date that is one of the catalogue's own for this program, with the catalogue's source,
    # is the collected date whoever picked it (the applicant in the form, or the advisor with their
    # confirm): it reads as collected and unchecked, not as something the applicant looked up.
    if catalog and origin == ENTERED and _is_the_catalogue_s(selection.program, deadline, source):
        origin = COLLECTED
    program = selection.program if catalog else None
    return dict(
        id=f"catalog:{selection.program_id}" if catalog else plan.id,
        programId=selection.program_id if catalog else None,
        school=program.university if program else (plan.school if plan else "未知学校"),
        name=(
            (program.name_en or program.name)
            if program
            else (plan.name if plan else "未知项目")
        ),
        round=plan.round if plan else None,
        status=selection.status if catalog else plan.status,
        deadline=deadline,
        sourceUrl=source,
        deadlineOrigin=origin,
        checkedAt=plan.checked_at if plan else None,
        materialsReady=plan.materials_ready if plan else False,
        materialNotes=plan.material_notes if plan else "",
        # A catalogue record is read from the portfolio row and, once edited, its overlay; a change to
        # either moves the version. A manual record is its plan alone.
        version=token_of(selection, plan) if catalog else token_of(plan),
    )


def selections(session, client_id):
    return {row.program_id: row for row in read_applications(client_id, session)}


def read_records(client_id: str, session: Session) -> list[dict]:
    plans = list(
        session.scalars(
            select(ApplicationPlan).where(ApplicationPlan.client_id == client_id)
        )
    )
    overlays = {p.catalog_program_id: p for p in plans if p.catalog_program_id}
    return [
        view(overlays.get(key), row)
        for key, row in selections(session, client_id).items()
    ] + [view(p) for p in plans if not p.catalog_program_id]


def apply_patch(plan, payload):
    fields = payload.model_fields_set
    changed = any(
        getattr(plan, key) != getattr(payload, key)
        for key in ("deadline", "source_url", "round")
        if key in fields
    )
    if changed:
        plan.checked_at = None
    for key in (
        "school",
        "name",
        "round",
        "deadline",
        "source_url",
        "materials_ready",
        "material_notes",
    ):
        if key in fields:
            setattr(plan, key, getattr(payload, key))
    if "status" in fields:
        if payload.status is None:
            raise InvalidRecord("申请状态不能为空")
        plan.status = payload.status.value
    if {"deadline", "source_url"} & fields:
        plan.deadline_override = True
    if payload.confirm_deadline:
        if not plan.deadline or not plan.source_url:
            raise InvalidRecord("请先填写截止日期和来源链接，再确认核对")
        plan.deadline_override = True
        plan.checked_at = datetime.now(UTC)


def find_created(session: Session, client_id: str, create_key: str) -> ApplicationPlan | None:
    """The manual record a create request with this key made, if it has run."""
    return session.scalar(
        select(ApplicationPlan).where(
            ApplicationPlan.client_id == client_id,
            ApplicationPlan.create_key == create_key,
        )
    )


def create_record(
    session: Session, client_id: str, payload: RecordCreate, create_key: str
) -> tuple[dict, bool]:
    """Create a manual application once per key; returns the record and whether this call made it.

    The caller makes one key per record it intends to create and sends it again when it retries. The
    first call creates the record; a call carrying a key this subject has already used returns that
    record as it is stored now and writes nothing. A replay never applies its payload, so a late
    duplicate of the create cannot undo an edit made after it.

    The subject's row is locked first, as the update and delete do, so two calls with one key that
    arrive together are handled one after the other and the second finds the first's row. The unique
    constraint on `(client_id, create_key)` states the same rule in the table.
    """
    load_or_create_profile(session, client_id)
    lock_client(session, client_id)
    existing = find_created(session, client_id, create_key)
    if existing is not None:
        return view(existing), False
    plan = ApplicationPlan(
        id=str(uuid4()),
        client_id=client_id,
        school=payload.school,
        name=payload.name,
        status="considering",
        deadline_override=False,
        materials_ready=False,
        material_notes="",
        create_key=create_key,
    )
    apply_patch(plan, payload)
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return view(plan), True


def current_view(plan, selection, client_id, session):
    """The record as the read serves it, for a row pair `resolve` returned."""
    if selection is None:
        return view(plan)
    return view(plan, selections(session, client_id).get(selection.program_id))


def resolve(key, client_id, session):
    if key.startswith("catalog:"):
        program_id = key.removeprefix("catalog:")
        selection = session.scalar(
            select(Application).where(
                Application.client_id == client_id, Application.program_id == program_id
            )
        )
        if not selection:
            raise RecordNotFound
        plan = session.scalar(
            select(ApplicationPlan).where(
                ApplicationPlan.client_id == client_id,
                ApplicationPlan.catalog_program_id == program_id,
            )
        )
        return plan, selection
    plan = session.scalar(
        select(ApplicationPlan).where(
            ApplicationPlan.client_id == client_id,
            ApplicationPlan.id == key,
            ApplicationPlan.catalog_program_id.is_(None),
        )
    )
    if not plan:
        raise RecordNotFound
    return plan, None


def read_record(session: Session, client_id: str, key: str) -> dict:
    """One record of this subject as the read serves it; `RecordNotFound` for anyone else's."""
    plan, selection = resolve(key, client_id, session)
    return current_view(plan, selection, client_id, session)


def update_record(session: Session, client_id: str, key: str, payload: RecordPatch) -> dict:
    """Apply an edit based on the stored version, and return the record as it then reads.

    The subject's row is held until the commit, and every writer of these rows takes it first, so the
    version read here is still the stored one when the edit is written. An edit based on any other
    version raises `StaleVersion` with the record as it is stored, and writes nothing.
    """
    lock_client(session, client_id)
    plan, selection = resolve(key, client_id, session)
    current = current_view(plan, selection, client_id, session)
    if payload.base_version != current["version"]:
        raise StaleVersion(current)
    if selection and {"school", "name"} & payload.model_fields_set:
        raise InvalidRecord("学校库项目名称请在学校库查看")
    if plan is None:
        served = selections(session, client_id)[selection.program_id]
        initial = view(None, served)
        plan = ApplicationPlan(
            id=str(uuid4()),
            client_id=client_id,
            catalog_program_id=selection.program_id,
            school="",
            name="",
            status=selection.status,
            deadline_override=False,
            deadline=initial["deadline"],
            source_url=initial["sourceUrl"],
            materials_ready=False,
            material_notes="",
        )
        session.add(plan)
    apply_patch(plan, payload)
    if selection:
        if "status" in payload.model_fields_set:
            selection.status = plan.status
        if {"deadline", "source_url"} & payload.model_fields_set:
            selection.official_deadline, selection.deadline_source_url = (
                plan.deadline,
                plan.source_url,
            )
    session.commit()
    session.refresh(plan)
    if selection:
        session.refresh(selection)
    return current_view(plan, selection, client_id, session)


def delete_record(session: Session, client_id: str, key: str, base_version: str) -> None:
    """Remove a record the caller has seen in its current state.

    A removal states the version it was based on like any other change: removing a record another
    device has just edited would discard that edit unseen, so it raises `StaleVersion` with the record
    as it is stored, and the applicant removes it again once they have seen it.
    """
    lock_client(session, client_id)
    plan, selection = resolve(key, client_id, session)
    current = current_view(plan, selection, client_id, session)
    if base_version != current["version"]:
        raise StaleVersion(current)
    if plan:
        session.delete(plan)
    if selection:
        session.delete(selection)
    session.commit()
