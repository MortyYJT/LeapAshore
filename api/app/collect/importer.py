"""Import the checked requirement files into the catalogue.

    python -m app.collect.importer [--prune] [api/data/requirements/<school>.json ...]

--prune also removes the programs an earlier import wrote that a file no longer lists (CRICOS rows
and rows a portfolio names are kept).

Only fields whose quote passed `verify` (`check == "ok"`) and whose summary the faithfulness check did
not find unfaithful (`verify.usable`) are written. A program with no verified quote at all is skipped, so an empty collection never blanks a row another source describes. When a program has
verified values, its requirement columns (English, marks, prerequisites) are replaced as one set, so
every value on the row comes from the same collection; the academic summary and the deadlines are part
of that set. Deadlines are compared with what is stored and rewritten only when they differ, so a rerun
over the same files writes nothing. A program is `机器核对` when every field it
reports is usable, otherwise `待核验`. A program whose quotes passed but whose summaries were all
downgraded is still written: its values become unknown, so a summary found unfaithful after an earlier
import leaves the catalogue. Nothing here writes `verified_at`: the page source stays
`待核验` until a person reviews it, and its snapshot version stays `pending_review`.

Australian programs land on their CRICOS row (`cricos-<code>`); everything else gets
`<school_key>-<program slug>`, under a university row named from `_schools.json`. Each program page
becomes one `Source`, and each distinct snapshot of it one `SourceVersion` whose `body_text` holds the
verified quotes (the full page stays in the local snapshot store, which is not published).
"""

import json
import re
import sys
import unicodedata
import uuid
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.collect.fields import study_area_from_name
from app.collect.snapshot import SNAPSHOT_ROOT
from app.collect.verify import LIST_FIELDS, MACHINE_CHECKED, program_status, usable
from app.models.program import Program, ProgramDeadline, ProgramPrerequisite, University
from app.models.source import Source, SourceStatus, SourceVersion

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "requirements"
SCHOOLS_FILE = DATA_DIR / "_schools.json"
SOURCE_NAMESPACE = uuid.UUID("6f2b7a1e-0c55-4c1f-9d7a-2e3b0f6c8a41")

COUNTRY_ZH = {
    "Australia": "澳大利亚", "Hong Kong SAR": "中国香港", "Singapore": "新加坡", "United Kingdom": "英国",
    "United States": "美国", "Canada": "加拿大", "New Zealand": "新西兰", "Japan": "日本",
    "South Korea": "韩国", "Malaysia": "马来西亚", "Macau SAR": "中国澳门",
    "Germany": "德国", "Netherlands": "荷兰", "Switzerland": "瑞士", "France": "法国", "Belgium": "比利时",
    "Sweden": "瑞典", "Italy": "意大利", "Spain": "西班牙", "Ireland": "爱尔兰", "Denmark": "丹麦",
    "Norway": "挪威", "Austria": "奥地利", "Finland": "芬兰", "Portugal": "葡萄牙", "Czechia": "捷克",
    "Poland": "波兰", "United Arab Emirates": "阿联酋", "Saudi Arabia": "沙特阿拉伯", "Qatar": "卡塔尔",
}


def slugify(text: str, limit: int) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:limit].strip("-")


def program_id_for(school_key: str, program: dict) -> str:
    if program.get("cricos_code"):
        return f"cricos-{program['cricos_code']}"
    # 64 characters at most, and stable for one program: the slug of its name, then a short hash of
    # its url and full name, so two programs with one name (a part-time variant) and two variants on
    # one page whose names differ past the slug's length (45 vs 65 credits) all stay apart.
    digest = uuid.uuid5(SOURCE_NAMESPACE, f"{program['url']}\n{program['name']}").hex[:6]
    return f"{slugify(school_key, 24)}-{slugify(program['name'], 32)}-{digest}"


def source_id_for(url: str) -> str:
    return str(uuid.uuid5(SOURCE_NAMESPACE, url))


def passed(item: dict) -> bool:
    return item.get("check") == "ok"


def english_text(fields: dict) -> str | None:
    """IELTS and TOEFL minimums in one line the interface can parse (`IELTS 6.5…`).

    A TOEFL minimum on the 1-6 scale ETS introduced in January 2026 (`scale: "iBT 1-6"`) says so, or
    `TOEFL iBT 4.5` would read as a score out of 120.

    A score the page only recommends ("we recommend at least 7.5", "preferred") is not a minimum, and
    the interface compares any `IELTS <n>` it finds against the applicant's score. So a recommended
    score is written in words outside that form (`建议雅思 7.5（非最低要求）`): it is shown, never
    compared.
    """
    parts = []
    for test, label, word, form in (("ielts", "IELTS", "雅思", "{:.1f}"), ("toefl", "TOEFL iBT", "托福", "{:g}")):
        item = fields.get(test)
        if item and usable(item) and item.get("overall") is not None:
            if item.get("recommended"):
                text = f"建议{word} {form.format(item['overall'])}"
            else:
                text = f"{label} {form.format(item['overall'])}"
            if item.get("min_band") is not None:
                text += f"，单项不低于 {form.format(item['min_band'])}"
            if test == "toefl" and item.get("scale") == "iBT 1-6":
                text += "（新版 1–6 分制）"
            if item.get("recommended"):
                text += "（非最低要求）"
            parts.append(text)
    return "；".join(parts) or None


def verified_quotes(fields: dict) -> str:
    """The verified quotes, one per line; a quote from a shared page names that page."""
    lines = []
    for name, field in fields.items():
        for item in field if name in LIST_FIELDS else [field]:
            if passed(item):
                line = f"[{name}] {item['quote']}"
                if item.get("source_sha256"):
                    line += f" (出处: {item.get('source_url') or 'sha256 ' + item['source_sha256']})"
                lines.append(line)
    return "\n".join(lines)


def academic_text(fields: dict) -> str | None:
    """The collector's summary of the academic requirement, when its quote passed; otherwise unknown."""
    item = fields.get("academic")
    if item and usable(item):
        return (item.get("text") or "").strip() or None
    return None


def academic_source(fields: dict, program_url: str) -> str | None:
    """The page the academic requirement's quote is on, when there is a requirement to cite."""
    if academic_text(fields) is None:
        return None
    return fields["academic"].get("source_url") or program_url


def deadline_rows(pid: str, program_url: str, fields: dict) -> list[dict]:
    """The verified deadlines, in the file's order, as `program_deadlines` rows.

    The id is the program and the position, like a prerequisite's: one page can list the same round
    and date twice, so the content alone does not name a row. `source_url` is the page the quote is on.
    """
    rows = []
    for item in fields.get("deadlines", []):
        if not usable(item):
            continue
        index = len(rows)
        rows.append({
            "id": str(uuid.uuid5(SOURCE_NAMESPACE, f"{pid}#deadline#{index}")),
            "program_id": pid,
            "label": (item.get("label") or "").strip() or None,
            "deadline": date.fromisoformat(item["date"]),
            "quote": item["quote"],
            "source_url": item.get("source_url") or program_url,
            "sort_order": index,
        })
    return rows


def _sync_deadlines(session: Session, pid: str, wanted: list[dict]) -> None:
    """Make the program's deadlines `wanted`, writing only when they differ (openspec requirement-dates D5)."""
    columns = ("id", "label", "deadline", "quote", "source_url", "sort_order")
    stored = session.scalars(select(ProgramDeadline).where(ProgramDeadline.program_id == pid)
                             .order_by(ProgramDeadline.sort_order)).all()
    if [tuple(getattr(row, c) for c in columns) for row in stored] == [tuple(row[c] for c in columns) for row in wanted]:
        return
    session.execute(delete(ProgramDeadline).where(ProgramDeadline.program_id == pid))
    session.flush()
    for row in wanted:
        session.add(ProgramDeadline(**row))


def has_verified_value(fields: dict) -> bool:
    """Whether any quote passed: the collection found something, even if no summary is usable."""
    return any(passed(item) for name, field in fields.items() for item in (field if name in LIST_FIELDS else [field]))


def _university(session: Session, data: dict, school: dict | None, program_ids: list[str]) -> str | None:
    """The university row for this school; Australian ones already exist from the CRICOS seed.

    None for an Australian school none of whose courses is in the catalogue: its row is the CRICOS one,
    found through a course, and making one from the file key would put the school in the library twice
    (twelve such empty rows in production, 2026-10-30).
    """
    existing = session.scalars(select(Program.university_id).where(Program.id.in_(program_ids))).first()
    if existing is None and (school or {}).get("cricos_institution"):
        return None
    key = existing or data["school_key"]
    row = session.get(University, key)
    if row is not None and row.country in COUNTRY_ZH:
        # Rows written before the European and Middle Eastern names were mapped carry the English name.
        row.country = COUNTRY_ZH[row.country]
    if existing:
        return existing
    if row is None:
        listing = (data.get("listing_urls") or [None])[0]
        session.add(University(
            id=key,
            name=(school or {}).get("name_zh") or data["school_name_en"],
            name_en=data["school_name_en"],
            country=COUNTRY_ZH.get(data.get("country") or "", (school or {}).get("country") or "未知")[:32],
            official_url=f"{urlsplit(listing).scheme}://{urlsplit(listing).netloc}/" if listing else None,
        ))
        session.flush()
    return key


def _snapshot_meta(school_key: str, sha: str, root: Path) -> dict:
    path = root / school_key / f"{sha}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _importable(data: dict, school: dict | None) -> tuple[list[dict], int]:
    """The file's programs the importer may write, and how many it leaves out.

    An Australian school's programs are its CRICOS catalogue rows: a course without its CRICOS code
    has no row to land on, and writing it anyway made a second row for the school (named from its
    school key) or a second row for a course the catalogue already lists (review of PR #51).
    """
    programs = data.get("programs", [])
    if not (school or {}).get("cricos_institution"):
        return programs, 0
    kept = [p for p in programs if p.get("cricos_code")]
    return kept, len(programs) - len(kept)


def import_school(session: Session, data: dict, schools: dict[str, dict], root: Path = SNAPSHOT_ROOT) -> dict:
    key = data["school_key"]
    programs, skipped = _importable(data, schools.get(key))
    report = {"school": key, "programs_added": 0, "programs_updated": 0}
    if skipped:
        report["skipped_without_cricos_code"] = skipped
        if not programs:
            return report  # every course lacks its code: no row to find the school by, none to make
    ids = [program_id_for(key, p) for p in programs]
    university_id = _university(session, data, schools.get(key), ids)
    if university_id is None:
        return {**report, "no_catalogue_row": len(programs)}
    added = updated = 0
    for program, pid in zip(programs, ids):
        fields = program.get("fields", {})
        if not has_verified_value(fields):
            # Nothing usable was collected (a blocked site, an empty page): the row keeps whatever
            # another source says about it, rather than being blanked by an empty collection.
            continue
        meta = _snapshot_meta(key, program["snapshot_sha256"], root)

        source = session.get(Source, source_id_for(program["url"])) or session.execute(
            select(Source).where(Source.url == program["url"])
        ).scalar_one_or_none()
        if source is None:
            source = Source(
                id=source_id_for(program["url"]), url=program["url"], title=program["name"],
                publisher=university_id, domain=urlsplit(program["url"]).netloc,
                status=SourceStatus.UNVERIFIED, verified_at=None,
            )
            session.add(source)
            session.flush()
        known = session.scalar(select(SourceVersion.id).where(
            SourceVersion.source_id == source.id, SourceVersion.content_sha256 == program["snapshot_sha256"]))
        if known is None:
            if source.status != SourceStatus.UNVERIFIED or source.verified_at is not None:
                # A person verified an older version of this page; the new content is not covered by
                # that review, so the page goes back to unverified until someone looks again.
                source.status, source.verified_at = SourceStatus.UNVERIFIED, None
            number = (session.scalar(select(func.max(SourceVersion.version_no)).where(SourceVersion.source_id == source.id)) or 0) + 1
            fetched = meta.get("fetched_at") or program.get("fetched_at")
            session.add(SourceVersion(
                id=str(uuid.uuid4()), source_id=source.id, version_no=number,
                requested_url=meta.get("requested_url", program["url"]), final_url=meta.get("final_url"),
                fetched_at=datetime.fromisoformat(fetched) if fetched else None,
                content_type=meta.get("content_type"), content_sha256=program["snapshot_sha256"],
                body_text=verified_quotes(fields) or None,
            ))

        china = fields.get("china_requirement") or {}
        china_ok = usable(china) if china else False
        values = {
            "english_requirement": english_text(fields),
            "minimum_mark": china.get("min_mark_211") if china_ok else None,
            "non_211_minimum_mark": china.get("min_mark_other") if china_ok else None,
            "academic_requirement": academic_text(fields),
            "academic_source_url": academic_source(fields, program["url"]),
            "source_id": source.id,
            "data_status": MACHINE_CHECKED if program_status(program) == MACHINE_CHECKED else "待核验",
        }
        row = session.get(Program, pid)
        if row is None:
            if program.get("cricos_code"):
                continue  # an Australian course the catalogue does not carry: nothing to attach it to
            row = Program(id=pid, university_id=university_id, name=program["name"], name_en=program["name"],
                          degree_level="授课型硕士", field=study_area_from_name(program["name"]), **values)
            session.add(row)
            added += 1
        else:
            for column, value in values.items():
                setattr(row, column, value)
            # A row that already has a study area keeps it: a CRICOS row's comes from the official field.
            if row.field is None:
                row.field = study_area_from_name(row.name_en or row.name)
            updated += 1
        session.flush()

        prerequisites = [item["text"] if item.get("text") else item["quote"]
                         for item in fields.get("prerequisites", []) if usable(item)]
        stored = session.execute(select(ProgramPrerequisite.id, ProgramPrerequisite.label)
                                 .where(ProgramPrerequisite.program_id == pid)
                                 .order_by(ProgramPrerequisite.sort_order)).all()
        # A program id can be 64 characters, so a suffixed id would be cut back onto its neighbour.
        wanted = [(str(uuid.uuid5(SOURCE_NAMESPACE, f"{pid}#prerequisite#{index}")), label)
                  for index, label in enumerate(prerequisites)]
        if [tuple(row) for row in stored] != wanted:
            session.execute(delete(ProgramPrerequisite).where(ProgramPrerequisite.program_id == pid))
            for index, (prerequisite_id, label) in enumerate(wanted):
                session.add(ProgramPrerequisite(id=prerequisite_id, program_id=pid, label=label,
                                                category="collected", sort_order=index))
        _sync_deadlines(session, pid, deadline_rows(pid, program["url"], fields))
    session.commit()
    return {**report, "programs_added": added, "programs_updated": updated}


def load_schools(path: Path = SCHOOLS_FILE) -> dict[str, dict]:
    return {row["school_key"]: row for row in json.loads(path.read_text(encoding="utf-8"))}


def requirement_files(directory: Path = DATA_DIR) -> list[Path]:
    return sorted(p for p in directory.glob("*.json") if not p.name.startswith("_"))


def prune_school(session: Session, data: dict, schools: dict[str, dict]) -> dict:
    """Remove the programs an earlier import wrote for this school that its file no longer lists.

    Only rows the importer owns are touched: a CRICOS catalogue row (`cricos-…`) stays, whatever
    the file says. A row someone's portfolio names stays too (`applications.program_id` is
    RESTRICT, and a portfolio should not lose a choice silently); it is reported instead.
    """
    from app.models.application import Application

    key = data["school_key"]
    programs, skipped = _importable(data, schools.get(key))
    ids = {program_id_for(key, p) for p in programs}
    if skipped and not ids:
        return {"school": key, "pruned": 0, "kept_in_portfolios": []}  # no CRICOS row to find the school by
    university_id = _university(session, data, schools.get(key), sorted(ids))
    if university_id is None:
        return {"school": key, "pruned": 0, "kept_in_portfolios": []}
    stale = [pid for pid in session.scalars(select(Program.id).where(Program.university_id == university_id))
             if not pid.startswith("cricos-") and pid not in ids]
    held = set(session.scalars(select(Application.program_id).where(Application.program_id.in_(stale)))) if stale else set()
    removable = [pid for pid in stale if pid not in held]
    if removable:
        session.execute(delete(ProgramPrerequisite).where(ProgramPrerequisite.program_id.in_(removable)))
        session.execute(delete(ProgramDeadline).where(ProgramDeadline.program_id.in_(removable)))
        session.execute(delete(Program).where(Program.id.in_(removable)))
    session.commit()
    return {"school": key, "pruned": len(removable), "kept_in_portfolios": sorted(held)}


def main(argv: list[str]) -> int:
    from app.db import SessionLocal

    prune = "--prune" in argv
    paths = [Path(a) for a in argv if a != "--prune"] or requirement_files()
    schools = load_schools()
    failed = 0
    with SessionLocal() as session:
        for path in paths:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                result = import_school(session, data, schools)
                if prune:
                    result.update(prune_school(session, data, schools))
            except Exception as error:  # noqa: BLE001 - one bad file must not stop the others
                session.rollback()
                failed += 1
                result = {"school": path.stem, "error": str(error).splitlines()[0][:300]}
            print(json.dumps(result, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
