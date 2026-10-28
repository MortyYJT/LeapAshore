"""Seed the program catalogue from the CRICOS extract, and fold the old placeholder slugs.

Every CRICOS master's (coursework) course becomes a `programs` row with the id `cricos-<code>`. The
extract states what a course is (name, provider, field, length) and nothing about who is admitted, so
every requirement column stays empty and the row is `待核验`: unknown stays unknown, and nothing here
writes `verified_at`.

Rows another source already describes are left alone. A row whose source is not the CRICOS dataset
(the hand-entered rows in `app.seed`, or a row the requirement importer wrote) keeps its values; the
catalogue only fills in courses nobody has described yet and keeps its own rows current.

`api/data/cricos/` holds a copy of `web/prototype-fixtures/cricos-au-masters.json`, because the API
image is built from `api/` alone; `tests/test_seed_catalog.py` fails if the two copies differ.
"""

import json
from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.document import Document
from app.models.program import Program, ProgramPrerequisite, University
from app.models.source import Source, SourceStatus
from app.models.task import RoadmapTask

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "cricos"
COURSES_FILE = DATA_DIR / "cricos-au-masters.json"
PROVIDERS_FILE = DATA_DIR / "providers.json"

CRICOS_SOURCE_ID = "src-cricos-courses"
CRICOS_SOURCE_URL = "https://data.gov.au/data/dataset/cricos"
CRICOS_SOURCE_TITLE = "CRICOS Courses (Australian Government Department of Education, CC BY 2.5 AU)"

# Universities the placeholder catalogue already created keep their ids, so their programs, sources and
# any portfolio that names them stay attached. Every other provider is `cricos-<provider code>`.
UNIVERSITY_IDS = {"00098G": "unsw", "00026A": "usyd", "00008C": "monash", "00025B": "uq", "00126G": "uwa"}

# The placeholder slugs and the CRICOS course each became. Chosen by matching the course name and
# provider in the extract; where a name has several codes, the one the course page cites. The Monash
# Master of Computer Science has no CRICOS course and is dropped.
LEGACY_SLUGS = {
    "unsw-master-it": "cricos-061294J",
    "usyd-master-cs": "cricos-111671D",
    "monash-master-ai": "cricos-103000K",
    "uq-master-data-science": "cricos-092454G",
    "uwa-master-it": "cricos-083866G",
    "monash-master-cs": None,
}

# CRICOS broad field (two-digit code) -> the study areas the interface offers (web/lib/taxonomy.ts).
# Society and Culture and Natural and Physical Sciences split by narrow field; a field with no fitting
# area stays null rather than being forced into one.
BROAD_FIELDS = {
    "02": "计算机与数据",
    "08": "商科与金融",
    "03": "工程",
    "07": "教育与社会科学",
    "06": "医学与健康",
    "01": "自然科学与数学",
    "04": "建筑规划与设计",
    "10": "传媒艺术与音乐",
    "05": "环境与农业",
    "09": "教育与社会科学",
}
NARROW_FIELDS = {
    "0109": "生命科学",
    "0909": "法律与犯罪学",
    "0911": "法律与犯罪学",
    "0913": "人文与语言",
    "0915": "人文与语言",
    "0917": "人文与语言",
}


def study_area(field: str, narrow: str) -> str | None:
    return NARROW_FIELDS.get(narrow[:4]) or BROAD_FIELDS.get(field[:2])


def load_courses(path: Path = COURSES_FILE) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["courses"]


def load_providers(path: Path = PROVIDERS_FILE) -> dict[str, dict]:
    return json.loads(path.read_text(encoding="utf-8"))["providers"]


def university_id(provider: str) -> str:
    return UNIVERSITY_IDS.get(provider, f"cricos-{provider}")


def program_id(code: str) -> str:
    return f"cricos-{code}"


def _ensure_source(session: Session) -> Source:
    source = session.get(Source, CRICOS_SOURCE_ID)
    if source is None:
        source = session.execute(select(Source).where(Source.url == CRICOS_SOURCE_URL)).scalar_one_or_none()
    if source is None:
        source = Source(
            id=CRICOS_SOURCE_ID,
            url=CRICOS_SOURCE_URL,
            title=CRICOS_SOURCE_TITLE,
            publisher="data.gov.au",
            domain="data.gov.au",
            status=SourceStatus.UNVERIFIED,
            verified_at=None,
        )
        session.add(source)
        session.flush()
    return source


def _ensure_universities(session: Session, courses: list[dict], providers: dict[str, dict]) -> int:
    added = 0
    for provider in sorted({course["provider"] for course in courses}):
        if session.get(University, university_id(provider)) is not None:
            continue
        identity = providers.get(provider, {})
        name_en = identity.get("name_en") or next(c["institution"] for c in courses if c["provider"] == provider)
        website = identity.get("website")
        if website and not website.startswith("http"):
            website = f"https://{website}"
        session.add(University(
            id=university_id(provider),
            name=identity.get("name_zh") or name_en,
            name_en=name_en,
            city=identity.get("city"),
            official_url=website,
        ))
        added += 1
    session.flush()
    return added


def fold_legacy_slugs(session: Session) -> dict:
    """Move every reference to a placeholder slug onto its CRICOS row, then delete the slug.

    A portfolio row moves when its subject does not already hold the target program; otherwise, or when
    the slug has no target, it is removed. Roadmap tasks and documents follow the same mapping.
    """
    moved = removed = folded = 0
    for slug, target in LEGACY_SLUGS.items():
        if session.get(Program, slug) is None:
            continue
        if target is not None and session.get(Program, target) is None:
            continue  # nothing to fold onto yet; the hand-entered seed writes the target first
        held = set(session.scalars(select(Application.client_id).where(Application.program_id == target))) if target else set()
        for application in session.scalars(select(Application).where(Application.program_id == slug)).all():
            if target is None or application.client_id in held:
                if application.is_primary and target is not None:
                    # The subject's first choice was this slug; it carries over to the row they keep.
                    kept = session.scalars(select(Application).where(
                        Application.client_id == application.client_id, Application.program_id == target)).first()
                    session.delete(application)
                    session.flush()
                    if kept is not None:
                        kept.is_primary = True
                else:
                    session.delete(application)
                removed += 1
            else:
                application.program_id = target
                moved += 1
        session.flush()
        for task in session.scalars(select(RoadmapTask).where(RoadmapTask.program_id == slug)).all():
            clash = session.execute(select(RoadmapTask.id).where(
                RoadmapTask.client_id == task.client_id,
                RoadmapTask.material_key == task.material_key,
                RoadmapTask.program_id == (target or ""),
            )).first()
            if clash:
                session.delete(task)
            else:
                task.program_id = target or ""
        session.execute(update(Document).where(Document.program_id == slug).values(program_id=target))
        session.execute(delete(ProgramPrerequisite).where(ProgramPrerequisite.program_id == slug))
        session.execute(delete(Program).where(Program.id == slug))
        folded += 1
    session.flush()
    return {"folded": folded, "applications_moved": moved, "applications_removed": removed}


def seed_catalog(session: Session, courses: list[dict] | None = None, providers: dict | None = None) -> dict:
    """Write the CRICOS catalogue and fold the placeholder slugs. Returns what changed."""
    courses = load_courses() if courses is None else courses
    providers = load_providers() if providers is None else providers
    source = _ensure_source(session)
    universities = _ensure_universities(session, courses, providers)

    added = updated = 0
    for course in courses:
        values = {
            "university_id": university_id(course["provider"]),
            "name_en": course["name"],
            "field": study_area(course["field"], course.get("narrow", "")),
            "duration": f"{course['weeks']} 周",
            "city": providers.get(course["provider"], {}).get("city"),
        }
        row = session.get(Program, program_id(course["code"]))
        if row is None:
            session.add(Program(
                id=program_id(course["code"]),
                name=course["name"],
                degree_level="授课型硕士",
                source_id=source.id,
                data_status="待核验",
                **values,
            ))
            added += 1
        elif row.source_id == source.id:
            changed = False
            for key, value in {**values, "name": course["name"]}.items():
                if getattr(row, key) != value:
                    setattr(row, key, value)
                    changed = True
            updated += changed
    session.flush()

    result = {"universities_added": universities, "programs_added": added, "programs_updated": updated}
    result.update(fold_legacy_slugs(session))
    session.commit()
    return result
