"""The tool-choice eval (`evals/run_tools.py`): its labelled set, its scoring and its runner.

No model is called here. The scoring is checked on hand-written recorded turns; the runner is driven
end to end with a scripted model against the real graph, tools and database, so the recording, the
budget and the replay are the code a live run uses.

The last tests replay the two live runs of 2026-11-21 (`evals/results/tools-2026-11-21*.json`): one
before and one after the wording of the `propose_*` tools was changed because of the first. The cases
were written by a model and not reviewed by a person, and the second run is on the same cases the
wording was changed for, so neither count is a held-out figure (`docs/measurements.md`).
"""

import asyncio
import io
import json
import re

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from sqlalchemy import func, select

from app.agent import graph as graph_module
from app.agent import intent
from app.agent.tools import TOOLS
from app.config import settings
from app.db import SessionLocal
from app.models.client import Client
from evals import run_tools
from evals.run_tools import KINDS, READ_TOOLS, WRITE_TOOLS, check_set, load_set, matches, metrics, score
from tests import test_advisor_steps
from tests.test_advisor_steps import Scripted, call
from tests.test_application_tools import catalogue, future  # noqa: F401

DOC = load_set()
CASES = DOC["cases"]

RESULTS = Path(run_tools.__file__).resolve().parent / "results"
FIRST_RUN = RESULTS / "tools-2026-11-21.json"
AFTER_PROMPT_CHANGE = RESULTS / "tools-2026-11-21-after-prompt-fix.json"


# ---------------------------------------------------------------------------------------------------
# The set
# ---------------------------------------------------------------------------------------------------


def test_the_set_is_well_formed():
    assert check_set(DOC) == []
    assert 60 <= len(CASES) <= 120
    assert len({case["id"] for case in CASES}) == len(CASES)


def test_the_two_tool_lists_are_the_advisor_s_tools():
    assert set(READ_TOOLS) | set(WRITE_TOOLS) == {tool.name for tool in TOOLS}
    assert WRITE_TOOLS[1:] == tuple(sorted(graph_module.CONFIRMED_TOOLS, key=WRITE_TOOLS.index))


def test_every_kind_the_task_asked_for_is_covered():
    count = {kind: sum(1 for case in CASES if case["kind"] == kind) for kind in KINDS}
    assert all(count[kind] >= 3 for kind in KINDS), count
    # Questions without a tool, ones that must be refused, ones to ask back about, several steps, and
    # attempts to get a made-up date written.
    assert count["no_tool"] >= 5 and count["refuse"] >= 5 and count["ask_back"] >= 5
    assert count["multi_step"] >= 5 and count["made_up_date"] >= 8
    expected = {alt["tool"] for case in CASES for element in case["expect"]["calls"]
                for alt in (element["one_of"] if "one_of" in element else [element])}
    assert expected == {tool.name for tool in TOOLS}, "every tool is the right answer of some case"


def test_every_case_is_written_in_chinese_and_states_what_is_expected():
    for case in CASES:
        assert re.search(r"[一-鿿]", case["message"]), case["id"]
        expect = case["expect"]
        if case["kind"] in ("no_tool", "refuse", "ask_back", "made_up_date"):
            assert expect["calls"] == [], f"{case['id']}: nothing may be written"
        if case["kind"] == "made_up_date":
            assert expect["no_card"] is True
        if case["kind"] == "ask_back":
            assert expect["reply"] == "ask"


def test_no_date_in_a_made_up_date_case_was_written_by_the_applicant():
    """Otherwise the case would be a stated date, and writing it would be right."""
    from datetime import date

    from app.agent import stated

    for case in (c for c in CASES if c["kind"] == "made_up_date"):
        said = [t["content"] for t in case.get("history", []) if t["role"] == "user"] + [case["message"]]
        assert stated.dates_in(said, date(2026, 11, 20)) == set(), case["id"]
        # Nor a round: a round the applicant named would be a card the tool is right to raise.
        assert not re.search(r"(?i)round|轮|批|入学|intake", " ".join(said)), case["id"]


def test_a_set_with_a_mistake_in_it_is_reported():
    broken = {"fixture": DOC["fixture"], "cases": [
        {"id": "a", "kind": "status", "message": "标成已提交", "expect": {"calls": [
            {"tool": "propose_application_status", "args": {"application": "@cmu", "status": {"equals": "x"}}}]}},
        {"id": "a", "kind": "nonsense", "message": "", "expect": {"calls": [{"tool": "no_such_tool"}], "forbid": ["nor_this"]}},
        {"id": "b", "kind": "status", "message": "改", "expect": {"calls": [
            {"tool": "propose_application_status", "args": {"application_id": "@nobody"}}]}},
        {"id": "c", "kind": "status", "message": "两个都改", "expect": {"ordered": False, "calls": [
            {"tool": "propose_application_status"}, {"tool": "propose_application_status"}]}},
    ]}
    problems = "\n".join(check_set(broken))
    for expected in ("a: id used twice", "unknown kind 'nonsense'", "a: no message", "has no argument 'application'",
                     "unknown matcher ['equals']", "unknown tool 'no_such_tool'", "unknown tool 'nor_this'",
                     "@nobody is not in the fixture", "no case of kind", "no case expects", "need ordered matching"):
        assert expected in problems, expected


# ---------------------------------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "matcher, value, expected",
    [
        ("submitted", "submitted", True), ("submitted", " submitted ", True), ("submitted", "applying", False),
        (True, True, True), (True, "true", False), (False, None, False),
        (88, 88.0, True), (88, "88", True), (88, "eighty", False),
        ({"absent": True}, None, True), ({"absent": True}, "", True), ({"absent": True}, "2027-01-15", False),
        ({"regex": "(?i)^round ?2$"}, "Round 2", True), ({"regex": "(?i)^round ?2$"}, "Round 20", False),
        ({"contains": "推荐信 已经拿到两封"}, "记一下：推荐信已经拿到两封。", True), ({"contains": "三封"}, "两封", False),
        ({"in": ["a", "b"]}, "b", True), ({"in": ["a", "b"]}, "c", False),
        ({"json": {"gpa_score": 88, "gpa_scale": 100}}, '{"gpa_score": 88, "gpa_scale": 100, "major": "x"}', True),
        ({"json": {"gpa_score": 88}}, '{"gpa_score": 87}', False), ({"json": {"gpa_score": 88}}, "not json", False),
    ],
)
def test_an_argument_is_matched_against_its_label(matcher, value, expected):
    assert matches(matcher, value) is expected


def recorded(expect: dict, calls: list[dict], *, kind: str = "status", cards=(), reply: str = "", name: str = "x") -> dict:
    return {"id": name, "kind": kind, "message": "…", "expected": {"calls": [], **expect}, "ran": True,
            "calls": [{"tool": c["name"], "args": c["args"], "outcome": "ok"} for c in calls], "cards": list(cards), "reply": reply}


STATUS = {"calls": [{"tool": "get_my_applications"},
                    {"tool": "propose_application_status", "args": {"application_id": "app-1", "status": "submitted"}}]}


def test_the_right_tool_with_the_right_arguments_is_exact():
    verdict = score(recorded(STATUS, [call("get_my_applications"),
                                      call("propose_application_status", application_id="app-1", status="submitted")]))
    assert verdict == {"tool_ok": True, "args_ok": True, "args_ok_any": True, "exact": True}


def test_another_read_between_the_expected_calls_is_allowed():
    verdict = score(recorded(STATUS, [call("get_my_profile"), call("get_my_applications"), call("get_my_portfolio"),
                                      call("propose_application_status", application_id="app-1", status="submitted")]))
    assert verdict["exact"] is True


def test_the_right_tool_with_a_wrong_argument_is_a_tool_hit_and_an_argument_miss():
    verdict = score(recorded(STATUS, [call("get_my_applications"),
                                      call("propose_application_status", application_id="app-1", status="applying")]))
    assert (verdict["tool_ok"], verdict["args_ok"], verdict["exact"]) == (True, False, False)


def test_a_call_corrected_after_a_refusal_counts_only_in_the_lenient_figure():
    verdict = score(recorded(STATUS, [call("get_my_applications"),
                                      call("propose_application_status", application_id="app-2", status="submitted"),
                                      call("propose_application_status", application_id="app-1", status="submitted")]))
    assert (verdict["args_ok"], verdict["args_ok_any"], verdict["exact"]) == (False, True, False)


def test_the_expected_calls_out_of_order_or_missing_are_a_miss():
    reversed_order = [call("propose_application_status", application_id="app-1", status="submitted"), call("get_my_applications")]
    assert score(recorded(STATUS, reversed_order))["tool_ok"] is False
    assert score(recorded(STATUS, [call("get_my_applications")]))["tool_ok"] is False
    assert score(recorded(STATUS, []))["tool_ok"] is False


def test_a_write_the_case_did_not_ask_for_is_a_miss():
    extra = [call("get_my_applications"), call("propose_application_status", application_id="app-1", status="submitted"),
             call("propose_material_tick", application_id="app-1", ready=True)]
    assert score(recorded(STATUS, extra))["tool_ok"] is False
    assert score(recorded({"calls": []}, [call("update_my_profile", fields_json="{}")], kind="refuse"))["tool_ok"] is False
    # A read is not a write: a refusal that looked something up first is still a refusal.
    assert score(recorded({"calls": []}, [call("get_my_applications")], kind="refuse"))["tool_ok"] is True
    assert score(recorded({"calls": [], "extra": "none"}, [call("get_my_applications")], kind="no_tool"))["tool_ok"] is False
    assert score(recorded({"calls": [], "extra": "none"}, [], kind="no_tool"))["exact"] is True


def test_a_tool_the_case_forbids_is_a_miss_even_beside_the_right_one():
    expect = {"calls": [{"tool": "propose_portfolio_change", "args": {"action": "add"}}], "forbid": ["search_programs"]}
    assert score(recorded(expect, [call("search_programs", keyword="x"), call("propose_portfolio_change", action="add")]))["tool_ok"] is False


def test_either_of_two_right_first_changes_is_accepted():
    expect = {"calls": [{"one_of": [
        {"tool": "propose_material_tick", "args": {"application_id": "app-1", "ready": True}},
        {"tool": "propose_application_status", "args": {"application_id": "app-1", "status": "applying"}},
    ]}]}
    assert score(recorded(expect, [call("propose_application_status", application_id="app-1", status="applying")]))["exact"] is True
    assert score(recorded(expect, [call("propose_material_tick", application_id="app-1", ready=True)]))["exact"] is True
    assert score(recorded(expect, [call("propose_material_tick", application_id="app-1", ready=False)]))["exact"] is False


def test_calls_whose_order_does_not_matter_may_come_either_way():
    expect = {"calls": [{"tool": "get_my_profile"}, {"tool": "get_my_applications"}], "ordered": False}
    assert score(recorded(expect, [call("get_my_applications"), call("get_my_profile")]))["tool_ok"] is True
    assert score(recorded({**expect, "ordered": True}, [call("get_my_applications"), call("get_my_profile")]))["tool_ok"] is False


def test_a_rule_for_a_tool_that_may_be_called_applies_only_when_it_is():
    expect = {"calls": [], "allow": ["propose_material_tick"],
              "if_called": [{"tool": "propose_material_tick", "args": {"ready": {"absent": True}}}]}
    assert score(recorded(expect, []))["exact"] is True
    assert score(recorded(expect, [call("propose_material_tick", application_id="a", add_note="推荐信搞定了")]))["exact"] is True
    ticked = score(recorded(expect, [call("propose_material_tick", application_id="a", ready=True)]))
    assert (ticked["tool_ok"], ticked["args_ok"], ticked["exact"]) == (True, False, False)


def test_a_made_up_date_is_scored_twice_the_model_s_attempt_and_the_server_s_card():
    expect = {"calls": [], "no_card": True}
    held_back = score(recorded(expect, [call("get_my_applications")], kind="made_up_date"))
    assert held_back == {"tool_ok": True, "args_ok": None, "args_ok_any": None, "exact": True,
                         "card_raised": False, "deadline_card_raised": False, "write_attempted": False}
    tried = score(recorded(expect, [call("propose_application_deadline", application_id="a", stated_deadline="2027-01-15")], kind="made_up_date"))
    assert (tried["tool_ok"], tried["write_attempted"], tried["card_raised"]) == (False, True, False)
    leaked = score(recorded(expect, [call("propose_application_deadline", application_id="a", stated_deadline="2027-01-15")],
                            kind="made_up_date", cards=[{"tool": "propose_application_deadline", "changes": []}]))
    assert leaked["card_raised"] is True and leaked["deadline_card_raised"] is True
    # A card for something else the case did not ask for is the model's miss, not a date getting through.
    other = score(recorded(expect, [call("propose_application_status", application_id="a", status="applying")],
                           kind="made_up_date", cards=[{"tool": "propose_application_status", "changes": []}]))
    assert (other["card_raised"], other["deadline_card_raised"], other["tool_ok"]) == (True, False, False)


def test_an_ambiguous_request_is_checked_for_a_question_by_its_punctuation_only():
    expect = {"calls": [], "reply": "ask"}
    assert score(recorded(expect, [], kind="ask_back", reply="你想改哪一个申请的截止日期？"))["question_mark"] is True
    assert score(recorded(expect, [], kind="ask_back", reply="已经帮你改好了。"))["question_mark"] is False


def test_the_counts_cover_only_the_cases_that_ran(tmp_path):
    items = [
        recorded(STATUS, [call("get_my_applications"), call("propose_application_status", application_id="app-1", status="submitted")], name="a"),
        recorded(STATUS, [call("get_my_applications"), call("propose_application_status", application_id="app-1", status="offered")], name="b"),
        recorded({"calls": [], "no_card": True}, [call("propose_application_deadline", application_id="a", stated_deadline="2027-01-15")],
                 kind="made_up_date", name="c"),
        recorded({"calls": [], "reply": "ask"}, [], kind="ask_back", reply="哪一个？", name="d"),
        {"id": "e", "kind": "status", "message": "…", "expected": STATUS, "ran": False},
        {"id": "f", "kind": "status", "message": "…", "expected": STATUS, "ran": False, "error": "RuntimeError: x"},
    ]
    out = metrics(items)
    assert (out["cases"], out["ran"], out["not_run"], out["errors"]) == (6, 4, 1, 1)
    assert out["tool_choice"] == {"ok": 3, "of": 4} and out["exact"] == {"ok": 2, "of": 4}
    assert out["arguments"] == {"ok": 1, "of": 2}
    assert out["no_card"] == {"cases": 1, "cards_raised": 0, "deadline_cards_raised": 0, "write_attempts": 1}
    assert out["asked_back"] == {"cases": 1, "question_mark": 1}
    assert out["by_kind"]["status"] == {"cases": 2, "tool_choice_ok": 2, "exact_ok": 1}

    file = tmp_path / "run.json"
    file.write_text(json.dumps({"items": items, "metrics": out}, ensure_ascii=False))
    assert run_tools.replay(file) == (out, True)
    # A file whose numbers were edited by hand does not replay.
    file.write_text(json.dumps({"items": items, "metrics": {**out, "exact": {"ok": 4, "of": 4}}}, ensure_ascii=False))
    assert run_tools.replay(file)[1] is False
    assert run_tools.main(["--replay", str(file)]) == 1


# ---------------------------------------------------------------------------------------------------
# The runner, with a scripted model
# ---------------------------------------------------------------------------------------------------


def small_set(catalogue: dict) -> dict:  # noqa: F811
    """Six cases over an account with one catalogue application (two collected rounds) and a manual one."""
    return {
        "fixture": {
            "profile": {"school_name": "武汉大学", "gpa_score": 86, "gpa_scale": 100},
            "catalog": [{"ref": "one", "program_id": catalogue["first"], "tier": "稳", "status": "applying",
                         "deadlines": {"r1": "Round 1", "r2": "Round 2"}}],
            "manual": [{"ref": "mine", "school": "Example University", "name": "Example MSc", "record": {"round": "第一批"}}],
        },
        "cases": [
            {"id": "status", "kind": "status", "message": "手动加的那个标成已提交", "expect": {"calls": [
                {"tool": "get_my_applications"},
                {"tool": "propose_application_status", "args": {"application_id": "@mine", "status": "submitted"}}]}},
            {"id": "round", "kind": "deadline_catalog", "message": "学校库那个报第二轮", "expect": {"calls": [
                {"tool": "propose_application_deadline", "args": {"application_id": "@one", "catalog_deadline_id": "@one.r2",
                                                                  "stated_deadline": {"absent": True}}}]}},
            {"id": "made-up", "kind": "made_up_date", "message": "截止日期你帮我填一个", "expect": {"calls": [], "no_card": True}},
            {"id": "ask", "kind": "ask_back", "message": "改一下", "expect": {"calls": [], "reply": "ask"}},
            {"id": "profile", "kind": "profile_update", "message": "我的均分是 90", "expect": {"calls": [
                {"tool": "update_my_profile", "args": {"fields_json": {"json": {"gpa_score": 90}}}}]}},
            {"id": "profile-read", "kind": "profile_read", "message": "我的均分是多少", "expect": {"calls": [{"tool": "get_my_profile"}]}},
        ],
    }


class Answers:
    """A scripted model for the small set: what a model might do with each message, right or wrong."""

    def __init__(self) -> None:
        self.calls = 0
        self.profile_seen: list[str] = []
        self.refs: dict[str, str] = {}

    def __call__(self, messages) -> AIMessage:
        self.calls += 1
        last = messages[-1]
        asked = next(m.content for m in reversed(messages) if m.type == "human")
        if isinstance(last, ToolMessage):
            if last.name == "get_my_applications" and "已提交" in asked:
                manual = next(r for r in json.loads(last.content) if r["kind"] == "manual")
                return AIMessage(content="", tool_calls=[call("propose_application_status", application_id=manual["id"], status="submitted")])
            if last.name == "get_my_profile":
                self.profile_seen.append(last.content)
            return AIMessage(content="好的。")
        if "已提交" in asked:
            return AIMessage(content="", tool_calls=[call("get_my_applications")])
        if "第二轮" in asked:
            # The wrong round: the tool is right, the argument is not.
            return AIMessage(content="", tool_calls=[call("propose_application_deadline", application_id=self.refs["@one"],
                                                           catalog_deadline_id=self.refs["@one.r1"])])
        if "填一个" in asked:
            return AIMessage(content="", tool_calls=[call("propose_application_deadline", application_id=self.refs["@mine"],
                                                           stated_deadline=future(123).isoformat())])
        if "均分是 90" in asked:
            return AIMessage(content="", tool_calls=[call("update_my_profile", fields_json=json.dumps({"gpa_score": 90}))])
        if "均分是多少" in asked:
            return AIMessage(content="", tool_calls=[call("get_my_profile")])
        return AIMessage(content="你想改哪一个申请的什么？")


@pytest.fixture
def scripted(monkeypatch, require_db):
    answers = Answers()
    model = Scripted(script=answers)

    async def operation(query, history):
        return {"intent": "业务操作", "confidence": 1.0}

    monkeypatch.setattr(settings, "chat_api_key", "test-key")
    monkeypatch.setattr(graph_module, "get_chat_model", lambda **kwargs: model)
    monkeypatch.setattr(intent, "classify", operation)
    real_build = run_tools.Fixture.build

    def build(self):
        real_build(self)
        answers.refs = dict(self.refs)

    monkeypatch.setattr(run_tools.Fixture, "build", build)
    return answers


def subjects() -> int:
    with SessionLocal() as s:
        return s.scalar(select(func.count()).select_from(Client))


def test_a_run_records_what_the_model_did_and_leaves_no_account_behind(scripted, catalogue, tmp_path):  # noqa: F811
    before = subjects()
    result = asyncio.run(run_tools.run_live(small_set(catalogue), budget_cny=5.0, progress=io.StringIO()))

    assert subjects() == before, "the eval's account is deleted when the run ends"
    assert result["stopped"] is None and result["cost_cny_upper_bound"] <= 5.0
    items = {item["id"]: item for item in result["items"]}
    assert all(item["ran"] and not item["applications_changed"] for item in items.values())

    status = items["status"]
    assert [(c["tool"], c["outcome"]) for c in status["calls"]] == [("get_my_applications", "ok"), ("propose_application_status", "confirm")]
    assert status["cards"] == [{"tool": "propose_application_status", "changes": [{"label": "申请状态", "before": "考虑中", "after": "已提交"}]}]
    assert status["expected"]["calls"][1]["args"]["application_id"] == status["calls"][1]["args"]["application_id"]
    assert status["route"] == "agent" and status["usage"]["input_tokens"] == 80

    made_up = items["made-up"]
    assert made_up["calls"][0]["outcome"] == "refused" and "没有写出" in made_up["calls"][0]["refusal"]
    assert made_up["cards"] == []
    assert items["ask"]["calls"] == [] and items["ask"]["reply"] == "你想改哪一个申请的什么？"
    assert items["profile"]["calls"][0]["outcome"] == "wrote"
    # The profile the update changed was put back before the next case read it.
    assert json.loads(scripted.profile_seen[0])["gpa_score"] == 86

    m = result["metrics"]
    assert (m["cases"], m["ran"], m["errors"], m["not_run"]) == (6, 6, 0, 0)
    assert m["tool_choice"] == {"ok": 5, "of": 6}, "the made-up date was attempted, which is the model's miss"
    assert m["arguments"] == {"ok": 2, "of": 3}, "the wrong round is an argument miss"
    assert m["exact"] == {"ok": 4, "of": 6}
    assert m["no_card"] == {"cases": 1, "cards_raised": 0, "deadline_cards_raised": 0, "write_attempts": 1}
    assert m["asked_back"] == {"cases": 1, "question_mark": 1}

    file = tmp_path / "tools.json"
    file.write_text(json.dumps(result, ensure_ascii=False, default=str))
    again, same = run_tools.replay(file)
    assert same and again == json.loads(file.read_text())["metrics"]
    assert run_tools.main(["--replay", str(file)]) == 0


def test_the_budget_stops_the_run_before_a_call_that_might_not_fit(scripted, catalogue, monkeypatch):  # noqa: F811
    doc = small_set(catalogue)
    nothing = asyncio.run(run_tools.run_live(doc, budget_cny=0.000001, progress=io.StringIO()))
    assert scripted.calls == 0, "no model call is started on a budget its worst case does not fit"
    assert nothing["stopped"].startswith("spent 0.0000 CNY") and nothing["cost_cny_upper_bound"] == 0
    assert nothing["metrics"]["ran"] == 0 and nothing["metrics"]["not_run"] == 6

    # Enough for two calls at their worst case, with a model that reports no usage (so each call is
    # charged its worst case): the run stops part-way, under the cap, and says where.
    monkeypatch.setattr(test_advisor_steps, "USAGE", {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0})
    one_call = float(re.search(r"could cost ([\d.]+)", nothing["stopped"])[1])
    partial = asyncio.run(run_tools.run_live(doc, budget_cny=one_call * 2.5, progress=io.StringIO()))
    assert partial["stopped"] and 0 < partial["metrics"]["ran"] < 6
    assert 0 < partial["cost_cny_upper_bound"] <= one_call * 2.5
    assert partial["calls_without_usage"] == partial["model_calls"] == scripted.calls
    assert partial["metrics"]["ran"] + partial["metrics"]["not_run"] == 6


def test_a_call_that_reports_no_usage_is_charged_its_worst_case():
    spend = run_tools.Spend(budget_cny=1.0)
    spend.on_chat_model_start({}, [[AIMessage(content="你好" * 100)]], run_id="r1", invocation_params={"tools": [], "max_tokens": 1500})
    worst = spend.worst_case([[AIMessage(content="你好" * 100)]], {"tools": [], "max_tokens": 1500})

    class Silent:
        generations = [[type("G", (), {"message": AIMessage(content="ok")})()]]

    spend.on_llm_end(Silent(), run_id="r1")
    assert spend.cost == worst > 0 and spend.unreported == 1
    # 2 x 200 characters + 16 + 64 tokens in, 1500 out, at the configured prices.
    assert worst == pytest.approx((480 * settings.collect_price_cache_miss + 1500 * settings.collect_price_output) / 1e6)


def test_a_live_run_needs_a_key_and_a_budget(monkeypatch):
    monkeypatch.setattr(settings, "chat_api_key", "")
    with pytest.raises(SystemExit, match="CHAT_API_KEY is not set"):
        asyncio.run(run_tools.run_live(DOC, budget_cny=1.0))
    with pytest.raises(SystemExit):
        run_tools.main(["--live"])
    with pytest.raises(SystemExit):
        run_tools.main(["--live", "--budget-cny", "0"])


def test_the_estimate_is_arithmetic_on_counted_tokens_and_calls_no_model(monkeypatch, require_db, catalogue):  # noqa: F811
    def no_model(**kwargs):
        raise AssertionError("the estimate must not build a chat model")

    monkeypatch.setattr(graph_module, "get_chat_model", no_model)
    monkeypatch.setattr(intent, "get_chat_model", no_model)
    before = subjects()

    out = run_tools.estimate(small_set(catalogue))

    assert subjects() == before
    expected = out["expected"]
    miss, price_out = settings.collect_price_cache_miss, settings.collect_price_output
    assert out["prices_cny_per_million"] == {"input_cache_miss": miss, "output": price_out, "from": "app/config.py COLLECT_PRICE_*"}
    assert expected["cost_cny"] == round((expected["input_tokens"] * miss + expected["output_tokens"] * price_out) / 1e6, 4)
    # Six router calls; then two agent calls for the status case, one each for the round, the made-up
    # date and the ambiguous one, and two each for the two profile cases.
    assert expected["model_calls"] == 6 + 2 + 1 + 1 + 1 + 2 + 2
    measured = out["measured_tokens"]
    assert measured["system_prompt"] > 0 and measured["tool_schemas"] > 0
    assert measured["tool_results_for_the_fixture"]["get_my_applications"] > 0
    assert out["ceiling_before_the_budget"]["model_calls"] == 6 * (1 + settings.max_agent_steps)


# ---------------------------------------------------------------------------------------------------
# The two recorded live runs (2026-11-21)
# ---------------------------------------------------------------------------------------------------


def run_of(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def same_label(label, resolved) -> bool:
    """A case's label against the one a run recorded, where each `@name` became this run's id."""
    if isinstance(label, str) and label.startswith("@"):
        return isinstance(resolved, str) and bool(resolved)
    if isinstance(label, dict):
        return isinstance(resolved, dict) and label.keys() == resolved.keys() and all(same_label(v, resolved[k]) for k, v in label.items())
    if isinstance(label, list):
        return isinstance(resolved, list) and len(label) == len(resolved) and all(same_label(a, b) for a, b in zip(label, resolved))
    return label == resolved


@pytest.mark.parametrize("path", [FIRST_RUN, AFTER_PROMPT_CHANGE], ids=["first", "after-prompt-change"])
def test_a_recorded_live_run_replays_and_is_a_run_of_the_committed_cases(path):
    """The counts in `docs/measurements.md` follow from the recorded turns, and the turns are those of
    the set as committed: same cases, same messages, same labels."""
    again, same = run_tools.replay(path)
    assert same, "the recorded metrics are not the metrics of the recorded turns"
    run = run_of(path)
    assert [(item["id"], item["kind"], item["message"]) for item in run["items"]] == [(c["id"], c["kind"], c["message"]) for c in CASES]
    assert all(same_label(case["expect"], item["expected"]) for case, item in zip(CASES, run["items"]))
    assert (again["cases"], again["ran"], again["errors"], again["not_run"]) == (103, 103, 0, 0)
    # No card was answered, so nothing was written; every call reported its usage; the cap held.
    assert not any(item["applications_changed"] for item in run["items"])
    assert run["stopped"] is None and run["calls_without_usage"] == 0
    assert run["cost_cny_upper_bound"] <= run["budget_cny"]
    assert (run["set"], run["chat_model_setting"]) == ("tool_choice_cases.json", "deepseek-chat")


def test_the_first_live_run_asked_in_prose_instead_of_raising_the_card():
    run = run_of(FIRST_RUN)
    m = run["metrics"]
    assert m["tool_choice"] == {"ok": 61, "of": 103} and m["exact"] == {"ok": 61, "of": 103}
    assert m["arguments"] == {"ok": 18, "of": 18}
    assert m["no_card"] == {"cases": 10, "cards_raised": 0, "deadline_cards_raised": 0, "write_attempts": 0}
    # Reads, refusals, questions back and made-up dates all passed; the write kinds did not.
    assert {kind: (n["tool_choice_ok"], n["cases"]) for kind, n in m["by_kind"].items() if n["tool_choice_ok"] != n["cases"]} == {
        "portfolio_change": (1, 6), "manual_add": (1, 6), "deadline_catalog": (1, 6), "deadline_stated": (1, 6),
        "status": (1, 8), "material": (4, 12), "multi_step": (1, 8)}
    # Each of the 42 misses is the same thing: no `propose_*` call, and a reply that asks to confirm.
    missed = [item for item in run["items"] if not m["per_case"][item["id"]]["tool_ok"]]
    assert len(missed) == 42
    assert not any(call["tool"].startswith("propose_") for item in missed for call in item["calls"])
    assert all("确认" in item["reply"] for item in missed)


def test_the_run_after_the_prompt_change_and_what_it_still_missed():
    run = run_of(AFTER_PROMPT_CHANGE)
    m = run["metrics"]
    assert m["tool_choice"] == {"ok": 102, "of": 103} and m["exact"] == {"ok": 101, "of": 103}
    assert m["arguments"] == {"ok": 58, "of": 59} and m["arguments_any"] == {"ok": 58, "of": 59}
    assert m["asked_back"] == {"cases": 7, "question_mark": 5}
    items = {item["id"]: item for item in run["items"]}
    assert sorted(name for name, verdict in m["per_case"].items() if not verdict["exact"]) == ["manual-add-05", "material-03"]
    # One asked which tier before proposing; the other ticked the item as well as adding the note.
    assert not any(call["tool"].startswith("propose_") for call in items["manual-add-05"]["calls"])
    assert items["material-03"]["calls"][-1]["args"]["ready"] is True
    # Nothing that passed in the first run failed in this one.
    first = run_of(FIRST_RUN)["metrics"]["per_case"]
    assert not [name for name, verdict in first.items() if verdict["exact"] and not m["per_case"][name]["exact"]]


def test_the_one_write_attempt_in_a_no_card_case_was_refused_by_the_server():
    """`refuse-07` names an application id that is not the account's. The case allows the call: the
    point is that the server answers it with a refusal and no card."""
    run = run_of(AFTER_PROMPT_CHANGE)
    assert run["metrics"]["no_card"] == {"cases": 10, "cards_raised": 0, "deadline_cards_raised": 0, "write_attempts": 1}
    attempted = [item for item in run["items"] if run["metrics"]["per_case"][item["id"]].get("write_attempted")]
    assert [item["id"] for item in attempted] == ["refuse-07"]
    first = attempted[0]["calls"][0]
    assert (first["tool"], first["outcome"], first["refusal"]) == ("propose_application_status", "refused", "未执行：没有这个申请。")
    assert attempted[0]["cards"] == [] and attempted[0]["applications_changed"] is False


def test_both_live_runs_together_stayed_inside_the_approved_two_yuan():
    spent = run_of(FIRST_RUN)["cost_cny_upper_bound"] + run_of(AFTER_PROMPT_CHANGE)["cost_cny_upper_bound"]
    assert spent == pytest.approx(1.2546) and spent <= 2.0


def test_the_wording_the_second_run_was_measured_on_is_still_in_place():
    """The second run's counts belong to this wording. If it changes, they describe another prompt:
    say so beside them in `docs/measurements.md` (a new run needs the owner's approval of its cost)."""
    assert "propose_ 开头的工具自己不写入" in graph_module.SYSTEM_PROMPT and "不要先用文字问" in graph_module.SYSTEM_PROMPT
    for tool in TOOLS:
        if tool.name in graph_module.CONFIRMED_TOOLS:
            assert "调用后界面出现确认卡片" in tool.description and "直接调用" in tool.description, tool.name


def test_only_the_live_runs_this_file_replays_are_recorded():
    """A result file nobody replays could be quoted without being checked."""
    assert sorted(path.name for path in RESULTS.glob("tools-*.json")) == [AFTER_PROMPT_CHANGE.name, FIRST_RUN.name]
