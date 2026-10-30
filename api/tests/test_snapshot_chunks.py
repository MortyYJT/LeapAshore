"""Snapshot chunks (openspec snapshot-rag D1-D5): the boilerplate trim, the chunker, idempotent
ingestion from requirement files and a snapshot root, and the collection queue's refresh. No network:
snapshots are written into a temporary root the way the snapshot tool writes them."""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select

from app.collect import chunks
from app.collect.importer import program_id_for, source_id_for
from app.db import SessionLocal
from app.models.collect import CollectPage, PageState
from app.models.program import Program, University
from app.models.snapshot import CHUNK_TSV_SQL, SnapshotChunk, SnapshotPage
from app.models.source import Source

pytestmark = pytest.mark.usefixtures("require_db")

NAV = ["Home", "Study with us", "Fees and scholarships", "Contact"]
FOOT = ["Privacy", "Copyright 2026 Example University"]


# ---- pure functions -----------------------------------------------------------------------------


def test_lines_on_half_the_pages_or_more_are_boilerplate_only_at_the_head_and_tail():
    pages = [
        "\n".join(NAV + ["Master of A", "Tuition: A$40,000 per year", "Interview required"] + FOOT),
        "\n".join(NAV + ["Master of B", "Interview required", "Tuition: A$41,000 per year"] + FOOT),
        "\n".join(NAV + ["Master of C", "Interview required", "Two references"] + FOOT),
    ]
    common = chunks.boilerplate_lines(pages)
    assert "Home" in common and "Privacy" in common
    # Repeated on every page, but in the body: it is the answer to a question, so it stays.
    assert "Interview required" in common
    trimmed = chunks.trim(pages[2], common)
    assert trimmed.splitlines() == ["Master of C", "Interview required", "Two references"]


def test_fewer_than_three_pages_have_no_boilerplate():
    assert chunks.boilerplate_lines(["a\nb", "a\nb"]) == set()


def test_a_page_that_is_all_boilerplate_keeps_nothing():
    pages = ["\n".join(NAV)] * 3
    assert chunks.trim(pages[0], chunks.boilerplate_lines(pages)) == ""


def test_chunks_follow_lines_and_stay_under_the_size():
    lines = [f"Line {i} " + "x" * 90 for i in range(40)]
    out = chunks.chunk_text("\n".join(lines), size=300)
    assert all(len(c) <= 300 for c in out)
    # Nothing lost, nothing reordered, no line cut.
    assert "\n".join(out) == "\n".join(lines)


def test_a_long_line_is_split_at_a_sentence_then_a_space():
    sentence = "Applicants must submit two letters of recommendation. "
    line = sentence * 20
    out = chunks.chunk_text(line.strip(), size=200)
    assert all(len(c) <= 200 for c in out)
    assert all(c.endswith(".") for c in out[:-1])
    assert " ".join(out) == line.strip()
    word_soup = " ".join(["word"] * 100)
    parts = chunks.chunk_text(word_soup, size=50)
    assert all(len(p) <= 50 for p in parts) and " ".join(parts) == word_soup
    unbroken = "y" * 130
    assert chunks.chunk_text(unbroken, size=50) == ["y" * 50, "y" * 50, "y" * 30]


def test_the_generated_column_matches_the_migration():
    path = Path(chunks.__file__).resolve().parents[2] / "alembic" / "versions" / \
        "f7c2d9a4e816_add_snapshot_pages_and_chunks.py"
    assert f'CHUNK_TSV_SQL = "{CHUNK_TSV_SQL}"' in path.read_text()


# ---- ingestion ----------------------------------------------------------------------------------


def write_snapshot(root, school, text, url, fetched="2026-10-20T08:00:00+00:00", local_path=True):
    """A snapshot as the tool writes it: `<sha>.txt` and `<sha>.json` (the html is not needed)."""
    sha = hashlib.sha256(f"{url}\n{text}".encode()).hexdigest()
    folder = root / school
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{sha}.txt").write_text(text, encoding="utf-8")
    meta = {"sha256": sha, "requested_url": url, "final_url": url, "status": 200, "fetched_at": fetched,
            "text_chars": len(text)}
    if local_path:
        meta["text_path"] = str(folder / f"{sha}.txt")
    (folder / f"{sha}.json").write_text(json.dumps(meta), encoding="utf-8")
    return sha


@pytest.fixture
def school(tmp_path):
    """A school with three program pages, one shared fees page, a requirement file and a catalogue row
    for two of the programs. Everything is removed afterwards."""
    key = f"test-chunks-{uuid.uuid4().hex[:8]}"
    root, data_dir = tmp_path / "snapshots", tmp_path / "data"
    data_dir.mkdir()
    base = f"https://www.{key}.example.edu"
    bodies = {
        "a": ["Master of Data Science", "Tuition: A$45,000 per year (2027)", "Two letters of recommendation."],
        "b": ["Master of Finance", "An interview may be required.", "Tuition: A$52,000 per year (2027)"],
        "c": ["Master of History", "No interview."],
    }
    programs, shas = [], {}
    for k, body in bodies.items():
        url = f"{base}/{k}"
        shas[k] = write_snapshot(root, key, "\n".join(NAV + body + FOOT), url)
        programs.append({"name": body[0], "url": url, "snapshot_sha256": shas[k], "fields": {}, "status": "待人工"})
    fees_url = f"{base}/fees"
    shas["fees"] = write_snapshot(root, key, "\n".join(NAV + ["Fees for international students",
                                                              "Fees are charged per credit point."] + FOOT), fees_url)
    programs[0]["fields"] = {"academic": {"text": "x", "quote": "x", "check": "ok", "source_url": fees_url,
                                          "source_sha256": shas["fees"]}}
    data = {"school_key": key, "school_name_en": "Chunk Test University", "programs": programs}
    (data_dir / f"{key}.json").write_text(json.dumps(data), encoding="utf-8")
    uid = key
    made_programs = []
    with SessionLocal() as s:
        s.add(University(id=uid, name="切块测试大学", name_en="Chunk Test University", country="美国"))
        s.flush()
        for p in programs[:2]:
            sid = source_id_for(p["url"])
            s.add(Source(id=sid, url=p["url"], title=p["name"]))
            s.flush()
            pid = program_id_for(key, p)
            s.add(Program(id=pid, university_id=uid, name=p["name"], name_en=p["name"], source_id=sid))
            made_programs.append(pid)
        s.commit()
    yield {"key": key, "root": root, "data_dir": data_dir, "uid": uid, "base": base, "shas": shas,
           "programs": made_programs, "fees_url": fees_url}
    with SessionLocal() as s:
        s.execute(delete(SnapshotPage).where(SnapshotPage.school_key == key))
        s.execute(delete(CollectPage).where(CollectPage.school_key == key))
        s.execute(delete(Program).where(Program.id.in_(made_programs)))
        s.execute(delete(Source).where(Source.url.like(f"{base}%")))
        s.execute(delete(University).where(University.id == uid))
        s.commit()


def ingest(school, **kw):
    with SessionLocal() as s:
        return chunks.ingest(s, data_dir=school["data_dir"], root=school["root"], schools=[school["key"]], **kw)


def pages_of(school):
    with SessionLocal() as s:
        return {p.url: p for p in s.scalars(select(SnapshotPage).where(SnapshotPage.school_key == school["key"]))}


def chunk_texts(school):
    with SessionLocal() as s:
        rows = s.execute(select(SnapshotPage.url, SnapshotChunk.text).join(SnapshotChunk)
                         .where(SnapshotPage.school_key == school["key"]).order_by(SnapshotPage.url, SnapshotChunk.ordinal))
        out = {}
        for url, text in rows:
            out.setdefault(url, []).append(text)
        return out


def test_ingest_stores_every_cited_page_without_a_path(school):
    report = ingest(school)
    assert report["pages_written"] == 4 and report["pages_unchanged"] == 0
    pages = pages_of(school)
    assert set(pages) == {f"{school['base']}/{k}" for k in "abc"} | {school["fees_url"]}
    a = pages[f"{school['base']}/a"]
    assert a.university_id == school["uid"] and a.program_id == school["programs"][0]
    assert a.title == "Master of Data Science"
    assert a.snapshot_sha256 == school["shas"]["a"]
    assert a.fetched_at == datetime(2026, 10, 20, 8, tzinfo=UTC)
    # A program the catalogue does not hold, and a shared page, belong to the school only.
    assert pages[f"{school['base']}/c"].program_id is None
    assert pages[school["fees_url"]].program_id is None
    texts = chunk_texts(school)
    # The navigation and the footer every page carries are gone; the page's own words are verbatim.
    assert texts[f"{school['base']}/a"] == ["Master of Data Science\nTuition: A$45,000 per year (2027)\n"
                                            "Two letters of recommendation."]
    with SessionLocal() as s:
        values = [str(v) for row in s.execute(select(SnapshotPage)).scalars() for v in vars(row).values()]
    assert not any(str(school["root"]) in v or "/Users/" in v for v in values)


def test_a_second_ingest_writes_nothing(school):
    ingest(school)
    with SessionLocal() as s:
        before = s.execute(select(SnapshotChunk.id, SnapshotChunk.text, SnapshotPage.ingested_at)
                           .join(SnapshotPage).where(SnapshotPage.school_key == school["key"])
                           .order_by(SnapshotChunk.id)).all()
    report = ingest(school)
    assert report["pages_written"] == 0 and report["pages_unchanged"] == 4
    with SessionLocal() as s:
        after = s.execute(select(SnapshotChunk.id, SnapshotChunk.text, SnapshotPage.ingested_at)
                          .join(SnapshotPage).where(SnapshotPage.school_key == school["key"])
                          .order_by(SnapshotChunk.id)).all()
    assert before == after


def test_the_queues_newer_snapshot_replaces_the_files(school):
    ingest(school)
    url = f"{school['base']}/b"
    new = write_snapshot(school["root"], school["key"],
                         "\n".join(NAV + ["Master of Finance", "Interviews are held online.",
                                          "Tuition: A$53,000 per year (2027)"] + FOOT), url,
                         fetched="2026-10-29T08:00:00+00:00")
    with SessionLocal() as s:
        s.add(CollectPage(id=str(uuid.uuid4()), school_key=school["key"], url=url, program_name="Master of Finance",
                          state=PageState.DONE, snapshot_sha256=new, attempts=1))
        s.commit()
    report = ingest(school)
    assert report["pages_written"] == 1
    page = pages_of(school)[url]
    assert page.snapshot_sha256 == new
    assert "Interviews are held online." in chunk_texts(school)[url][0]
    assert "An interview may be required." not in chunk_texts(school)[url][0]


def test_refresh_rechunks_one_re_collected_page(school):
    ingest(school)
    url = f"{school['base']}/a"
    new = write_snapshot(school["root"], school["key"],
                         "\n".join(NAV + ["Master of Data Science", "Tuition: A$47,000 per year (2027)"] + FOOT), url)
    with SessionLocal() as s:
        assert chunks.refresh_page(s, school["key"], url, new, root=school["root"]) == "written"
        assert chunks.refresh_page(s, school["key"], url, new, root=school["root"]) == "unchanged"
    assert chunk_texts(school)[url] == ["Master of Data Science\nTuition: A$47,000 per year (2027)"]
    assert pages_of(school)[url].snapshot_sha256 == new


def test_refresh_skips_a_page_with_no_school_row(school):
    sha = write_snapshot(school["root"], "no-such-school-key", "Master of X\nTuition: A$1", "https://x.example/a")
    with SessionLocal() as s:
        assert chunks.refresh_page(s, "no-such-school-key", "https://x.example/a", sha,
                                   root=school["root"]) == "no university"
        assert s.get(SnapshotPage, chunks.page_id_for("https://x.example/a")) is None


def test_a_missing_snapshot_is_reported_not_guessed(school):
    (school["root"] / school["key"] / f"{school['shas']['c']}.txt").unlink()
    report = ingest(school)
    assert report["missing_snapshots"] == 1
    assert f"{school['base']}/c" not in pages_of(school)


def test_prune_removes_pages_the_files_no_longer_cite(school):
    ingest(school)
    path = school["data_dir"] / f"{school['key']}.json"
    data = json.loads(path.read_text())
    data["programs"] = data["programs"][1:]  # drops page a and with it the shared fees page
    path.write_text(json.dumps(data))
    assert ingest(school)["pages_pruned"] == 0  # without --prune nothing is removed
    report = ingest(school, prune=True)
    assert report["pages_pruned"] == 2
    assert set(pages_of(school)) == {f"{school['base']}/b", f"{school['base']}/c"}


def test_measure_counts_what_ingest_would_store(school):
    m = chunks.measure(data_dir=school["data_dir"], root=school["root"], schools=[school["key"]])
    assert m["pages"] == 4 and m["missing_snapshots"] == 0
    assert m["chunks"] == 4
    assert m["chars_trimmed"] < m["chars_full"]


def test_a_collected_page_refreshes_its_chunks(school, monkeypatch):
    """The queue hook: a page the queue collects (done or unchanged) has its chunks refreshed."""
    from app.collect import queue

    calls = []
    monkeypatch.setattr(chunks, "refresh_page", lambda session, key, url, sha, root: calls.append((key, url, sha)) or "written")
    page = CollectPage(id=str(uuid.uuid4()), school_key=school["key"], url=f"{school['base']}/a",
                       program_name="Master of Data Science", state=PageState.DONE, snapshot_sha256="f" * 64, attempts=1)
    with SessionLocal() as s:
        s.add(page)
        s.commit()
        queue.refresh_chunks(s, s.get(CollectPage, page.id), root=school["root"])
    assert calls == [(school["key"], f"{school['base']}/a", "f" * 64)]


def test_a_failing_refresh_does_not_fail_the_page(school, monkeypatch):
    from app.collect import queue

    def boom(*a, **k):
        raise RuntimeError("disk gone")

    monkeypatch.setattr(chunks, "refresh_page", boom)
    page = CollectPage(id=str(uuid.uuid4()), school_key=school["key"], url=f"{school['base']}/a",
                       program_name="x", state=PageState.DONE, snapshot_sha256="f" * 64, attempts=1)
    with SessionLocal() as s:
        s.add(page)
        s.commit()
        assert queue.refresh_chunks(s, s.get(CollectPage, page.id), root=school["root"]) == "error"
        assert s.get(CollectPage, page.id).state == PageState.DONE
    with SessionLocal() as s:
        assert s.scalar(select(func.count()).select_from(CollectPage).where(CollectPage.id == page.id)) == 1


# ---- chunk embeddings (the P1 #4 plumbing, no key needed) ----------------------------------------


def test_the_chunk_backfill_embeds_each_chunk_once_and_ranks_by_vector(school, monkeypatch):
    from functools import partial

    from tests.test_hybrid_retrieval import FakeEmbeddings

    from app.agent import embeddings
    from app.models.snapshot import SnapshotChunkEmbedding

    ingest(school)
    real = embeddings.stale_chunks
    monkeypatch.setattr(embeddings, "stale_chunks", partial(real, school_keys=[school["key"]]))
    fake = FakeEmbeddings()
    report = embeddings.backfill(SessionLocal, fake, batch_size=2, chunks=True)
    assert report["target"] == "chunks" and report["embedded"] == 4 and report["stale"] == 4
    assert embeddings.backfill(SessionLocal, FakeEmbeddings(), batch_size=2, chunks=True)["embedded"] == 0
    with SessionLocal() as s:
        stored = s.scalar(select(func.count()).select_from(SnapshotChunkEmbedding)
                          .join(SnapshotChunk).join(SnapshotPage).where(SnapshotPage.school_key == school["key"]))
    assert stored == 4
    # A re-cut page's chunks are new rows: their vectors are made on the next run, the old ones went
    # with the old chunks.
    url = f"{school['base']}/a"
    new = write_snapshot(school["root"], school["key"], "\n".join(NAV + ["Master of Data Science", "Tuition: A$1"] + FOOT), url)
    with SessionLocal() as s:
        chunks.refresh_page(s, school["key"], url, new, root=school["root"])
    assert embeddings.backfill(SessionLocal, FakeEmbeddings(), batch_size=2, chunks=True)["embedded"] == 1


def test_a_bundle_carries_the_cited_text_without_local_paths(school, tmp_path):
    import tarfile

    out = tmp_path / "bundle.tgz"
    report = chunks.bundle(out, data_dir=school["data_dir"], root=school["root"], schools=[school["key"]])
    assert report["pages"] == 4 and report["missing_snapshots"] == 0
    with tarfile.open(out) as tar:
        names = sorted(tar.getnames())
        assert names == sorted(f"{school['key']}/{sha}.{ext}" for sha in school["shas"].values() for ext in ("txt", "json"))
        for name in names:
            body = tar.extractfile(name).read().decode()
            assert "text_path" not in body and str(school["root"]) not in body
    # Unpacked elsewhere, it ingests the same pages.
    other = tmp_path / "unpacked"
    with tarfile.open(out) as tar:
        tar.extractall(other, filter="data")
    with SessionLocal() as s:
        report = chunks.ingest(s, data_dir=school["data_dir"], root=other, schools=[school["key"]])
    assert report["pages_written"] == 4 and report["missing_snapshots"] == 0


def test_prune_keeps_a_cited_page_whose_snapshot_is_missing_here(school):
    ingest(school)
    (school["root"] / school["key"] / f"{school['shas']['c']}.txt").unlink()
    report = ingest(school, prune=True)
    assert report["pages_pruned"] == 0 and report["missing_snapshots"] == 1
    assert f"{school['base']}/c" in pages_of(school)


def test_the_same_text_at_a_new_snapshot_keeps_the_chunks_and_their_vectors(school):
    from app.models.program import EMBEDDING_DIM
    from app.models.snapshot import SnapshotChunkEmbedding

    ingest(school)
    url = f"{school['base']}/a"
    with SessionLocal() as s:
        before = s.scalars(select(SnapshotChunk.id).join(SnapshotPage).where(SnapshotPage.url == url)).all()
        for cid in before:
            s.add(SnapshotChunkEmbedding(chunk_id=cid, model="m", content_sha256="x", embedding=[0.0] * EMBEDDING_DIM))
        s.commit()
    # Other HTML, the same visible text: a new sha256, the same words.
    text = (school["root"] / school["key"] / f"{school['shas']['a']}.txt").read_text()
    new = write_snapshot(school["root"], school["key"], text, url + "?v=2")
    with SessionLocal() as s:
        assert chunks.refresh_page(s, school["key"], url, new, root=school["root"]) == "written"
        after = s.scalars(select(SnapshotChunk.id).join(SnapshotPage).where(SnapshotPage.url == url)).all()
        assert after == before
        assert s.get(SnapshotPage, chunks.page_id_for(url)).snapshot_sha256 == new
        assert s.scalar(select(func.count()).select_from(SnapshotChunkEmbedding)
                        .where(SnapshotChunkEmbedding.chunk_id.in_(before))) == len(before)
