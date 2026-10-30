"""Cut the official pages the catalogue cites into chunks the advisor can quote (openspec snapshot-rag).

    python -m app.collect.chunks measure [--school K]... [--root DIR]
    python -m app.collect.chunks ingest  [--school K]... [--root DIR] [--prune]
    python -m app.collect.chunks bundle  --out FILE.tgz [--school K]... [--root DIR]

The pages are the ones the committed requirement files cite: each program's own page at the snapshot its
values were checked against, and every shared page a value was quoted from (D1). A page the collection
queue has collected since (`collect_pages`, done or unchanged) is taken at the queue's snapshot instead.

Each page's visible text loses the lines that open or close at least half of its school's pages (the
navigation and the footer, D2) and is cut on line boundaries into chunks of at most `CHUNK_CHARS`
characters (D3). Chunks are verbatim page text: the advisor's quotes are checked against exactly what
is stored. Nothing about where a snapshot lies on disk is stored, only its school key and sha256.

Ingesting is idempotent: a page whose chunked text, snapshot, school, program and title are what is
stored is not written again. `refresh_page` is the same for one page; the queue calls it when it
re-collects a page.
"""

import argparse
import hashlib
import io
import json
import math
import re
import sys
import tarfile
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from app.collect.snapshot import SNAPSHOT_ROOT
from app.models.collect import CollectPage, PageState
from app.models.program import Program, University
from app.models.snapshot import SnapshotChunk, SnapshotPage
from app.models.source import Source

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "requirements"
NAMESPACE = uuid.UUID("a3d6f0c1-7b2e-4f59-8c14-9e0b5d2a7f63")

# At most this many characters per chunk: about 300 English tokens, so six passages and the question
# stay near 2,500 tokens (D3).
CHUNK_CHARS = 1200
# A line that opens or closes at least this share of a school's pages (and at least
# `BOILERPLATE_MIN_PAGES` of them) is the site's frame, not the page's content (D2).
BOILERPLATE_SHARE = 0.5
BOILERPLATE_MIN_PAGES = 3
# Stored with each page: a different chunker re-cuts every page on the next ingest.
CHUNKER = f"lines-{CHUNK_CHARS}-trim{int(BOILERPLATE_SHARE * 100)}-v1"
# The queue states whose snapshot is the page as it now is (a page that lost every value is a person's
# to look at; its earlier snapshot stays).
CURRENT_STATES = (PageState.DONE, PageState.UNCHANGED)

_SENTENCE_END = re.compile(r"[.!?;。！？；](?=\s)")


# ---- text ---------------------------------------------------------------------------------------


def boilerplate_lines(texts: list[str]) -> set[str]:
    """Lines that appear on at least half of these pages (at least three of them). Only where they
    open or close a page are they removed (`trim`): the same sentence in the body of every page (an
    interview rule the school states for all its programs) is an answer, not a frame."""
    if len(texts) < BOILERPLATE_MIN_PAGES:
        return set()
    seen: Counter[str] = Counter()
    for text in texts:
        seen.update(set(text.split("\n")))
    limit = max(BOILERPLATE_MIN_PAGES, math.ceil(BOILERPLATE_SHARE * len(texts)))
    return {line for line, n in seen.items() if n >= limit}


def trim(text: str, boilerplate: set[str]) -> str:
    """The page without the boilerplate lines it opens and closes with."""
    lines = text.split("\n")
    start, end = 0, len(lines)
    while start < end and lines[start] in boilerplate:
        start += 1
    while end > start and lines[end - 1] in boilerplate:
        end -= 1
    return "\n".join(lines[start:end])


def _split_line(line: str, size: int) -> list[str]:
    """A line longer than `size`, cut after the last sentence end that fits, else the last space, else
    at `size`. The pieces joined by single spaces give the line back (when it was cut at spaces)."""
    parts = []
    while len(line) > size:
        window = line[: size + 1]
        cut = max((m.end() for m in _SENTENCE_END.finditer(window) if m.end() <= size), default=0)
        if cut == 0:
            cut = window.rfind(" ")
        if cut <= 0:
            parts.append(line[:size])
            line = line[size:]
            continue
        parts.append(line[:cut].rstrip())
        line = line[cut:].lstrip()
    if line:
        parts.append(line)
    return parts


def chunk_text(text: str, size: int = CHUNK_CHARS) -> list[str]:
    """Consecutive lines packed into pieces of at most `size` characters; a line is cut only when it is
    longer than `size` on its own."""
    out: list[str] = []
    current: list[str] = []
    length = 0
    for raw in text.split("\n"):
        if not raw:
            continue
        for line in _split_line(raw, size) if len(raw) > size else [raw]:
            if current and length + 1 + len(line) > size:
                out.append("\n".join(current))
                current, length = [], 0
            length += len(line) + (1 if current else 0)
            current.append(line)
    if current:
        out.append("\n".join(current))
    return out


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---- which pages ----------------------------------------------------------------------------------


@dataclass
class PageRef:
    school_key: str
    url: str
    sha: str
    title: str | None  # the program's name for its own page; None for a shared page
    fetched_at: str | None = None  # the file's date, when the snapshot's own record is missing


def requirement_files(data_dir: Path) -> list[Path]:
    return sorted(p for p in data_dir.glob("*.json") if not p.name.startswith("_"))


def file_pages(data_dir: Path, schools: list[str] | None = None) -> dict[str, dict[str, PageRef]]:
    """school key -> url -> the page the committed file cites. A program's own page wins over the same
    URL cited as a shared page (it carries the program's name)."""
    out: dict[str, dict[str, PageRef]] = {}
    for path in requirement_files(data_dir):
        data = json.loads(path.read_text(encoding="utf-8"))
        key = data["school_key"]
        if schools and key not in schools:
            continue
        pages = out.setdefault(key, {})
        shared: dict[str, PageRef] = {}
        for program in data.get("programs", []):
            if program.get("snapshot_sha256") and program.get("url") and program["url"] not in pages:
                pages[program["url"]] = PageRef(key, program["url"], program["snapshot_sha256"], program.get("name"),
                                                program.get("fetched_at") or data.get("collected_at"))
            for name, field in (program.get("fields") or {}).items():
                for item in field if isinstance(field, list) else [field]:
                    if isinstance(item, dict) and item.get("source_sha256") and item.get("source_url"):
                        shared.setdefault(item["source_url"], PageRef(key, item["source_url"], item["source_sha256"],
                                                                      None, data.get("collected_at")))
        for url, ref in shared.items():
            pages.setdefault(url, ref)
    return out


def _with_queue(session: Session, pages: dict[str, dict[str, PageRef]], root: Path,
                schools: list[str] | None) -> None:
    """Pages the queue holds a current snapshot of: its snapshot replaces the file's, and a page it
    collected that no file cites yet is added."""
    query = select(CollectPage.school_key, CollectPage.url, CollectPage.program_name, CollectPage.snapshot_sha256) \
        .where(CollectPage.state.in_(CURRENT_STATES), CollectPage.snapshot_sha256.is_not(None))
    if schools:
        query = query.where(CollectPage.school_key.in_(schools))
    for key, url, name, sha in session.execute(query):
        if not (root / key / f"{sha}.txt").exists():
            continue
        known = pages.setdefault(key, {}).get(url)
        if known is None:
            pages[key][url] = PageRef(key, url, sha, name)
        else:
            known.sha = sha


def _read(root: Path, ref: PageRef) -> str | None:
    path = root / ref.school_key / f"{ref.sha}.txt"
    return path.read_text(encoding="utf-8") if path.exists() else None


def _fetched_at(root: Path, ref: PageRef) -> datetime | None:
    meta = root / ref.school_key / f"{ref.sha}.json"
    when = json.loads(meta.read_text(encoding="utf-8")).get("fetched_at") if meta.exists() else None
    when = when or ref.fetched_at
    if not when:
        return None
    parsed = datetime.fromisoformat(when)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


# ---- links to the catalogue -----------------------------------------------------------------------


def program_links(session: Session, urls: list[str]) -> dict[str, tuple[str, str]]:
    """url -> (program id, university id) of the program whose cited page it is (the first by id)."""
    out: dict[str, tuple[str, str]] = {}
    for i in range(0, len(urls), 1000):
        rows = session.execute(
            select(Source.url, Program.id, Program.university_id)
            .join(Program, Program.source_id == Source.id)
            .where(Source.url.in_(urls[i:i + 1000]))
            .order_by(Source.url, Program.id)
        )
        for url, pid, uid in rows:
            out.setdefault(url, (pid, uid))
    return out


def school_university(session: Session, school_key: str, linked: list[str], name_en: str | None = None) -> str | None:
    """The university row a school's pages belong to: that of its linked programs (an Australian
    school's are CRICOS rows), else the row named by the school key, else the one row with the school's
    English name from `_schools.json` (an Australian school none of whose cited pages is a catalogued
    program), else none."""
    if linked:
        return Counter(linked).most_common(1)[0][0]
    if session.get(University, school_key) is not None:
        return school_key
    if name_en:
        rows = session.scalars(select(University.id).where(University.name_en == name_en).limit(2)).all()
        if len(rows) == 1:
            return rows[0]
    return None


def school_names(data_dir: Path) -> dict[str, str]:
    path = data_dir / "_schools.json"
    if not path.exists():
        return {}
    return {row["school_key"]: row.get("name_en") for row in json.loads(path.read_text(encoding="utf-8"))}


# ---- writing --------------------------------------------------------------------------------------


def page_id_for(url: str) -> str:
    return str(uuid.uuid5(NAMESPACE, url))


def _write_page(session: Session, ref: PageRef, university_id: str, program_id: str | None, body: str,
                fetched_at: datetime | None) -> bool:
    """Store the page and its chunks unless what is stored is the same. True when it wrote."""
    pid = page_id_for(ref.url)
    content = sha256(body)
    stored = session.get(SnapshotPage, pid)
    wanted = {"school_key": ref.school_key, "university_id": university_id, "program_id": program_id,
              "title": ref.title, "snapshot_sha256": ref.sha, "fetched_at": fetched_at,
              "content_sha256": content, "chunker": CHUNKER}
    if stored is not None and all(getattr(stored, k) == v for k, v in wanted.items()):
        return False
    if stored is not None and stored.content_sha256 == content and stored.chunker == CHUNKER:
        # The same text at a new snapshot (other HTML, same visible text) or under a new program row:
        # the chunks, their ids and their vectors stay; only the page's record changes (review of #60).
        for key, value in wanted.items():
            setattr(stored, key, value)
        stored.ingested_at = func.now()
        session.flush()
        return True
    pieces = chunk_text(body)
    if stored is None:
        session.add(SnapshotPage(id=pid, url=ref.url, chunk_count=len(pieces), **wanted))
    else:
        for key, value in wanted.items():
            setattr(stored, key, value)
        stored.chunk_count = len(pieces)
        stored.ingested_at = func.now()
        session.execute(delete(SnapshotChunk).where(SnapshotChunk.page_id == pid))
    session.flush()
    if pieces:
        session.execute(insert(SnapshotChunk), [
            {"id": str(uuid.uuid5(NAMESPACE, f"{pid}\n{content}\n{n}")), "page_id": pid, "ordinal": n,
             "text": piece, "content_sha256": sha256(piece)}
            for n, piece in enumerate(pieces)
        ])
    return True


def ingest(session: Session, data_dir: Path = DATA_DIR, root: Path = SNAPSHOT_ROOT,
           schools: list[str] | None = None, prune: bool = False) -> dict:
    """Bring `snapshot_pages` and `snapshot_chunks` in line with the cited pages, one school per
    transaction."""
    pages = file_pages(data_dir, schools)
    _with_queue(session, pages, root, schools)
    names = school_names(data_dir)
    report = {"schools": 0, "schools_without_university": [], "pages_written": 0, "pages_unchanged": 0,
              "pages_pruned": 0, "missing_snapshots": 0, "chunks": 0}
    for key in sorted(pages):
        refs = list(pages[key].values())
        texts = {ref.url: _read(root, ref) for ref in refs}
        report["missing_snapshots"] += sum(1 for t in texts.values() if t is None)
        present = [ref for ref in refs if texts[ref.url] is not None]
        links = program_links(session, [ref.url for ref in present])
        university = school_university(session, key, [uid for _, uid in links.values()], names.get(key))
        if university is None:
            report["schools_without_university"].append(key)
            continue
        boilerplate = boilerplate_lines([texts[ref.url] for ref in present])
        for ref in present:
            body = trim(texts[ref.url], boilerplate)
            program_id = links.get(ref.url, (None, None))[0]
            if _write_page(session, ref, university, program_id, body, _fetched_at(root, ref)):
                report["pages_written"] += 1
            else:
                report["pages_unchanged"] += 1
        if prune:
            # Only pages no file cites any more: a cited page whose snapshot is missing from this store
            # keeps what was ingested before (review of #60).
            gone = delete(SnapshotPage).where(SnapshotPage.school_key == key,
                                              SnapshotPage.url.not_in([ref.url for ref in refs]))
            report["pages_pruned"] += session.execute(gone).rowcount or 0
        session.commit()
        report["schools"] += 1
    report["chunks"] = session.scalar(select(func.count()).select_from(SnapshotChunk)) or 0
    return report


def refresh_page(session: Session, school_key: str, url: str, sha: str, root: Path = SNAPSHOT_ROOT,
                 data_dir: Path = DATA_DIR) -> str:
    """Re-cut one page at snapshot `sha` (the queue has just collected it). The boilerplate is learnt
    from the school's stored pages, read at their stored snapshots."""
    ref = PageRef(school_key, url, sha, None)
    text = _read(root, ref)
    if text is None:
        return "missing snapshot"
    stored = session.get(SnapshotPage, page_id_for(url))
    link = program_links(session, [url]).get(url)
    if stored is not None:
        university, ref.title = stored.university_id, stored.title
    else:
        university = link[1] if link else school_university(session, school_key, [],
                                                            school_names(data_dir).get(school_key))
        ref.title = session.scalar(select(CollectPage.program_name).where(
            CollectPage.school_key == school_key, CollectPage.url == url))
    if university is None:
        return "no university"
    siblings = session.execute(select(SnapshotPage.url, SnapshotPage.snapshot_sha256).where(
        SnapshotPage.school_key == school_key, SnapshotPage.url != url)).all()
    texts = [text] + [t for u, s in siblings if (t := _read(root, PageRef(school_key, u, s, None))) is not None]
    body = trim(text, boilerplate_lines(texts))
    written = _write_page(session, ref, university, link[0] if link else None, body, _fetched_at(root, ref))
    session.commit()
    return "written" if written else "unchanged"


# ---- measuring --------------------------------------------------------------------------------------


def measure(data_dir: Path = DATA_DIR, root: Path = SNAPSHOT_ROOT, schools: list[str] | None = None) -> dict:
    """What `ingest` would store from the files alone (no database): pages, characters before and after
    the boilerplate trim, and chunks."""
    pages = file_pages(data_dir, schools)
    out = {"schools": 0, "pages": 0, "missing_snapshots": 0, "chars_full": 0, "chars_trimmed": 0, "chunks": 0,
           "chunk_chars": CHUNK_CHARS, "chunker": CHUNKER}
    sizes: list[int] = []
    for key in sorted(pages):
        texts = [t for ref in pages[key].values() if (t := _read(root, ref)) is not None]
        out["missing_snapshots"] += len(pages[key]) - len(texts)
        if not texts:
            continue
        out["schools"] += 1
        boilerplate = boilerplate_lines(texts)
        for text in texts:
            body = trim(text, boilerplate)
            out["pages"] += 1
            out["chars_full"] += len(text)
            out["chars_trimmed"] += len(body)
            out["chunks"] += len(chunk_text(body))
            sizes.append(len(text))
    sizes.sort()
    if sizes:
        out["page_chars_median"] = sizes[len(sizes) // 2]
        out["page_chars_p99"] = sizes[int(0.99 * (len(sizes) - 1))]
        out["page_chars_max"] = sizes[-1]
    return out


def bundle(out: Path, data_dir: Path = DATA_DIR, root: Path = SNAPSHOT_ROOT, schools: list[str] | None = None) -> dict:
    """A tgz of the cited snapshots' text and records, laid out as the snapshot store, for a store that
    lacks them (production's `snapshots` volume, D12). A record's `text_path` names a local folder, so
    it is left out; nothing else in a record is local."""
    pages = file_pages(data_dir, schools)
    seen: set[tuple[str, str]] = set()
    report = {"pages": 0, "missing_snapshots": 0, "bytes": 0}
    with tarfile.open(out, "w:gz") as tar:
        for key in sorted(pages):
            for ref in pages[key].values():
                if (key, ref.sha) in seen:
                    continue
                seen.add((key, ref.sha))
                text = root / key / f"{ref.sha}.txt"
                if not text.exists():
                    report["missing_snapshots"] += 1
                    continue
                tar.add(text, arcname=f"{key}/{ref.sha}.txt")
                meta_path = root / key / f"{ref.sha}.json"
                if meta_path.exists():
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    meta.pop("text_path", None)
                    body = json.dumps(meta, ensure_ascii=False, indent=1).encode("utf-8")
                    info = tarfile.TarInfo(f"{key}/{ref.sha}.json")
                    info.size = len(body)
                    tar.addfile(info, io.BytesIO(body))
                report["pages"] += 1
                report["bytes"] += text.stat().st_size
    report["file_bytes"] = out.stat().st_size
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=("measure", "ingest", "bundle"))
    parser.add_argument("--school", action="append")
    parser.add_argument("--root", type=Path, default=SNAPSHOT_ROOT)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--prune", action="store_true", help="remove pages the files no longer cite")
    parser.add_argument("--out", type=Path, help="bundle: the tgz to write")
    args = parser.parse_args(argv)
    if args.command == "bundle":
        if args.out is None:
            parser.error("bundle needs --out")
        print(json.dumps(bundle(args.out, args.data_dir, args.root, args.school), ensure_ascii=False))
        return 0
    if args.command == "measure":
        print(json.dumps(measure(args.data_dir, args.root, args.school), ensure_ascii=False))
        return 0
    from app.db import SessionLocal

    with SessionLocal() as session:
        report = ingest(session, args.data_dir, args.root, args.school, prune=args.prune)
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
