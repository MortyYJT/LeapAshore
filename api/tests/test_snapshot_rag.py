"""Answering from official page chunks (openspec snapshot-rag D6-D9): routing, retrieval and its gate,
the quote check, the reply, and a whole turn through the API with a scripted model.

No test calls a model. The retrieval tests plant a school with pages and chunks of its own (test-only
ids and names); the API test replaces the chat model with one that returns a fixed function call.
"""

import asyncio
import json
import uuid
from datetime import UTC, datetime

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from sqlalchemy import delete

from app.agent import answer, evidence, intent, passages
from app.agent import graph as graph_module
from app.agent.answer import CitedSentence, PassageAnswer, Quote
from app.config import settings
from app.db import SessionLocal
from app.models.program import Program, University
from app.models.snapshot import SnapshotChunk, SnapshotPage
from app.models.source import Source

PREFIX = "test-rag-"


# ---- the quote check (no database) ----------------------------------------------------------------

CHUNKS = [
    "Master of Data Science\nTuition fees: A$53,000 per year (2027 entry).\nTwo letters of recommendation are required.",
    "Interviews\nShortlisted applicants are invited to an online interview in March.",
]


def sentence(text, *quotes):
    return CitedSentence(text=text, citations=[Quote(passage=n, quote=q) for n, q in quotes])


def test_a_verbatim_quote_with_its_numbers_passes():
    reply = PassageAnswer(sentences=[
        sentence("数据科学硕士 2027 年入学的学费是每年 53,000 澳元。", (1, "Tuition fees: A$53,000 per year (2027 entry).")),
        sentence("需要 2 封推荐信。", (1, "Two letters of recommendation are required")),
        sentence("入围的申请人会在 3 月参加线上面试。", (2, "invited to an online interview in March")),
    ])
    checked = answer.verify(reply, CHUNKS)
    assert [s.ok for s in checked.sentences] == [True, True, True]
    assert checked.quotes == checked.quotes_passed == 3


def test_only_checked_sentences_go_to_the_support_check_with_their_quotes_and_pages():
    reply = PassageAnswer(sentences=[
        sentence("学费是每年 53,000 澳元。", (1, "Tuition fees: A$53,000 per year (2027 entry).")),
        sentence("学费是每年 99,000 澳元。", (1, "Tuition fees: A$99,000 per year")),
        sentence("入围者 3 月参加线上面试。", (2, "invited to an online interview in March")),
    ])
    checked = answer.verify(reply, CHUNKS)
    pages = [{"school": "Uni", "program": "Master of Data Science", "url": "https://u.test/mds"},
             {"school": "Uni", "program": None, "title": "How to apply", "url": "https://u.test/apply"}]
    claims = answer.support_claims(checked, pages)
    assert [c.id for c in claims] == [1, 2]
    assert claims[0].quotes == [("Uni, Master of Data Science", "Tuition fees: A$53,000 per year (2027 entry).")]
    assert claims[1].quotes == [("Uni, school-wide page: How to apply", "invited to an online interview in March")]

    from app.collect.faithful import Judgement
    answer.apply_support(checked, Judgement(verdicts={1: "ok", 2: "unsupported: x"}))
    assert [s.text for s in checked.kept] == ["学费是每年 53,000 澳元。"]
    assert checked.summary()["reasons"]["quote_does_not_support"] == 1


def test_quotes_are_compared_after_folding_spaces_quotes_and_case():
    reply = PassageAnswer(sentences=[sentence("学费按年收取。", (1, "TUITION   fees: a$53,000 per year"))])
    assert answer.verify(reply, CHUNKS).sentences[0].ok


@pytest.mark.parametrize("bad, reason", [
    (sentence("学费是每年 53,000 澳元。"), "no_citation"),
    (sentence("学费是每年 53,000 澳元。", (3, "Tuition fees: A$53,000 per year")), "unknown_passage"),
    (sentence("需要推荐信。", (1, "Two letters")), "quote_too_short"),
    (sentence("学费是每年 55,000 澳元。", (1, "Tuition fees: A$55,000 per year")), "quote_not_in_passage"),
    (sentence("学费是每年 55,000 澳元。", (1, "Tuition fees: A$53,000 per year")), "number_not_in_quotes"),
    # A paraphrase is not a quote, even when it says the same thing.
    (sentence("需要两封推荐信。", (1, "You need two recommendation letters")), "quote_not_in_passage"),
    # Words stitched together from two places are not on the page.
    (sentence("需要推荐信和面试。", (1, "Two letters of recommendation and an online interview")),
     "quote_not_in_passage"),
])
def test_a_sentence_that_fails_a_check_is_dropped(bad, reason):
    good = sentence("需要 2 封推荐信。", (1, "Two letters of recommendation are required"))
    checked = answer.verify(PassageAnswer(sentences=[good, bad]), CHUNKS)
    assert [s.ok for s in checked.sentences] == [True, False]
    assert reason in checked.sentences[1].reasons
    assert [s.text for s in checked.kept] == ["需要 2 封推荐信。"]


def test_one_failing_quote_drops_the_whole_sentence():
    both = sentence("学费是每年 53,000 澳元，需要面试。", (1, "Tuition fees: A$53,000 per year"),
                    (2, "an interview is compulsory for everyone"))
    checked = answer.verify(PassageAnswer(sentences=[both]), CHUNKS)
    assert not checked.sentences[0].ok and checked.quotes_passed == 1 and checked.quotes == 2


def test_a_marker_the_model_wrote_is_not_a_number():
    reply = PassageAnswer(sentences=[sentence("需要推荐信[1]。", (1, "Two letters of recommendation are required"))])
    assert answer.verify(reply, CHUNKS).sentences[0].ok


def test_european_thousands_and_month_names_count_as_numbers():
    chunks = ["Studiengebühren: 3.000 € pro Semester", "Deadline: 15 January 2027"]
    reply = PassageAnswer(sentences=[
        sentence("学费每学期 3000 欧元。", (1, "Studiengebühren: 3.000 € pro Semester")),
        sentence("截止日期是 2027 年 1 月 15 日。", (2, "Deadline: 15 January 2027")),
    ])
    assert all(s.ok for s in answer.verify(reply, chunks).sentences)


PASSAGES = [
    {"chunk_id": "c1", "text": CHUNKS[0], "url": "https://u.example/mds", "title": "Master of Data Science",
     "school": "示例大学", "program": "Master of Data Science", "fetched_at": "2026-10-20T08:00:00+00:00"},
    {"chunk_id": "c2", "text": CHUNKS[1], "url": "https://u.example/admissions", "title": None,
     "school": "示例大学", "program": None, "fetched_at": "2026-10-21T08:00:00+00:00"},
]


def test_the_reply_numbers_citations_in_order_of_use_and_says_it_is_unverified():
    reply = PassageAnswer(sentences=[
        sentence("入围者会被邀请参加线上面试。", (2, "invited to an online interview")),
        sentence("学费是每年 53,000 澳元。", (1, "Tuition fees: A$53,000 per year")),
        sentence("学费是每年 99,000 澳元。", (1, "Tuition fees: A$99,000 per year")),
    ])
    text, cites = answer.render(answer.verify(reply, CHUNKS), PASSAGES)
    assert text.startswith("入围者会被邀请参加线上面试。[1]学费是每年 53,000 澳元。[2]")
    assert "99,000" not in text
    assert "待核验" in text and "2026-10-20" in text and "2026-10-21" in text
    assert "另有 1 句" in text
    assert [(c["n"], c["url"]) for c in cites] == [(1, "https://u.example/admissions"), (2, "https://u.example/mds")]
    assert all(c["status"] == "待核验" for c in cites)


def test_nothing_sourced_left_is_a_refusal_with_the_pages():
    text = answer.refusal_after_check(PASSAGES)
    assert "不作判断" in text and "https://u.example/mds" in text


def test_the_prompt_numbers_the_passages_and_names_their_pages():
    prompt = answer.prompt_for("学费多少？", PASSAGES)
    assert "[1] 示例大学｜Master of Data Science（项目页面）｜https://u.example/mds｜抓取于 2026-10-20" in prompt
    assert "[2] 示例大学｜学校官方页面｜https://u.example/admissions｜抓取于 2026-10-21" in prompt
    assert CHUNKS[1] in prompt


# ---- topics and routing ---------------------------------------------------------------------------


@pytest.mark.parametrize("question, keys", [
    ("悉尼大学数据科学硕士学费多少？", ["tuition"]),
    ("要几封推荐信？需要面试吗", ["recommendation", "interview"]),
    ("What are the tuition fees?", ["tuition"]),
    ("Do I need referees?", ["recommendation"]),
    ("雅思要求多少", []),
    ("推荐几个学校", []),
])
def test_page_topics_are_found_by_the_applicants_words(question, keys):
    assert [t.key for t in passages.detect_topics(question)] == keys


def test_only_requirement_and_general_questions_naming_a_school_take_the_pages(monkeypatch):
    monkeypatch.setattr(passages, "names_a_school", lambda session, q: "某大学" in q)
    assert [t.key for t in passages.route(None, "某大学学费多少", "官方要求核验")] == ["tuition"]
    assert [t.key for t in passages.route(None, "某大学学费多少", "通用问答")] == ["tuition"]
    assert passages.route(None, "某大学学费多少", "规划") == []
    assert passages.route(None, "我的预算是学费 30 万以内", "资料补充") == []
    assert passages.route(None, "学费一般多少", "通用问答") == []  # no school: unchanged route


def test_the_graph_routes_page_topics_to_the_passages():
    assert graph_module.route_by_intent({"intent": "官方要求核验", "page_topics": ["tuition"]}) == "passages"
    assert graph_module.route_by_intent({"intent": "官方要求核验", "page_topics": []}) == "requirements"
    nodes = set(graph_module.build_graph().get_graph().nodes)
    assert {"retrieve_passages", "answer_passages"} <= nodes


# ---- retrieval and the gate (database) ------------------------------------------------------------


@pytest.fixture
def school(require_db):
    """One school: a data science page, a finance page and a shared admissions page, plus a second
    school with no pages."""
    uid, empty = f"{PREFIX}{uuid.uuid4().hex[:6]}", f"{PREFIX}{uuid.uuid4().hex[:6]}"
    made = {"pages": [], "programs": [], "sources": []}
    with SessionLocal() as s:
        s.add(University(id=uid, name="切片检索测试大学", name_en="Ragtest University", country="美国"))
        s.add(University(id=empty, name="无页面测试大学", name_en="Nopages Test University", country="美国"))
        s.flush()
        progs = {}
        for key, name, area in (("mds", "Master of Data Science", "计算机与数据"), ("fin", "Master of Finance", "商科与金融")):
            sid = str(uuid.uuid4())
            s.add(Source(id=sid, url=f"https://ragtest.example/{key}-{sid}", title=name))
            s.flush()
            pid = f"{PREFIX}{key}-{uuid.uuid4().hex[:6]}"
            s.add(Program(id=pid, university_id=uid, name=name, name_en=name, field=area, source_id=sid))
            progs[key] = pid
            made["programs"].append(pid)
            made["sources"].append(sid)
        s.flush()
        pages = {
            "mds": (progs["mds"], ["Master of Data Science overview. Tuition fee: US$61,000 per year.",
                                   "Admission: two letters of recommendation required."]),
            "fin": (progs["fin"], ["Master of Finance. Tuition fee: US$75,000 per year.",
                                   "An interview is part of the selection."]),
            "adm": (None, ["Graduate admissions. All programs may invite applicants to an interview.",
                           "Application fee: US$90."]),
        }
        for key, (pid, texts) in pages.items():
            page_id = str(uuid.uuid4())
            s.add(SnapshotPage(id=page_id, url=f"https://ragtest.example/{key}/{page_id}", school_key=uid,
                               university_id=uid, program_id=pid, title=None, snapshot_sha256="0" * 64,
                               fetched_at=datetime(2026, 10, 20, tzinfo=UTC), content_sha256="0" * 64,
                               chunker="test", chunk_count=len(texts)))
            s.flush()
            for n, text in enumerate(texts):
                s.add(SnapshotChunk(id=str(uuid.uuid4()), page_id=page_id, ordinal=n, text=text, content_sha256="x"))
            made["pages"].append(page_id)
        s.commit()
    yield {"uid": uid, "empty": empty, **made}
    with SessionLocal() as s:
        s.execute(delete(SnapshotPage).where(SnapshotPage.id.in_(made["pages"])))
        s.execute(delete(Program).where(Program.id.in_(made["programs"])))
        s.execute(delete(Source).where(Source.id.in_(made["sources"])))
        s.execute(delete(University).where(University.id.in_([uid, empty])))
        s.commit()


def topics(*keys):
    return [t for t in passages.detect_topics("学费 推荐信 面试") if t.key in keys]


def test_a_named_subject_reads_its_programs_pages_and_the_shared_ones(school):
    with SessionLocal() as s:
        found = passages.search_passages(s, "切片检索测试大学数据科学硕士学费多少", topics("tuition"))
    texts = [p.text for p in found.passages]
    assert any("61,000" in t for t in texts) and any("Application fee" in t for t in texts)
    # Another programme's fee is never evidence for this one.
    assert not any("75,000" in t for t in texts)
    assert found.passages[0].program == "Master of Data Science"


def test_no_subject_reads_every_page_of_the_school(school):
    with SessionLocal() as s:
        found = passages.search_passages(s, "切片检索测试大学要面试吗", topics("interview"))
    assert {p.text for p in found.passages} == {"An interview is part of the selection.",
                                                 "Graduate admissions. All programs may invite applicants to an interview."}


def test_a_topic_no_page_states_is_refused_with_counts(school):
    with SessionLocal() as s:
        update = passages.gate(s, "切片检索测试大学数据科学硕士要面试吗？", topics("interview"))
    # The shared admissions page mentions an interview, so it is found; the finance page is not read.
    assert update["evidence_strong"] and all("Finance" not in p["text"] for p in update["passages"])
    with SessionLocal() as s:
        update = passages.gate(s, "切片检索测试大学金融硕士要几封推荐信？", topics("recommendation"))
    assert update["evidence_strong"] is False and update["refusal"] == "no_passage"
    assert "2 个相关官方页面" in update["refusal_text"] and "推荐信" in update["refusal_text"]


def test_a_school_with_no_pages_is_refused_as_not_collected(school):
    with SessionLocal() as s:
        update = passages.gate(s, "无页面测试大学学费多少", topics("tuition"))
    assert update["refusal"] == "school_not_collected" and "无页面测试大学" in update["refusal_text"]


def test_vector_rankings_fall_back_to_full_text_without_a_question_vector(school):
    with SessionLocal() as s:
        found = passages.search_passages(s, "切片检索测试大学数据科学学费", topics("tuition"), ranking="hybrid")
    assert found.ranking == "fts" and found.passages


def test_at_most_two_passages_come_from_one_page(school):
    with SessionLocal() as s:
        page = SnapshotPage(id=str(uuid.uuid4()), url=f"https://ragtest.example/long/{uuid.uuid4()}",
                            school_key=school["uid"], university_id=school["uid"], program_id=None, title=None,
                            snapshot_sha256="0" * 64, content_sha256="0" * 64, chunker="test", chunk_count=4)
        s.add(page)
        s.flush()
        for n in range(4):
            s.add(SnapshotChunk(id=str(uuid.uuid4()), page_id=page.id, ordinal=n, text=f"Tuition fee note {n}.",
                                content_sha256="x"))
        s.commit()
        school["pages"].append(page.id)
        found = passages.search_passages(s, "切片检索测试大学学费", topics("tuition"))
    by_page = {}
    for p in found.passages:
        by_page[p.url] = by_page.get(p.url, 0) + 1
    assert max(by_page.values()) <= passages.PER_PAGE


# ---- a whole turn -----------------------------------------------------------------------------------


class Answering(BaseChatModel):
    """Returns one fixed `PassageAnswer` function call, and to the support check (`Verdicts`) the given
    verdicts, by default backing every sentence."""

    arguments: dict
    verdicts: list | None = None
    tool: str = "PassageAnswer"

    @property
    def _llm_type(self) -> str:
        return "answering"

    def bind_tools(self, tools, **kwargs):
        name = getattr(tools[0], "__name__", None) or tools[0].get("name") or "PassageAnswer"
        return self.model_copy(update={"tool": name})

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if self.tool == "Verdicts":
            verdicts = self.verdicts if self.verdicts is not None else [
                {"id": i, "supported": True} for i in range(1, 20)]
            args = {"verdicts": verdicts}
        else:
            args = self.arguments
        call = {"name": self.tool, "args": args, "id": "call-1"}
        message = AIMessage(content="", tool_calls=[call],
                            usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120})
        return ChatResult(generations=[ChatGeneration(message=message)])


def run_turn(monkeypatch, question, arguments, verdicts=None):
    from fastapi.testclient import TestClient

    from app.main import app

    async def requirement(query, history):
        return {"intent": "官方要求核验", "confidence": 0.9}

    monkeypatch.setattr(settings, "chat_api_key", "test-key")
    monkeypatch.setattr(intent, "classify", requirement)
    monkeypatch.setattr(graph_module, "get_chat_model",
                        lambda **kwargs: Answering(arguments=arguments, verdicts=verdicts))
    monkeypatch.setattr(settings, "advisor_subject_limits", "1000/60")
    monkeypatch.setattr(settings, "advisor_ip_limits", "1000/60")
    # Not `with TestClient(...)`: its shutdown would close the shared checkpointer pool for later tests.
    response = TestClient(app).post("/api/advisor/chat", json={"conversationId": f"rag-{uuid.uuid4().hex[:8]}",
                                                                "message": question})
    return [json.loads(line[5:]) for line in response.text.split("\n\n") if line.startswith("data:")]


def test_a_turn_shows_only_the_checked_sentences(school, monkeypatch):
    args = {"sentences": [
        {"text": "数据科学硕士学费每年 61,000 美元。",
         "citations": [{"passage": 1, "quote": "Tuition fee: US$61,000 per year."}]},
        {"text": "学费每年 59,000 美元。", "citations": [{"passage": 1, "quote": "Tuition fee: US$59,000 per year."}]},
    ]}
    events = run_turn(monkeypatch, "切片检索测试大学数据科学硕士学费多少？", args)
    kinds = [e["type"] for e in events]
    assert kinds[:2] == ["intent", "citations"] and kinds[-1] == "done"
    citations = next(e for e in events if e["type"] == "citations")
    assert citations["gate"] == "pass" and len(citations["citations"]) == 1
    text = "".join(e["text"] for e in events if e["type"] == "token")
    assert "61,000" in text and "59,000" not in text and "另有 1 句" in text


def test_a_sentence_whose_quote_does_not_back_it_is_dropped_after_the_verbatim_check(school, monkeypatch):
    args = {"sentences": [
        {"text": "数据科学硕士学费每年 61,000 美元。",
         "citations": [{"passage": 1, "quote": "Tuition fee: US$61,000 per year."}]},
        {"text": "这个学费包含住宿，每年 61,000 美元。",
         "citations": [{"passage": 1, "quote": "Tuition fee: US$61,000 per year."}]},
    ]}
    verdicts = [{"id": 1, "supported": True}, {"id": 2, "supported": False, "unsupported": "包含住宿"}]
    events = run_turn(monkeypatch, "切片检索测试大学数据科学硕士学费多少？", args, verdicts)
    text = "".join(e["text"] for e in events if e["type"] == "token")
    assert "数据科学硕士学费每年 61,000 美元" in text and "住宿" not in text and "另有 1 句" in text


def test_a_support_check_without_an_answer_refuses_rather_than_show_unchecked_sentences(school, monkeypatch):
    args = {"sentences": [{"text": "数据科学硕士学费每年 61,000 美元。",
                           "citations": [{"passage": 1, "quote": "Tuition fee: US$61,000 per year."}]}]}
    events = run_turn(monkeypatch, "切片检索测试大学数据科学硕士学费多少？", args, verdicts=[])
    citations = next(e for e in events if e["type"] == "citations")
    assert citations["gate"] == "refuse"
    text = "".join(e["text"] for e in events if e["type"] == "token")
    assert "不作判断" in text and "61,000" not in text


def test_a_turn_with_nothing_checkable_refuses(school, monkeypatch):
    args = {"sentences": [{"text": "学费大约 6 万美元。", "citations": []}]}
    events = run_turn(monkeypatch, "切片检索测试大学数据科学硕士学费多少？", args)
    citations = next(e for e in events if e["type"] == "citations")
    assert citations["gate"] == "refuse" and citations["citations"] == []
    text = "".join(e["text"] for e in events if e["type"] == "token")
    assert "不作判断" in text and "6 万" not in text


def test_a_gate_refusal_never_calls_the_model(school, monkeypatch):
    events = run_turn(monkeypatch, "无页面测试大学学费多少？", {"sentences": []})
    citations = next(e for e in events if e["type"] == "citations")
    assert citations["gate"] == "refuse"
    assert "还没有收录官方页面" in "".join(e["text"] for e in events if e["type"] == "token")


def test_a_question_vector_ranks_the_chunks_and_hybrid_fuses_both_lists(school):
    from sqlalchemy import select

    from app.models.program import EMBEDDING_DIM
    from app.models.snapshot import SnapshotChunkEmbedding

    def one_hot(i):
        v = [0.0] * EMBEDDING_DIM
        v[i] = 1.0
        return v

    with SessionLocal() as s:
        rows = s.execute(select(SnapshotChunk.id, SnapshotChunk.text).where(SnapshotChunk.page_id.in_(school["pages"]))).all()
        for i, (cid, text) in enumerate(sorted(rows, key=lambda r: r.text)):
            s.add(SnapshotChunkEmbedding(chunk_id=cid, model=settings.embed_model, content_sha256="x",
                                         embedding=one_hot(i)))
        s.commit()
        target = sorted(rows, key=lambda r: r.text).index(next(r for r in rows if "part of the selection" in r.text))
        found = passages.search_passages(s, "切片检索测试大学要面试吗", topics("interview"), ranking="vector",
                                         query_vector=one_hot(target))
        assert found.ranking == "vector" and found.passages[0].text == "An interview is part of the selection."
        hybrid = passages.search_passages(s, "切片检索测试大学要面试吗", topics("interview"), ranking="hybrid",
                                          query_vector=one_hot(target))
    assert hybrid.ranking == "hybrid" and hybrid.passages[0].text == "An interview is part of the selection."


# ---- review of #60 --------------------------------------------------------------------------------


def test_the_modal_may_does_not_vouch_for_a_five():
    chunks = ["Applicants may be invited to an interview."]
    reply = PassageAnswer(sentences=[sentence("面试可能在 5 月进行。", (1, "Applicants may be invited to an interview"))])
    assert answer.verify(reply, chunks).sentences[0].reasons == ["number_not_in_quotes"]


def test_a_chinese_count_must_be_in_the_quotes():
    reply = PassageAnswer(sentences=[
        sentence("需要三封推荐信。", (1, "Two letters of recommendation are required")),
        sentence("需要两封推荐信。", (1, "Two letters of recommendation are required")),
        sentence("一般在线上进行面试。", (2, "invited to an online interview in March")),
        sentence("第二轮是一次线上面试。", (2, "invited to an online interview in March")),
    ])
    checked = answer.verify(reply, CHUNKS)
    assert [s.ok for s in checked.sentences] == [False, True, True, True]


def test_a_vector_never_lets_in_a_chunk_that_does_not_state_the_topic(school):
    from sqlalchemy import select

    from app.models.program import EMBEDDING_DIM
    from app.models.snapshot import SnapshotChunkEmbedding

    def one_hot(i):
        v = [0.0] * EMBEDDING_DIM
        v[i] = 1.0
        return v

    with SessionLocal() as s:
        rows = s.execute(select(SnapshotChunk.id, SnapshotChunk.text).where(SnapshotChunk.page_id.in_(school["pages"]))).all()
        for i, (cid, _) in enumerate(rows):
            s.add(SnapshotChunkEmbedding(chunk_id=cid, model=settings.embed_model, content_sha256="x", embedding=one_hot(i)))
        s.commit()
        off_topic = next(i for i, r in enumerate(rows) if "letters of recommendation" in r.text)
        for ranking in ("vector", "hybrid"):
            found = passages.search_passages(s, "切片检索测试大学要面试吗", topics("interview"), ranking=ranking,
                                             query_vector=one_hot(off_topic))
            assert found.passages and all("interview" in p.text for p in found.passages)


@pytest.mark.parametrize("text, numbers", [
    ("二十天内", {"20"}), ("三十天内提交", {"30"}), ("需要十二个月工作经验", {"12"}), ("十五年", {"15"}),
    ("第十二轮", set()), ("二〇二六年入学", {"2026"}), ("一百二十个学分", {"120"}), ("两封推荐信", {"2"}),
    ("一次额外面试", set()), ("十一个月", {"11"}), ("学费三万五千美元", {"35000"}), ("一万欧元", {"10000"}),
])
def test_chinese_numbers_are_read_whole(text, numbers):
    assert answer.numbers_in(text) == numbers


def test_a_chinese_compound_needs_its_own_number_quoted():
    chunks = ["Applications close in October.", "12 months of work experience is required."]
    reply = PassageAnswer(sentences=[
        sentence("需在三十天内提交申请。", (1, "Applications close in October.")),
        sentence("需要十二个月的工作经验。", (2, "12 months of work experience is required")),
        sentence("可以申请两次。", (2, "12 months of work experience is required")),
    ])
    assert [s.ok for s in answer.verify(reply, chunks).sentences] == [False, True, False]
