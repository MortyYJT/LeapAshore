"""Hybrid retrieval (openspec hybrid-retrieval): full text, vectors, RRF, the country filter, and the
embedding backfill, against a real database.

No test calls SiliconFlow. Vectors are planted by hand (one-hot, so the expected order is obvious) or
made by `FakeEmbeddings`, which hashes words into 1024 dimensions; the HTTP client is exercised through
`httpx.MockTransport`. The fixture's schools have test-only ids and names, so the development
catalogue's own rows never enter the ranking.
"""

import importlib.util
import json
import uuid
from pathlib import Path

import httpx
import pytest
from sqlalchemy import delete, func, select

from app.agent import embeddings, evidence
from app.config import settings
from app.db import SessionLocal
from app.models.program import EMBEDDING_DIM, SEARCH_TSV_SQL, Program, ProgramEmbedding, University
from app.models.source import Source

pytestmark = pytest.mark.usefixtures("require_db")

PREFIX = "test-hybrid-"
EDU = "教育与社会科学"
UNIVERSITIES = [
    (f"{PREFIX}tc", "混检测试大学", "Hybrid Test University", "美国"),
    (f"{PREFIX}uk", "同名测试大学（英国）", "Samename Test University", "英国"),
    (f"{PREFIX}au", "同名测试大学（澳大利亚）", "Samename Test University, Australia", "澳大利亚"),
]
# key -> (university, English name, field)
PROGRAMS = {
    "tesol": (f"{PREFIX}tc", "TESOL (MA)", EDU),
    "tesol_long": (f"{PREFIX}tc", "Teaching TESOL and Applied Linguistics (MA)", EDU),
    "teacher": (f"{PREFIX}tc", "Teacher Education (MA)", EDU),
    "maths": (f"{PREFIX}tc", "Teaching Mathematics (MA)", EDU),
    "uk_cs": (f"{PREFIX}uk", "MSc Computer Science", "计算机与数据"),
    "au_cs": (f"{PREFIX}au", "Master of Computer Science", "计算机与数据"),
}


def one_hot(i: int) -> list[float]:
    v = [0.0] * EMBEDDING_DIM
    v[i] = 1.0
    return v


def near(i: int, j: int, weight: float) -> list[float]:
    """Mostly dimension i, a little of j: closer to one_hot(i) the smaller `weight` is."""
    v = [0.0] * EMBEDDING_DIM
    v[i], v[j] = 1.0, weight
    return v


@pytest.fixture
def catalogue():
    ids, source_ids, made = {}, [], []
    with SessionLocal() as s:
        for uid, name, name_en, country in UNIVERSITIES:
            s.add(University(id=uid, name=name, name_en=name_en, country=country))
            made.append(uid)
        s.flush()
        for key, (uid, name, area) in PROGRAMS.items():
            sid, pid = str(uuid.uuid4()), f"{PREFIX}{key}-{uuid.uuid4().hex[:8]}"
            s.add(Source(id=sid, url=f"https://example.org/{PREFIX}{sid}", title=f"{name} (test)"))
            s.flush()
            s.add(Program(id=pid, university_id=uid, name=name, name_en=name, field=area, source_id=sid,
                          data_status="机器核对", english_requirement="IELTS 7.0"))
            ids[key] = pid
            source_ids.append(sid)
        s.commit()
    evidence._counts_cache.clear()
    yield ids
    with SessionLocal() as s:
        s.execute(delete(Program).where(Program.id.in_(ids.values())))
        s.execute(delete(Source).where(Source.id.in_(source_ids)))
        s.execute(delete(University).where(University.id.in_(made)))
        s.commit()
    evidence._counts_cache.clear()


def plant(vectors: dict[str, list[float]], ids: dict[str, str], model: str | None = None) -> None:
    with SessionLocal() as s:
        for key, vector in vectors.items():
            s.merge(ProgramEmbedding(program_id=ids[key], model=model or settings.embed_model,
                                     content_sha256="0" * 64, embedding=vector))
        s.commit()


def order(question: str, ranking: str, ids: dict[str, str], query_vector=None) -> list[str]:
    back = {v: k for k, v in ids.items()}
    with SessionLocal() as s:
        found = evidence.search_requirements(s, question, ranking=ranking, query_vector=query_vector)
    assert found.ranking == ranking or query_vector is None
    return [back[h.program.id] for h in found.hits]


QUESTION = "混检测试大学 TESOL 硕士要求"


def test_full_text_puts_the_program_the_applicant_named_first(catalogue):
    """The TESOL row first, the shorter of the two TESOL names before the longer one; the rest after,
    by name."""
    assert order(QUESTION, "fts", catalogue) == ["tesol", "tesol_long", "teacher", "maths"]


def test_vector_ranking_orders_by_cosine_distance(catalogue):
    plant({"tesol_long": near(0, 1, 0.1), "teacher": near(0, 1, 0.5), "tesol": near(0, 1, 1.0),
           "maths": one_hot(1)}, catalogue)
    assert order(QUESTION, "vector", catalogue, one_hot(0)) == ["tesol_long", "teacher", "tesol", "maths"]


def test_hybrid_fuses_the_two_lists_by_reciprocal_rank(catalogue):
    """Full text: tesol 1, tesol_long 2. Vectors: tesol_long 1, teacher 2, tesol 3, maths 4.
    RRF: tesol_long 1/62+1/61 > tesol 1/61+1/63 > teacher 1/62 > maths 1/64."""
    plant({"tesol_long": near(0, 1, 0.1), "teacher": near(0, 1, 0.5), "tesol": near(0, 1, 1.0),
           "maths": one_hot(1)}, catalogue)
    assert order(QUESTION, "hybrid", catalogue, one_hot(0)) == ["tesol_long", "tesol", "teacher", "maths"]


def test_a_row_without_a_vector_still_ranks_by_full_text(catalogue):
    """Only `teacher` has a vector: it and `tesol` each top one list (1/61, a tie broken by name), the
    second TESOL row follows on full text alone (1/62), and `maths` is in neither list."""
    plant({"teacher": one_hot(0)}, catalogue)
    assert order(QUESTION, "hybrid", catalogue, one_hot(0)) == ["tesol", "teacher", "tesol_long", "maths"]


def test_a_vector_of_another_model_is_ignored(catalogue):
    """`maths` matches the question's vector exactly, but under another model: no row has a vector for
    the configured one, so the vector list is empty and the order is by name."""
    plant({"maths": one_hot(0)}, catalogue, model="fake-other-model")
    try:
        assert order(QUESTION, "vector", catalogue, one_hot(0)) == ["tesol", "teacher", "maths", "tesol_long"]
    finally:
        with SessionLocal() as s:
            s.execute(delete(ProgramEmbedding).where(ProgramEmbedding.model == "fake-other-model"))
            s.commit()


def test_hybrid_without_a_question_vector_says_it_ranked_by_full_text(catalogue):
    with SessionLocal() as s:
        found = evidence.search_requirements(s, QUESTION, ranking="hybrid", query_vector=None)
    assert found.ranking == "fts"
    assert found.fts_terms == ["tesol"]


def test_every_ranking_returns_the_same_rows_when_k_covers_them(catalogue):
    """The ranking changes the order only; which rows may be evidence does not depend on it."""
    plant({k: one_hot(i) for i, k in enumerate(("tesol", "tesol_long", "teacher", "maths"))}, catalogue)
    sets = {r: set(order(QUESTION, r, catalogue, one_hot(2))) for r in evidence.RANKINGS}
    assert len({frozenset(v) for v in sets.values()}) == 1


def test_an_unknown_ranking_is_an_error(catalogue):
    with SessionLocal() as s, pytest.raises(ValueError):
        evidence.search_requirements(s, QUESTION, ranking="bm25")


# ---- country -----------------------------------------------------------------------------------


def schools_for(question: str) -> list[str]:
    with SessionLocal() as s:
        return evidence.search_requirements(s, question, ranking="fts").schools


def test_a_country_tells_two_schools_of_the_same_name_apart(catalogue):
    assert set(schools_for("同名测试大学计算机硕士要求")) == {f"{PREFIX}uk", f"{PREFIX}au"}
    assert schools_for("英国的同名测试大学计算机硕士要求") == [f"{PREFIX}uk"]
    assert schools_for("澳洲同名测试大学计算机硕士要求") == [f"{PREFIX}au"]


def test_a_country_never_drops_a_school_named_without_ambiguity(catalogue):
    """Found in review: "英国" removed every named school outside the UK, so "我在英国读本科，问港大和
    UCL" lost HKU silently. A country only chooses among schools that share the name it qualifies."""
    assert set(schools_for("我在英国读本科，想问混检测试大学和同名测试大学的计算机硕士要求")) == {
        f"{PREFIX}tc", f"{PREFIX}uk"}


def test_a_country_that_holds_none_of_the_named_schools_is_ignored(catalogue):
    assert schools_for("加拿大的混检测试大学 TESOL") == [f"{PREFIX}tc"]


def test_a_question_naming_only_a_country_is_still_refused(catalogue):
    with SessionLocal() as s:
        update = evidence.gate(s, "英国的计算机硕士要求", ranking="fts")
    assert update["evidence_strong"] is False
    assert update["refusal"] == "no_school"


# ---- the gate and the question's vector ---------------------------------------------------------


def test_the_gate_embeds_the_question_only_for_a_vector_ranking(catalogue, monkeypatch):
    calls = []
    monkeypatch.setattr(embeddings, "embed_query", lambda text: calls.append(text) or one_hot(0))
    with SessionLocal() as s:
        fts = evidence.gate(s, QUESTION, ranking="fts")
        hybrid = evidence.gate(s, QUESTION, ranking="hybrid")
    assert calls == [QUESTION]
    assert fts["trace"]["gate_signals"]["ranking"] == "fts"
    assert hybrid["trace"]["gate_signals"]["ranking"] == "hybrid"


def test_the_gate_answers_by_full_text_when_the_question_does_not_embed(catalogue, monkeypatch):
    monkeypatch.setattr(embeddings, "embed_query", lambda text: None)
    with SessionLocal() as s:
        update = evidence.gate(s, QUESTION, ranking="hybrid")
    assert update["evidence_strong"] is True
    assert update["trace"]["gate_signals"]["ranking"] == "fts"
    assert update["citations"][0]["programId"] == catalogue["tesol"]


def test_the_gate_uses_the_configured_ranking(catalogue, monkeypatch):
    monkeypatch.setattr(settings, "advisor_retrieval", "rules")
    with SessionLocal() as s:
        update = evidence.gate(s, QUESTION)
    assert update["trace"]["gate_signals"]["ranking"] == "rules"


def test_no_key_means_no_request(monkeypatch):
    monkeypatch.setattr(settings, "embed_api_key", "")
    assert embeddings.configured_client() is None
    assert embeddings.embed_query("港大计算机") is None


def test_a_failing_service_is_logged_and_returns_no_vector(caplog):
    client = embeddings.OpenAIEmbeddings("https://embed.test/v1", "BAAI/bge-m3", "k", 1.0,
                                         transport=httpx.MockTransport(lambda r: httpx.Response(503, text="busy")))
    assert embeddings.embed_query("港大计算机", client=client) is None
    assert "ranking by full text only" in caplog.text


# ---- the HTTP client ---------------------------------------------------------------------------


def test_the_client_posts_an_openai_embeddings_request_and_keeps_the_input_order():
    seen = {}

    def answer(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        # Out of order on purpose: the client must sort by `index`.
        data = [{"index": 1, "embedding": one_hot(1)}, {"index": 0, "embedding": one_hot(0)}]
        return httpx.Response(200, json={"data": data, "usage": {"prompt_tokens": 7, "total_tokens": 7}})

    client = embeddings.OpenAIEmbeddings("https://embed.test/v1/", "BAAI/bge-m3", "secret", 1.0,
                                         transport=httpx.MockTransport(answer))
    result = client.embed(["a", "b"])
    assert seen == {"url": "https://embed.test/v1/embeddings", "auth": "Bearer secret",
                    "body": {"model": "BAAI/bge-m3", "input": ["a", "b"], "encoding_format": "float"}}
    assert result.vectors == [one_hot(0), one_hot(1)]
    assert result.tokens == 7


def test_a_vector_of_the_wrong_size_is_an_error():
    client = embeddings.OpenAIEmbeddings(
        "https://embed.test/v1", "m", "k", 1.0,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0]}]})),
    )
    with pytest.raises(embeddings.EmbeddingError):
        client.embed(["a"])


# ---- the backfill ------------------------------------------------------------------------------


class FakeEmbeddings:
    """Hashes words into the vector, deterministically; can be told to fail after n calls."""

    def __init__(self, model: str = "fake-bge-m3", fail_after: int | None = None):
        self.model = model
        self.calls = 0
        self.texts: list[str] = []
        self.fail_after = fail_after

    def embed(self, texts: list[str]) -> embeddings.Embedded:
        if self.fail_after is not None and self.calls >= self.fail_after:
            raise embeddings.EmbeddingError("HTTP 429: rate limited")
        self.calls += 1
        self.texts.extend(texts)
        vectors = []
        for text in texts:
            v = [0.0] * EMBEDDING_DIM
            for word in text.lower().split():
                v[hash(word) % EMBEDDING_DIM] += 1.0
            vectors.append(v)
        return embeddings.Embedded(vectors, tokens=sum(len(t.split()) for t in texts))


@pytest.fixture
def only_fixture_programs(monkeypatch, catalogue):
    """Limit the backfill to the fixture's rows, so it never touches the development catalogue."""
    real = embeddings.stale_programs

    def scoped(session, model):
        return [p for p in real(session, model) if p.program_id.startswith(PREFIX)]

    monkeypatch.setattr(embeddings, "stale_programs", scoped)
    yield catalogue
    with SessionLocal() as s:
        s.execute(delete(ProgramEmbedding).where(ProgramEmbedding.model.like("fake-%")))
        s.commit()


def stored(model: str) -> dict[str, str]:
    with SessionLocal() as s:
        return dict(s.execute(
            select(ProgramEmbedding.program_id, ProgramEmbedding.content_sha256)
            .where(ProgramEmbedding.model == model, ProgramEmbedding.program_id.like(f"{PREFIX}%"))
        ).all())


def test_the_backfill_embeds_every_program_once(only_fixture_programs):
    fake = FakeEmbeddings()
    report = embeddings.backfill(SessionLocal, fake, batch_size=4)
    assert report["embedded"] == len(PROGRAMS) and report["batches"] == 2 and report["tokens"] > 0
    assert set(stored(fake.model)) == set(only_fixture_programs.values())
    again = FakeEmbeddings()
    assert embeddings.backfill(SessionLocal, again, batch_size=4)["embedded"] == 0
    assert again.calls == 0


def test_a_changed_program_is_embedded_again_and_only_it(only_fixture_programs):
    embeddings.backfill(SessionLocal, FakeEmbeddings(), batch_size=4)
    with SessionLocal() as s:
        s.get(Program, only_fixture_programs["teacher"]).name_en = "Teacher Education and Policy (MA)"
        s.commit()
    fake = FakeEmbeddings()
    report = embeddings.backfill(SessionLocal, fake, batch_size=4)
    assert report["embedded"] == 1
    assert fake.texts == ["Teacher Education and Policy (MA)\nTeacher Education (MA)\n教育与社会科学"]


def test_an_interrupted_backfill_keeps_what_it_stored_and_the_next_run_finishes(only_fixture_programs):
    first = embeddings.backfill(SessionLocal, FakeEmbeddings(fail_after=1), batch_size=4)
    assert first["embedded"] == 4 and "429" in first["error"]
    assert len(stored("fake-bge-m3")) == 4
    second = embeddings.backfill(SessionLocal, FakeEmbeddings(), batch_size=4)
    assert second["embedded"] == 2
    assert set(stored("fake-bge-m3")) == set(only_fixture_programs.values())


def test_a_new_model_replaces_every_vector(only_fixture_programs):
    embeddings.backfill(SessionLocal, FakeEmbeddings(), batch_size=8)
    report = embeddings.backfill(SessionLocal, FakeEmbeddings(model="fake-bge-m4"), batch_size=8)
    assert report["embedded"] == len(PROGRAMS)
    assert stored("fake-bge-m3") == {}


def test_a_dry_run_sends_nothing(only_fixture_programs):
    fake = FakeEmbeddings()
    report = embeddings.backfill(SessionLocal, fake, dry_run=True)
    assert report["stale"] == len(PROGRAMS) and report["characters"] > 0 and fake.calls == 0


def test_deleting_a_program_deletes_its_vector(only_fixture_programs):
    embeddings.backfill(SessionLocal, FakeEmbeddings(), batch_size=8)
    with SessionLocal() as s:
        s.execute(delete(Program).where(Program.id == only_fixture_programs["maths"]))
        s.commit()
        assert s.scalar(select(func.count()).select_from(ProgramEmbedding)
                        .where(ProgramEmbedding.program_id == only_fixture_programs["maths"])) == 0


# ---- schema and schedule -----------------------------------------------------------------------


def test_the_model_and_the_migration_generate_the_same_search_vector():
    path = next(Path(__file__).resolve().parents[1].glob("alembic/versions/e3a9c5d17b42_*.py"))
    spec = importlib.util.spec_from_file_location("revision_e3a9c5d17b42", path)
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    assert revision.SEARCH_TSV_SQL == SEARCH_TSV_SQL


def test_the_search_vector_follows_the_program_name(catalogue):
    with SessionLocal() as s:
        p = s.get(Program, catalogue["maths"])
        p.name_en = "Statistics (MS)"
        s.commit()
        assert s.scalar(select(Program.search_tsv.op("@@")(func.plainto_tsquery("english", "statistic")))
                        .where(Program.id == p.id)) is True


def test_the_beat_embeds_new_programs_every_hour(monkeypatch):
    from app import worker

    entry = worker.app.conf.beat_schedule["embed-programs"]
    assert entry["task"] == "maintenance.embed_programs"
    monkeypatch.setattr(settings, "embed_api_key", "")
    assert worker.embed_programs() == {"skipped": "EMBED_API_KEY is not set"}
