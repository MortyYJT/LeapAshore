"""The requirement extractor: model answer -> requirement fields -> verify -> drop and record.

No test calls a real model. `fixtures/extract/response.json` is one real DeepSeek response, recorded on
2026-10-30 for the fictional page `fixtures/extract/page.html` (Example University, not a real school);
the tests replay it through `ChatOpenAI` over a mocked transport, and plant faults by editing a copy of
its function-call arguments. `fixtures/extract/judge.json` is the real response of the summary check
(`app.collect.faithful`) for that answer, recorded the same day; other tests use a judge that backs
every claim, or one that backs none.
"""

import copy
import hashlib
import json
from pathlib import Path

import httpx
import pytest
from langchain_openai import ChatOpenAI

from app.agent.llm import ModelNotConfigured
from app.collect import extract as ex
from app.collect.text import html_to_text
from app.collect.verify import MACHINE_CHECKED, NEEDS_HUMAN
from app.config import settings

FIXTURES = Path(__file__).parent / "fixtures" / "extract"
PAGE = (FIXTURES / "page.html").read_text(encoding="utf-8")
RECORDED = json.loads((FIXTURES / "response.json").read_text(encoding="utf-8"))
JUDGED = json.loads((FIXTURES / "judge.json").read_text(encoding="utf-8"))
SHA = hashlib.sha256(PAGE.encode()).hexdigest()


@pytest.fixture
def root(tmp_path):
    folder = tmp_path / "example"
    folder.mkdir()
    (folder / f"{SHA}.txt").write_text(html_to_text(PAGE), encoding="utf-8")
    (folder / f"{SHA}.json").write_text(json.dumps({"final_url": "https://example.edu/mds"}), encoding="utf-8")
    return tmp_path


def answering(body: dict | list[dict], seen: list | None = None) -> ChatOpenAI:
    """A ChatOpenAI whose upstream replies with `body` (or each of a list in turn), recording each request."""
    bodies = body if isinstance(body, list) else None

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(json.loads(request.content))
        return httpx.Response(200, json=bodies.pop(0) if bodies is not None else body)

    return ChatOpenAI(model="deepseek-chat", base_url="https://model.test/v1", api_key="test", temperature=0,
                      max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def with_arguments(edit) -> dict:
    """The recorded response with its function-call arguments passed through `edit`."""
    body = copy.deepcopy(RECORDED)
    call = body["choices"][0]["message"]["tool_calls"][0]["function"]
    call["arguments"] = json.dumps(edit(json.loads(call["arguments"])))
    return body


def judging(supported: bool = True, reason: str = "an added condition") -> dict:
    """A judge response giving every claim id the same verdict (ids it was not asked about are ignored)."""
    body = copy.deepcopy(JUDGED)
    verdicts = [{"id": i, "supported": supported, **({} if supported else {"unsupported": reason})} for i in range(1, 40)]
    body["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = json.dumps({"verdicts": verdicts})
    return body


def run(model, root, judge=None, **kwargs):
    return ex.extract_snapshot("example", SHA, program_name="Master of Data Science",
                               school_name="Example University", country="Australia", model=model,
                               judge_model=answering(judge or judging()), root=root, **kwargs)


def bare(item: dict) -> dict:
    """An item without the summary check's bookkeeping."""
    return {k: v for k, v in item.items() if k not in ("summary_check", "summary_sha")}


def walk(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key, item
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)


def test_the_recorded_answer_passes_verify_and_keeps_the_model_name_and_usage(root):
    seen = []
    result = run(answering(RECORDED, seen), root, judge=JUDGED)
    program = result.program
    assert program["status"] == MACHINE_CHECKED
    assert program["url"] == "https://example.edu/mds"
    assert program["snapshot_sha256"] == SHA
    assert set(program["fields"]) == {"academic", "china_requirement", "ielts", "toefl", "prerequisites", "deadlines"}
    assert bare(program["fields"]["ielts"]) == {"overall": 6.5, "min_band": 6.0, "check": "ok",
                                                "quote": "IELTS Academic: an overall score of 6.5 with no band below 6.0."}
    assert program["fields"]["china_requirement"]["min_mark_211"] == 80
    assert [bare(d) for d in program["fields"]["deadlines"]] == [
        {"label": "2027 intake", "date": "2026-11-30", "check": "ok",
         "quote": "Applications for the 2027 intake close on 30 November 2026."}]
    assert result.rejected == [] and result.downgraded == []
    # The judge backed every summary of the recorded answer.
    assert all(item["summary_check"] == "ok" for name, value in program["fields"].items()
               for item in (value if isinstance(value, list) else [value]))
    assert result.model == "deepseek-flash"
    # Both calls are counted: the extraction (2260 / 532 / 1024) and the summary check.
    judge_usage = JUDGED["usage"]
    assert result.usage["input_tokens"] == 2260 + judge_usage["prompt_tokens"]
    assert result.usage["output_tokens"] == 532 + judge_usage["completion_tokens"]
    assert result.attempts == 1 and result.unused == []
    # One forced function call, carrying the page text.
    assert len(seen) == 1
    assert seen[0]["tool_choice"]["function"]["name"] == "ProgramRequirements"
    assert "no band below 6.0" in seen[0]["messages"][0]["content"]


def test_nothing_the_extractor_writes_is_verified_at_an_empty_string_or_a_zero(root):
    result = run(answering(RECORDED), root)
    for key, value in walk(result.program):
        assert key != "verified_at"
        assert value != "" and value is not None
        assert not (isinstance(value, (int, float)) and not isinstance(value, bool) and value == 0)
    assert "verified_at" not in json.dumps(ex.ProgramRequirements.model_json_schema())


def test_a_value_that_fails_verify_is_dropped_and_its_reason_recorded(root):
    def plant(args):
        args["ielts"]["quote"] = "IELTS 6.5 overall, 6.0 in each band"  # a paraphrase
        args["toefl"]["overall"] = 100  # a number the quote does not state
        args["deadlines"].append({"label": "Round 2", "date": "2027-01-15", "quote": "Round 2 closes on 15 January."})
        return args

    result = run(answering(with_arguments(plant)), root)
    fields = result.program["fields"]
    assert "ielts" not in fields and "toefl" not in fields
    assert [d["label"] for d in fields["deadlines"]] == ["2027 intake"]
    reasons = {r["field"]: r["reason"] for r in result.rejected}
    assert reasons["ielts"] == "quote not found in snapshot"
    assert reasons["toefl"] == "overall=100 not in quote"
    assert reasons["deadlines"] == "deadline year 2027 not in quote"
    rejected_toefl = next(r for r in result.rejected if r["field"] == "toefl")
    assert rejected_toefl["value"]["overall"] == 100 and "check" not in rejected_toefl["value"]
    # What is left all passed, so the program is machine-checked on what remains.
    assert result.program["status"] == MACHINE_CHECKED


def test_a_zero_an_empty_string_or_a_non_date_is_refused_before_the_check(root):
    def plant(args):
        args["china_requirement"]["min_mark_other"] = 0
        args["ielts"] = {"overall": None, "min_band": None, "text": "", "quote": "IELTS Academic: an overall score of 6.5"}
        args["academic"][0]["quote"] = "   "
        args["deadlines"][0]["date"] = "30 November 2026"
        return args

    result = run(answering(with_arguments(plant)), root)
    fields = result.program["fields"]
    assert set(fields) == {"toefl", "prerequisites"}
    reasons = {r["field"]: r["reason"] for r in result.rejected}
    assert reasons == {
        "academic": "no quote",
        "china_requirement": "min_mark_other=0 is outside (0, 100]",
        "ielts": "no value: neither a number nor a text",
        "deadlines": "date '30 November 2026' is not an ISO date",
    }


def test_toefl_on_two_scales_gets_the_scale_note(root):
    result = run(answering(RECORDED), root)  # the page states 90 and 4.5; the model said two_scales
    assert result.program["fields"]["toefl"]["scale_note"] == ex.TOEFL_TWO_SCALES
    assert "two_scales" not in result.program["fields"]["toefl"]

    def one_scale(args):
        args["toefl"]["two_scales"] = False
        return args

    assert "scale_note" not in run(answering(with_arguments(one_scale)), root).program["fields"]["toefl"]


def test_the_first_academic_route_is_kept_and_the_others_listed_as_unused(root):
    second = {"text": "Any bachelor's degree", "quote": "Applicants must have completed at least one course in linear algebra"}

    def plant(args):
        args["academic"].append(second)
        return args

    result = run(answering(with_arguments(plant)), root)
    assert result.program["fields"]["academic"]["quote"].startswith("Applicants need a bachelor's degree")
    assert result.unused == [{"field": "academic", "value": second,
                              "reason": "another academic route; the requirement file holds one"}]
    assert result.rejected == []


def test_an_academic_route_given_as_one_object_is_read_as_a_list_of_one(root):
    def plant(args):
        args["academic"] = args["academic"][0]
        return args

    result = run(answering(with_arguments(plant)), root)
    assert result.error is None and "academic" in result.program["fields"]


def test_a_page_that_states_nothing_goes_to_the_human_queue(root):
    result = run(answering(with_arguments(lambda args: {})), root)
    assert result.program["fields"] == {}
    assert result.program["status"] == NEEDS_HUMAN
    assert result.rejected == [] and result.error is None


def malformed() -> dict:
    body = copy.deepcopy(RECORDED)
    body["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = '{"ielts": {"overall": 6.5, "quo'
    body["choices"][0]["finish_reason"] = "length"
    return body


def test_an_answer_that_is_not_valid_json_twice_is_an_error_not_a_value(root):
    seen = []
    result = run(answering([malformed(), malformed()], seen), root)
    assert len(seen) == 2 and result.attempts == 2
    assert result.error and "finish_reason=length" in result.error
    assert result.program["fields"] == {} and result.program["status"] == NEEDS_HUMAN
    assert result.rejected == []
    assert result.usage["output_tokens"] == 2 * 532


def test_a_malformed_answer_is_asked_for_once_more(root):
    result = run(answering([malformed(), RECORDED]), root)
    assert result.attempts == 2 and result.error is None
    assert result.program["status"] == MACHINE_CHECKED
    assert result.usage["input_tokens"] == 2 * 2260 + JUDGED["usage"]["prompt_tokens"]


def test_a_summary_the_judge_does_not_back_stays_marked_and_sends_the_program_to_a_person(root):
    result = run(answering(RECORDED), root, judge=judging(False, "added a degree"))
    fields = result.program["fields"]
    assert result.program["status"] == NEEDS_HUMAN
    # Downgraded, not deleted or edited: every value is still in the program, with the reason.
    assert set(fields) == {"academic", "china_requirement", "ielts", "toefl", "prerequisites", "deadlines"}
    assert fields["academic"]["summary_check"] == "unsupported: added a degree"
    assert {d["field"] for d in result.downgraded} == set(fields)
    assert result.rejected == []


def test_a_judge_that_does_not_answer_raises_with_the_paid_extraction_usage(root):
    def refuse(request):
        raise httpx.ConnectError("judge down")

    judge = ChatOpenAI(model="deepseek-chat", base_url="https://model.test/v1", api_key="test", max_retries=0,
                       http_client=httpx.Client(transport=httpx.MockTransport(refuse)))
    with pytest.raises(Exception) as caught:
        ex.extract_snapshot("example", SHA, program_name="Master of Data Science", school_name="Example University",
                            country="Australia", model=answering(RECORDED), judge_model=judge, root=root)
    assert caught.value.extract_usage["input_tokens"] == 2260


def test_a_judge_that_cannot_be_read_blocks_every_summary_as_not_checked(root):
    broken = copy.deepcopy(JUDGED)
    broken["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = "{"
    result = run(answering(RECORDED), root, judge=broken)
    assert result.program["status"] == NEEDS_HUMAN
    assert all(d["reason"].startswith("not checked") for d in result.downgraded) and result.downgraded


def test_a_long_page_is_cut_to_the_lines_around_requirement_words():
    filler = [f"Campus news item {i} about the library opening hours." for i in range(3000)]
    lines = filler[:1500] + ["IELTS overall 6.5 with no band below 6.0."] + filler[1500:]
    excerpt, truncated = ex.page_excerpt("\n".join(lines), limit=5_000)
    assert truncated
    assert "IELTS overall 6.5 with no band below 6.0." in excerpt
    assert len(excerpt) <= 5_000
    short, cut = ex.page_excerpt("IELTS 6.5", limit=5_000)
    assert (short, cut) == ("IELTS 6.5", False)


def test_without_a_model_key_the_extractor_says_so(root, monkeypatch):
    monkeypatch.setattr(settings, "chat_api_key", "")
    with pytest.raises(ModelNotConfigured):
        run(None, root)


def test_a_snapshot_with_no_recorded_address_is_refused_before_any_call(root):
    (root / "example" / f"{SHA}.json").unlink()
    seen = []
    with pytest.raises(ValueError, match="no URL"):
        run(answering(RECORDED, seen), root)
    assert seen == []


@pytest.mark.parametrize(("name", "key", "value"), [
    ("toefl", "overall", 4.5),  # a 1-6 band score is not a 0-120 total
    ("toefl", "overall", 121),
    ("toefl", "min_band", 4.5),
    ("ielts", "overall", 65),
    ("ielts", "min_band", -1),
])
def test_a_number_outside_its_scale_is_refused_whole(root, name, key, value):
    def plant(args):
        args[name][key] = value
        return args

    result = run(answering(with_arguments(plant)), root)
    assert name not in result.program["fields"]
    [refusal] = result.rejected
    assert refusal["field"] == name and refusal["reason"].startswith(f"{key}={value:g} is outside")


@pytest.mark.parametrize("name", ["academic", "prerequisites", "deadlines"])
def test_a_null_list_is_nothing_stated_not_a_lost_answer(root, name):
    def plant(args):
        args[name] = None
        return args

    result = run(answering(with_arguments(plant)), root)
    assert result.error is None and result.attempts == 1
    assert name not in result.program["fields"]
    assert {"ielts", "toefl"} <= set(result.program["fields"])


def test_the_two_scales_note_needs_a_band_score_in_the_quote(root):
    def plant(args):
        args["toefl"]["quote"] = "TOEFL iBT: for tests taken on or before 20 January 2026, a total of 90"
        return args

    toefl = run(answering(with_arguments(plant)), root).program["fields"]["toefl"]
    assert toefl["check"] == "ok" and toefl["overall"] == 90
    assert "scale_note" not in toefl
