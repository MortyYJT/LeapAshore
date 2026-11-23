"""Reading and writing one applicant's application records.

A record is what 「我的申请」 lists: a catalogue program the applicant chose (a portfolio row, plus an
overlay once they have edited it) or an application they entered by hand. Two callers write them, the
HTTP routes (`app.routers.application_records`) and the advisor's confirmed changes
(`app.agent.application_tools`), and both come through here, so a rule is stated once: what a payload
may carry, which version an edit must be based on, when a date stops counting as checked.

A record's materials (`docs/product/PRD-multi-device.md`, 3.7) are two lists. `materials` is what the
catalogue collected from the program's official page, each entry with the applicant's own tick;
`customMaterials` is the applicant's own checklist, which every record has and which is all a record
has when it was added by hand or its program's page has not been read yet (`materialsExtracted` false).
A tick is the applicant saying "I have this ready"; nothing here reviews a document. It is stored with
a digest of the requirement it was given for, so when the page's requirement changes the tick stops
counting and the entry reads `changed`. For the same reason a tick must say which wording it is for
(`materialBasis`, the entry's `digest` as the caller read it): the record's version does not move when
the catalogue is imported again, so without it a page opened before the import could tick a
requirement its reader never saw. A tick for another wording is refused like any stale edit.

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

from app.collect import materials as material_rules
from app.deps import load_or_create_profile
from app.models.application import Application, ApplicationOrigin, ApplicationStatus, ApplicationTier
from app.models.application_plan import ApplicationPlan
from app.models.program import Program, ProgramMaterial
from app.models.source import Source, SourceVersion
from app.routers.applications import read_applications
from app.schemas.common import _camel
from app.models.task import TaskOrigin
from app.services.accounts import lock_client
from app.services.applications import _snapshot as portfolio_snapshot
from app.services.versions import StaleVersion, token_of
from app.services.writes import write_history

NOT_FOUND = "申请项目不存在"

# Where a record's deadline came from: the catalogue's collected page, or the applicant's own entry.
COLLECTED, ENTERED = "collected", "entered"


class RecordNotFound(LookupError):
    """The key names no record of this subject (another subject's record reads the same)."""

    def __init__(self) -> None:
        super().__init__(NOT_FOUND)


class ProgramNotFound(LookupError):
    """The catalogue holds no program with this id."""

    def __init__(self) -> None:
        super().__init__("学校库里没有这个项目")


class InvalidRecord(ValueError):
    """An edit the record cannot take, with the reason in the message."""


# How many lines of their own an applicant's checklist holds, and how many ticks one edit carries.
CUSTOM_LIMIT = 40
TICK_LIMIT = 60
# The applicant's earlier whole-application tick, carried over by the migration as a line of their own.
LEGACY_ITEM_ID = "legacy-all"


class CustomMaterial(BaseModel):
    """One line of the applicant's own checklist. The id is made by whoever adds the line; the `c-`
    prefix keeps it apart from the catalogue's material keys, so one name never means two things."""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^(c-[A-Za-z0-9_-]{1,36}|legacy-all)$")
    label: str = Field(min_length=1, max_length=200)
    done: bool = False

    @field_validator("label")
    @classmethod
    def named(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("材料名称不能为空")
        return value.strip()


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
    # Ticks to set (true) or clear (false) on the catalogue's materials, by key; keys left out keep
    # their state. The checklist of the applicant's own lines is replaced as a whole when sent.
    material_ticks: dict[str, bool] = Field(default_factory=dict, max_length=TICK_LIMIT)
    # For every tick being set: the digest of the requirement as the caller read it (`materials[].digest`).
    material_basis: dict[str, str] = Field(default_factory=dict, max_length=TICK_LIMIT)
    custom_materials: list[CustomMaterial] | None = Field(None, max_length=CUSTOM_LIMIT)
    material_notes: str = Field("", max_length=10000)

    @field_validator("custom_materials")
    @classmethod
    def distinct_lines(cls, value):
        if value is not None and len({item.id for item in value}) != len(value):
            raise ValueError("清单里有重复的条目")
        return value

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


def catalogue_materials(session: Session, program_ids) -> dict[str, tuple[bool, list[ProgramMaterial], str | None]]:
    """For each program: whether its page has been read for materials, the entries collected, and the
    page the materials were read from.

    The page is served with the record because a program read and found to list no documents has no
    entry to carry a source, and the applicant is then sent to the page itself. It is given only when
    the catalogue holds the very snapshot the materials were read from as a version of the program's
    source: a program's source can also be a register that lists it (the CRICOS dataset), which is not
    a page to check for documents, and such a source has no version with that snapshot.
    """
    ids = [pid for pid in dict.fromkeys(program_ids) if pid]
    if not ids:
        return {}
    page_read = (
        select(Source.url).join(SourceVersion, SourceVersion.source_id == Source.id)
        .where(Source.id == Program.source_id, SourceVersion.content_sha256 == Program.materials_snapshot_sha256)
        .limit(1).correlate(Program).scalar_subquery()
    )
    known = {pid: (sha, url) for pid, sha, url in session.execute(
        select(Program.id, Program.materials_snapshot_sha256, page_read).where(Program.id.in_(ids))
    )}
    read = {pid for pid, (sha, _url) in known.items() if sha is not None}
    rows: dict[str, list[ProgramMaterial]] = {}
    query = (select(ProgramMaterial).where(ProgramMaterial.program_id.in_(read))
             .order_by(ProgramMaterial.program_id, ProgramMaterial.sort_order)) if read else None
    for row in session.scalars(query) if query is not None else []:
        rows.setdefault(row.program_id, []).append(row)
    return {pid: (pid in read, rows.get(pid, []), known[pid][1] if pid in known else None) for pid in ids}


def _digest(row: ProgramMaterial) -> str:
    return material_rules.digest(row.type, row.count, row.note, row.quote)


def materials_view(plan, catalogue=None) -> dict:
    """The record's two material lists and the counts drawn from them."""
    extracted, rows, page = catalogue or (False, [], None)
    ticks = (plan.material_ticks if plan else None) or {}
    items = []
    for row in rows:
        held = ticks.get(row.key)
        items.append(dict(
            key=row.key, type=row.type, count=row.count, note=row.note, quote=row.quote, sourceUrl=row.source_url,
            # The requirement as it reads now; a tick is sent back with it (`materialBasis`).
            digest=_digest(row),
            ready=held == _digest(row),
            # Ticked for an earlier wording of this requirement: not ready, and worth a second look.
            changed=held is not None and held != _digest(row),
        ))
    custom = [
        dict(id=str(item.get("id")), label=str(item.get("label") or ""), done=bool(item.get("done")))
        for item in ((plan.custom_materials if plan else None) or [])
        if isinstance(item, dict)
    ]
    done = sum(item["ready"] for item in items) + sum(item["done"] for item in custom)
    total = len(items) + len(custom)
    return dict(
        materials=items,
        materialsExtracted=extracted,
        # The page the materials were read from, when the catalogue holds that snapshot; else None.
        materialsPageUrl=page,
        customMaterials=custom,
        materialsDone=done,
        materialsTotal=total,
        # Every listed line ticked. A record with no line at all has nothing ticked, so it is not ready.
        materialsReady=total > 0 and done == total,
    )


def view(plan, selection=None, catalogue=None):
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
        **materials_view(plan, catalogue),
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
    chosen = selections(session, client_id)
    collected = catalogue_materials(session, chosen)
    return [
        view(overlays.get(key), row, collected.get(key))
        for key, row in chosen.items()
    ] + [view(p) for p in plans if not p.catalog_program_id]


class RequirementMoved(Exception):
    """A tick was sent for a wording of a requirement that the catalogue no longer holds."""


def _apply_materials(plan, payload, catalogue) -> None:
    fields = payload.model_fields_set
    if "material_ticks" in fields and payload.material_ticks:
        if catalogue is None:
            raise InvalidRecord("手动添加的申请没有学校库的材料清单，请在自己的清单里勾选")
        _extracted, rows, _page = catalogue
        by_key = {row.key: row for row in rows}
        # Ticks on entries the catalogue no longer lists are dropped with the first edit after.
        ticks = {key: held for key, held in (plan.material_ticks or {}).items() if key in by_key}
        for key, wanted in payload.material_ticks.items():
            row = by_key.get(key)
            if row is None:
                raise InvalidRecord(f"学校库里这个项目没有「{key[:48]}」这项材料，没有可以勾的")
            if not wanted:
                ticks.pop(key, None)
                continue
            seen = payload.material_basis.get(key)
            if not seen:
                raise InvalidRecord("勾选一项材料时要带上所看到的那条要求（materialBasis）")
            if seen != _digest(row):
                # The catalogue was imported again after the caller read the record: the applicant
                # ticked a requirement that now reads differently.
                raise RequirementMoved
            ticks[key] = seen
        plan.material_ticks = ticks
    if "custom_materials" in fields and payload.custom_materials is not None:
        plan.custom_materials = [item.model_dump() for item in payload.custom_materials]


def apply_patch(plan, payload, catalogue=None):
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
        "material_notes",
    ):
        if key in fields:
            setattr(plan, key, getattr(payload, key))
    _apply_materials(plan, payload, catalogue)
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


def _same_text(a: str, b: str) -> bool:
    return "".join(a.casefold().split()) == "".join(b.casefold().split())


def same_named(session: Session, client_id: str, payload: RecordCreate) -> bool:
    """Whether the subject already has a record with this school and name, whatever the case and spacing."""
    return any(
        _same_text(row["school"], payload.school) and _same_text(row["name"], payload.name)
        for row in read_records(client_id, session)
    )


def create_record(
    session: Session, client_id: str, payload: RecordCreate, create_key: str, *, unless_same_named: bool = False
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
    if unless_same_named and same_named(session, client_id, payload):
        # The advisor's rule, not the form's: checked here, under the lock, so two cards for the same
        # program confirmed together add one record.
        raise InvalidRecord("已经有同名的申请")
    plan = ApplicationPlan(
        id=str(uuid4()),
        client_id=client_id,
        school=payload.school,
        name=payload.name,
        status="considering",
        deadline_override=False,
        materials_ready=False,
        material_notes="",
        material_ticks={},
        custom_materials=[],
        create_key=create_key,
    )
    apply_patch(plan, payload)
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return view(plan), True


class CatalogueAdd(BaseModel):
    """One catalogue program to add to the applicant's applications, from the school library."""

    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True, extra="forbid")
    program_id: str = Field(min_length=1, max_length=64)
    # The band to store: the one the tiers gave against the applicant's background, or the caller's
    # stand-in when they gave none, which it then flags with `needs_review` (shown as 未经系统分档,
    # as the portfolio flags a band the applicant picked). Without a band the row is 稳 and flagged.
    tier: ApplicationTier | None = None
    needs_review: bool | None = None


# The band a program is stored with when the caller states none.
UNTIERED_BAND = ApplicationTier.MATCH


def add_catalogue_program(
    session: Session, client_id: str, payload: CatalogueAdd
) -> tuple[dict, bool]:
    """Add a catalogue program to the applicant's applications in one step; returns the record and
    whether this call added it.

    The record is the program's portfolio row (`applications`), the same row the portfolio's confirm
    and the advisor write, so it shows on the portfolio, 我的申请, the overview and the roadmap at
    once. Nothing else is stored: the deadline the record shows is read from the catalogue each time
    (`view`), with its page as the source and marked as collected and unchecked, and a program with
    no collected date shows none. No date is made up here.

    The call is idempotent by program: a program the applicant already holds is answered with its
    record as it is stored, and nothing is written, so a double click, a retry after a lost answer or
    a second tab adds one row. The subject's row is locked first, as every writer of these rows does,
    and `UNIQUE (client_id, program_id)` states the same rule in the table.
    """
    load_or_create_profile(session, client_id)
    lock_client(session, client_id)
    if session.get(Program, payload.program_id) is None:
        raise ProgramNotFound
    stored = session.scalar(
        select(Application).where(
            Application.client_id == client_id, Application.program_id == payload.program_id
        )
    )
    key = f"catalog:{payload.program_id}"
    if stored is not None:
        return read_record(session, client_id, key), False
    row = Application(
        id=str(uuid4()),
        client_id=client_id,
        program_id=payload.program_id,
        tier=(payload.tier or UNTIERED_BAND).value,
        status=ApplicationStatus.CONSIDERING.value,
        is_primary=False,
        needs_review=payload.tier is None if payload.needs_review is None else payload.needs_review,
        origin=ApplicationOrigin.USER.value,
    )
    session.add(row)
    session.flush()
    write_history(
        session, client_id, "created", None, portfolio_snapshot(row),
        actor=TaskOrigin.USER, application_id=row.id,
    )
    session.commit()
    return read_record(session, client_id, key), True


def current_view(plan, selection, client_id, session):
    """The record as the read serves it, for a row pair `resolve` returned."""
    if selection is None:
        return view(plan)
    collected = catalogue_materials(session, [selection.program_id])
    return view(plan, selections(session, client_id).get(selection.program_id), collected.get(selection.program_id))


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
            material_ticks={},
            custom_materials=[],
        )
        session.add(plan)
    collected = catalogue_materials(session, [selection.program_id]) if selection else {}
    try:
        apply_patch(plan, payload, collected.get(selection.program_id) if selection else None)
    except RequirementMoved:
        # Answered as a stale edit, with the record as it reads now: nothing is written, and the
        # caller shows the applicant the requirement as it is before they tick it.
        session.rollback()
        raise StaleVersion(read_record(session, client_id, key)) from None
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
