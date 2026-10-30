"""The summary faithfulness check: does each field's quote, on its own, state what its summary says?

No test calls a real model. `fixtures/faithful/ut-austin-mscs.json` is the program the task named (UT
Austin's MSCS, whose academic summary adds "Bachelor's degree or comparable foreign degree" to a quote
that only states a GPA) with the real DeepSeek response recorded for it on 2026-10-30; the tests replay
it over a mocked transport.
"""

import copy
import json
from pathlib import Path

import httpx
import pytest
from langchain_openai import ChatOpenAI
from sqlalchemy import delete

from app.collect import faithful as fa
from app.collect.changes import diff_fields
from app.collect.importer import import_school, program_id_for, source_id_for
from app.collect.verify import (
    MACHINE_CHECKED,
    NEEDS_HUMAN,
    SUMMARY_CHECK,
    SUMMARY_SHA,
    program_status,
    summary_verdict,
    usable,
    verify,
)
from app.models.program import Program, ProgramPrerequisite, University
from app.models.source import Source, SourceVersion

FIXTURES = Path(__file__).parent / "fixtures" / "faithful"
UT = json.loads((FIXTURES / "ut-austin-mscs.json").read_text(encoding="utf-8"))


def answering(*bodies: dict, seen: list | None = None) -> ChatOpenAI:
    """A ChatOpenAI whose upstream replies with each body in turn (the last one again after that)."""
    queue = list(bodies)

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(json.loads(request.content))
        return httpx.Response(200, json=queue.pop(0) if len(queue) > 1 else queue[0])

    return ChatOpenAI(model="deepseek-chat", base_url="https://model.test/v1", api_key="test", temperature=0,
                      max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def verdicts_body(verdicts: list[dict] | str) -> dict:
    """A response in the recorded shape whose function call carries `verdicts` (or raw arguments)."""
    body = copy.deepcopy(UT["response"])
    arguments = verdicts if isinstance(verdicts, str) else json.dumps({"verdicts": verdicts})
    body["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = arguments
    return body


def ut_program() -> dict:
    return copy.deepcopy(UT["program"])


# ---- UT Austin: the record the task names -----------------------------------------------------------


def test_ut_austin_mscs_academic_summary_is_downgraded_and_the_scores_stay():
    program = ut_program()
    assert program["status"] == MACHINE_CHECKED  # verify alone passed it: the quote is verbatim

    result = fa.check_program(program, UT["school_name_en"], answering(UT["response"]))

    academic = program["fields"]["academic"]
    assert academic[SUMMARY_CHECK].startswith("unsupported:") and "Bachelor" in academic[SUMMARY_CHECK]
    assert not usable(academic)
    assert academic["text"] == UT["program"]["fields"]["academic"]["text"]  # kept, never edited
    assert usable(program["fields"]["toefl"]) and usable(program["fields"]["ielts"])
    assert program["status"] == NEEDS_HUMAN
    assert result.model == "deepseek-flash" and result.usage["input_tokens"] > 0


def test_the_ut_austin_prompt_asks_about_the_claim_and_its_quote_only():
    seen = []
    fa.check_program(ut_program(), UT["school_name_en"], answering(UT["response"], seen=seen))
    prompt = seen[0]["messages"][0]["content"]
    academic = UT["program"]["fields"]["academic"]
    assert academic["text"] in prompt and academic["quote"] in prompt
    assert "Minimum TOEFL iBT: overall 79" in prompt and "Minimum IELTS: overall 6.5" in prompt
    assert "Do not use what you know about the school" in prompt
    assert seen[0]["tools"][0]["function"]["name"] == "Verdicts"


@pytest.fixture
def cleanup(db_session):
    key, url, name = "test-faithful-university", "https://example.test/mscs", "MSCS"
    yield key, url, name
    pid = program_id_for(key, {"url": url, "name": name})
    db_session.rollback()
    db_session.execute(delete(ProgramPrerequisite).where(ProgramPrerequisite.program_id == pid))
    db_session.execute(delete(Program).where(Program.id == pid))
    db_session.execute(delete(SourceVersion).where(SourceVersion.source_id == source_id_for(url)))
    db_session.execute(delete(Source).where(Source.id == source_id_for(url)))
    db_session.execute(delete(University).where(University.id == key))
    db_session.commit()


def test_a_downgraded_summary_is_not_imported_and_an_earlier_import_of_it_is_cleared(db_session, require_db,
                                                                                    cleanup, tmp_path):
    key, url, name = cleanup
    program = ut_program()
    program.update(url=url, name=name)
    data = {"school_key": key, "school_name_en": "Test Faithful University", "country": "United States",
            "listing_urls": ["https://example.test/"], "programs": [program]}
    schools = {key: {"school_key": key, "country": "United States"}}
    pid = program_id_for(key, program)

    import_school(db_session, copy.deepcopy(data), schools, root=tmp_path)  # before the check
    row = db_session.get(Program, pid)
    assert row.academic_requirement.startswith("Bachelor's degree") and row.data_status == MACHINE_CHECKED

    fa.check_program(program, UT["school_name_en"], answering(UT["response"]))
    import_school(db_session, data, schools, root=tmp_path)
    db_session.expire_all()
    row = db_session.get(Program, pid)
    assert row.academic_requirement is None and row.academic_source_url is None
    assert row.english_requirement == "IELTS 6.5；TOEFL iBT 79"
    assert row.data_status == "待核验"


def test_a_program_whose_every_summary_is_downgraded_is_still_rewritten(db_session, require_db, cleanup, tmp_path):
    key, url, name = cleanup
    program = ut_program()
    program.update(url=url, name=name)
    program["fields"] = {"academic": program["fields"]["academic"]}
    data = {"school_key": key, "school_name_en": "Test Faithful University", "country": "United States",
            "listing_urls": ["https://example.test/"], "programs": [program]}
    schools = {key: {"school_key": key, "country": "United States"}}
    import_school(db_session, copy.deepcopy(data), schools, root=tmp_path)
    fa.check_program(program, UT["school_name_en"], answering(UT["response"]))
    import_school(db_session, data, schools, root=tmp_path)
    db_session.expire_all()
    row = db_session.get(Program, program_id_for(key, program))
    assert row.academic_requirement is None and row.data_status == "待核验"


# ---- the verdict on the item -------------------------------------------------------------------------


def judged_item(verdict: str) -> dict:
    item = {"text": "GPA 3.0", "quote": "a GPA of 3.0", "check": "ok"}
    fa.set_summary_verdict(item, verdict)
    return item


def test_a_verdict_counts_only_while_the_summary_and_quote_it_judged_are_unchanged():
    item = judged_item("unsupported: x")
    assert summary_verdict(item) == "unsupported: x" and not usable(item)
    item["text"] = "GPA of 3.0 or higher"
    assert summary_verdict(item) is None and usable(item)  # stale: unjudged again
    item = judged_item("unsupported: x")
    item["quote"] = "a GPA of 3.0 or higher"
    assert summary_verdict(item) is None


def test_a_failed_quote_is_never_usable_whatever_the_summary_verdict():
    item = judged_item("ok")
    item["check"] = "quote not found in snapshot"
    assert not usable(item)


def test_an_item_never_judged_is_usable_as_before():
    assert usable({"text": "GPA 3.0", "quote": "a GPA of 3.0", "check": "ok"})


def test_verify_keeps_a_current_verdict_and_drops_a_stale_one(tmp_path):
    folder = tmp_path / "s"
    folder.mkdir()
    (folder / f"{'a' * 64}.txt").write_text("Requirements: a GPA of 3.0 and IELTS 6.5 overall.", encoding="utf-8")
    current, stale = judged_item("unsupported: added degree"), judged_item("unsupported: x")
    stale["text"] = "edited"
    data = {"school_key": "s", "school_name_en": "S", "programs": [
        {"name": "A", "url": "https://s.test/a", "snapshot_sha256": "a" * 64, "fields": {"academic": current}},
        {"name": "B", "url": "https://s.test/b", "snapshot_sha256": "a" * 64, "fields": {"academic": stale}},
    ]}
    out = verify(data, tmp_path)
    a, b = out["programs"]
    assert a["fields"]["academic"][SUMMARY_CHECK] == "unsupported: added degree" and a["status"] == NEEDS_HUMAN
    assert SUMMARY_CHECK not in b["fields"]["academic"] and SUMMARY_SHA not in b["fields"]["academic"]
    assert b["status"] == MACHINE_CHECKED
    assert out["verification"] == {"programs": 2, MACHINE_CHECKED: 1, NEEDS_HUMAN: 1}


def test_a_change_row_does_not_carry_the_summary_bookkeeping():
    old = {"academic": judged_item("ok")}
    new = {"academic": {"text": "GPA 3.2", "quote": "a GPA of 3.2", "check": "ok"}}
    (change,) = diff_fields(old, new)
    assert SUMMARY_CHECK not in change["old"] and SUMMARY_SHA not in change["old"]


# ---- what the judge is asked and how its answer is read ---------------------------------------------


def test_each_field_is_put_as_a_claim_in_words():
    assert fa.statement("academic", {"text": "GPA 3.0"}) == "GPA 3.0"
    assert fa.statement("ielts", {"overall": 7.0, "min_band": 6.5, "recommended": True}) == \
        "Recommended (not a minimum) IELTS: overall 7, no section below 6.5"
    assert fa.statement("toefl", {"overall": 90}) == "Minimum TOEFL iBT: overall 90"
    assert fa.statement("deadlines", {"label": "Round 1", "date": "2027-01-12"}) == \
        "Application deadline (Round 1): 2027-01-12"
    # The field says whom it is for: the claim does not add "Chinese degrees" or "985/211".
    assert fa.statement("china_requirement", {"text": "2:1 is 80%", "min_mark_211": 80, "min_mark_other": 85}) == \
        "2:1 is 80%; minimum average 80% for the higher group of universities; " \
        "minimum average 85% for the other universities"
    # Nothing beyond its own quote: nothing to judge.
    assert fa.statement("prerequisites", {"quote": "linear algebra"}) is None


def test_a_prerequisite_without_a_summary_passes_without_a_model_call():
    program = {"name": "P", "fields": {"prerequisites": [{"quote": "linear algebra", "check": "ok"}]}}
    result = fa.check_program(program, "S", model=None)
    assert result.attempts == 0
    assert program["fields"]["prerequisites"][0][SUMMARY_CHECK] == "ok" and program["status"] == MACHINE_CHECKED


def test_an_item_whose_quote_failed_is_not_sent():
    program = ut_program()
    program["fields"]["academic"]["check"] = "quote not found in snapshot"
    claims, _, _ = fa.program_claims(program)
    assert [c.field for c in claims] == ["toefl", "ielts"]


def test_a_malformed_answer_is_asked_again_and_then_blocks_as_not_checked():
    program = ut_program()
    result = fa.check_program(program, "S", answering(verdicts_body("{not json")))
    assert result.attempts == fa.MAX_ATTEMPTS and result.error
    for name in ("academic", "toefl", "ielts"):
        verdict = program["fields"][name][SUMMARY_CHECK]
        assert verdict.startswith(fa.NOT_CHECKED) and not usable(program["fields"][name])
        assert fa.needs_judgement(program["fields"][name])  # a rerun of the backfill tries again
    assert program["status"] == NEEDS_HUMAN


def test_a_second_answer_is_used_when_the_first_is_malformed():
    program = ut_program()
    result = fa.check_program(program, "S", answering(verdicts_body("{not json"), UT["response"]))
    assert result.attempts == 2 and result.error is None
    assert program["fields"]["toefl"][SUMMARY_CHECK] == "ok"


def test_a_claim_the_judge_leaves_out_is_not_checked():
    program = ut_program()
    fa.check_program(program, "S", answering(verdicts_body([{"id": 1, "supported": True},
                                                             {"id": 2, "supported": True}])))
    assert program["fields"]["academic"][SUMMARY_CHECK] == "ok"
    assert program["fields"]["ielts"][SUMMARY_CHECK].startswith(fa.NOT_CHECKED)


def test_a_verdict_without_its_flag_is_read_from_its_reason():
    program = ut_program()
    fa.check_program(program, "S", answering(verdicts_body([
        {"id": 1, "unsupported": "Bachelor's degree"}, {"id": 2, "supported": True}, {"id": 3},
    ])))
    assert program["fields"]["academic"][SUMMARY_CHECK] == "unsupported: Bachelor's degree"
    assert program["fields"]["ielts"][SUMMARY_CHECK].startswith(fa.NOT_CHECKED)


def test_an_unknown_or_repeated_id_does_not_count():
    program = ut_program()
    fa.check_program(program, "S", answering(verdicts_body([
        {"id": 9, "supported": True}, {"id": 1, "supported": False, "unsupported": "x"},
        {"id": 1, "supported": True}, {"id": 2, "supported": True}, {"id": 3, "supported": True},
    ])))
    assert program["fields"]["academic"][SUMMARY_CHECK] == "unsupported: x"


# ---- the backfill ------------------------------------------------------------------------------------


def school_files(tmp_path: Path, copies: int = 2) -> list[Path]:
    paths = []
    for n in range(copies):
        data = {"school_key": f"s{n}", "school_name_en": f"S{n}", "programs": [ut_program()]}
        path = tmp_path / f"s{n}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        paths.append(path)
    return paths


def test_the_estimate_counts_what_would_be_sent_without_calling_a_model(tmp_path):
    report = fa.estimate(school_files(tmp_path))
    assert (report["programs"], report["claims"]) == (2, 6)
    assert report["est_cost_cny"] > 0


def test_the_backfill_writes_the_verdicts_and_a_rerun_sends_nothing(tmp_path):
    paths = school_files(tmp_path)
    seen = []
    totals = fa.backfill(paths, budget_cny=1.0, concurrency=2,
                         model_factory=lambda: answering(UT["response"], seen=seen), log=lambda _: None)
    assert len(seen) == 2 and totals["programs"] == 2 and totals["blocked"] == 2
    assert totals["files_written"] == 2 and totals["cost_cny"] > 0 and totals["models"] == ["deepseek-flash"]
    data = json.loads(paths[0].read_text(encoding="utf-8"))
    assert data["programs"][0]["status"] == NEEDS_HUMAN
    assert data["verification"] == {"programs": 1, MACHINE_CHECKED: 0, NEEDS_HUMAN: 1}
    assert program_status(data["programs"][0]) == NEEDS_HUMAN

    again = fa.backfill(paths, budget_cny=1.0, model_factory=lambda: answering(UT["response"], seen=seen),
                        log=lambda _: None)
    assert len(seen) == 2 and again["programs"] == 0 and again["files_written"] == 0


def test_the_backfill_stops_sending_once_the_budget_is_spent(tmp_path):
    paths = school_files(tmp_path, copies=3)
    seen = []
    totals = fa.backfill(paths, budget_cny=1e-9, concurrency=1,
                         model_factory=lambda: answering(UT["response"], seen=seen), log=lambda _: None)
    assert len(seen) == 1 and totals["stopped_at_budget"]
    untouched = json.loads(paths[2].read_text(encoding="utf-8"))
    assert SUMMARY_CHECK not in untouched["programs"][0]["fields"]["academic"]


def test_the_backfill_stops_at_once_when_the_account_is_refused(tmp_path, monkeypatch):
    """2026-10-30: the balance ran out mid-run and every later call was a 402, each tried three times."""
    from tests.model_outage import out_of_balance_model

    paths = school_files(tmp_path, copies=3)
    before = [p.read_text(encoding="utf-8") for p in paths]
    calls, slept = [], []
    monkeypatch.setattr(fa.time, "sleep", slept.append)
    totals = fa.backfill(paths, budget_cny=1.0, concurrency=1, model_factory=lambda: out_of_balance_model(calls),
                         log=lambda _: None)
    assert totals["stopped_at_model_unavailable"].startswith("APIStatusError") and "402" in totals["stopped_at_model_unavailable"]
    assert len(calls) == 1 and slept == [] and totals["programs"] == 0
    # No value is marked "not checked" because the account was out of money: every file is as it was.
    assert [p.read_text(encoding="utf-8") for p in paths] == before


def test_forgetting_a_field_makes_its_values_unjudged_and_usable_again(tmp_path):
    paths = school_files(tmp_path, copies=1)
    fa.backfill(paths, budget_cny=1.0, model_factory=lambda: answering(UT["response"]), log=lambda _: None)
    assert fa.forget(paths, "academic") == 1
    data = json.loads(paths[0].read_text(encoding="utf-8"))
    program = data["programs"][0]
    assert SUMMARY_CHECK not in program["fields"]["academic"] and usable(program["fields"]["academic"])
    assert program["fields"]["toefl"][SUMMARY_CHECK] == "ok"
    assert program["status"] == MACHINE_CHECKED and data["verification"][MACHINE_CHECKED] == 1
