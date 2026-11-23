"""The advisor's memory tiers (`app.agent.memory`): what the model is shown of a long conversation.

The pure parts run without a database: sentence cutting, the token estimate, where the tiers fall,
that a tool call stays with its reply, the middle tier's short form, the ledger of changes, and the
summary's incremental update and fallback, on stand-in models. The last tests run the real graph
through the endpoint, on a scripted model and a checkpointer of its own, and check that the stored
thread is complete while the model saw the tiers. No paid model is called anywhere.
"""

import asyncio
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from app.agent import graph as graph_module
from app.agent import halt, intent, memory, passages
from app.agent.confirm import CHANGED, DECLINED
from app.agent.graph import CONFIRMED_TOOLS, UNANSWERED_CALL, build_graph, with_unanswered_calls_closed
from app.agent.llm import ModelNotConfigured
from app.agent.stated import stamp
from app.config import settings
from app.deps import COOKIE_NAME
from app.main import app
from app.routers import advisor

# ---------------------------------------------------------------------------------------------------
# Building threads
# ---------------------------------------------------------------------------------------------------


def call(name: str, **args) -> dict:
    return {"name": name, "args": args, "id": f"call-{uuid.uuid4().hex[:8]}"}


def qa(question: str, answer: str) -> list:
    return [HumanMessage(content=question), AIMessage(content=answer)]


def with_tool(question: str, name: str, result: str | None, answer: str = "好的。", **args) -> list:
    """A turn with one tool call; `result` None leaves the call unanswered (a confirm nobody answered)."""
    c = call(name, **args)
    turn = [HumanMessage(content=question), AIMessage(content="", tool_calls=[c])]
    if result is not None:
        turn += [ToolMessage(content=result, tool_call_id=c["id"], name=name), AIMessage(content=answer)]
    return turn


def flat(turns: list[list]) -> list:
    return [m for turn in turns for m in turn]


LONG_ANSWER = "这个项目要求均分 85 分以上 [1]。雅思总分 7.0，单项不低于 6.5 [2]。另外需要两封推荐信。截止日期以官网为准。" * 3


@pytest.fixture
def small_budgets(monkeypatch):
    """Budgets small enough that a dozen short turns reach every tier."""
    monkeypatch.setattr(memory, "RECENT_BUDGET", 300)
    monkeypatch.setattr(memory, "MIDDLE_BUDGET", 300)
    monkeypatch.setattr(memory, "SUMMARY_TRIGGER", 150)
    monkeypatch.setattr(memory, "FALLBACK_BUDGET", 400)


# ---------------------------------------------------------------------------------------------------
# Sentences
# ---------------------------------------------------------------------------------------------------


def test_chinese_sentences_end_at_full_stops_and_keep_their_citation_marks():
    text = "港大计算机硕士要求均分 85 分 [1]。雅思 6.5！你满足吗？剩下的"
    assert memory.sentences(text) == ["港大计算机硕士要求均分 85 分 [1]。", "雅思 6.5！", "你满足吗？", "剩下的"]
    assert memory.first_sentences(text) == "港大计算机硕士要求均分 85 分 [1]。雅思 6.5！" + memory.CUT


def test_english_sentences_skip_decimals_abbreviations_and_initials():
    text = "Your GPA 3.5 meets it. However, e.g. IELTS 6.5 is needed! The U.S. page says so. More."
    assert memory.sentences(text) == [
        "Your GPA 3.5 meets it.", "However, e.g. IELTS 6.5 is needed!", "The U.S. page says so.", "More.",
    ]
    assert memory.first_sentences(text, 1) == "Your GPA 3.5 meets it." + memory.CUT


def test_mixed_text_and_quotes_stay_with_their_sentence():
    text = "截止日期是 2027 年 1 月 15 日（Main Round）。“请以官网为准。”See the page [3]. 好。"
    assert memory.sentences(text) == [
        "截止日期是 2027 年 1 月 15 日（Main Round）。", "“请以官网为准。”", "See the page [3].", "好。",
    ]
    # English after Chinese is joined without a space, English after English with one.
    assert memory.first_sentences("First one. Second one. Third.") == "First one. Second one." + memory.CUT


def test_lists_break_at_lines_and_a_list_number_is_not_a_sentence_end():
    text = "要求如下：\n1. 均分 85\n2. 雅思 6.5\n- 推荐信两封。另外附简历"
    assert memory.sentences(text) == ["要求如下：", "1. 均分 85", "2. 雅思 6.5", "- 推荐信两封。", "另外附简历"]


def test_a_code_block_is_one_short_sentence():
    text = "这样写：\n```python\nprint('a. b. c.')\nx = 1\n```\n然后保存。"
    assert memory.sentences(text) == ["这样写：", memory.CODE, "然后保存。"]


def test_a_short_reply_is_kept_whole_without_a_cut_mark_and_a_long_sentence_is_cut_to_the_limit():
    assert memory.first_sentences("好的，已记下。") == "好的，已记下。"
    long = "这" * 300 + "。"
    cut = memory.first_sentences(long, limit=50)
    assert cut.endswith(memory.CUT) and len(cut) == 49 + len(memory.CUT)
    assert memory.first_sentences("") == ""


# ---------------------------------------------------------------------------------------------------
# The token estimate
# ---------------------------------------------------------------------------------------------------


def test_the_estimate_counts_wide_characters_heavier_than_ascii():
    assert memory.estimate_tokens("") == 0
    assert memory.estimate_tokens("你好世界") == 5  # 4 x 1.2, rounded up
    assert memory.estimate_tokens("abcdef") == 2  # 6 / 3.0
    call_message = AIMessage(content="", tool_calls=[call("search_programs", keyword="帝国理工")])
    assert memory.message_tokens(call_message) > memory.MESSAGE_OVERHEAD


# ---------------------------------------------------------------------------------------------------
# Tiers
# ---------------------------------------------------------------------------------------------------


def test_a_turn_starts_at_every_human_message():
    thread = flat([qa("一", "甲。"), with_tool("二", "get_my_profile", "{}"), [HumanMessage(content="三")]])
    split = memory.turns(thread)
    assert [len(t) for t in split] == [2, 4, 1]
    assert all(isinstance(t[0], HumanMessage) for t in split)


def test_a_short_conversation_is_all_recent_and_shown_unchanged():
    thread = flat([qa("一", "甲。"), qa("二", "乙。"), [HumanMessage(content="三")]])
    seen = memory.view(thread)
    assert seen.far == "" and seen.history == thread


def test_the_tiers_fall_by_budget_and_the_last_two_turns_are_always_whole(small_budgets):
    turns = [qa(f"问题{i}", LONG_ANSWER) for i in range(12)] + [[HumanMessage(content="现在的问题")]]
    t = memory.tiers(flat(turns))
    assert len(t.far) + len(t.middle) + len(t.recent) == 13
    assert len(t.recent) >= memory.RECENT_MIN_TURNS and len(t.middle) > 0 and len(t.far) > 0
    # The recent turns before the two always kept fit the budget, and the next older one would not.
    extra = t.recent[: -memory.RECENT_MIN_TURNS]
    assert memory.messages_tokens(flat(extra)) <= memory.RECENT_BUDGET
    assert memory.messages_tokens(flat([t.middle[-1], *extra])) > memory.RECENT_BUDGET
    assert sum(memory.messages_tokens(memory.compact(turn)) for turn in t.middle) <= memory.MIDDLE_BUDGET

    # A huge turn just before the current one is still kept whole.
    huge = with_tool("查一下", "get_my_applications", json.dumps([{"x": "y" * 50}] * 200))
    t = memory.tiers(flat(turns[:-1] + [huge, [HumanMessage(content="然后呢")]]))
    assert t.recent[-2:] == [huge, [HumanMessage(content="然后呢")]]


def test_the_tiers_do_not_move_within_a_turn_and_only_move_forward_as_turns_are_added(small_budgets):
    turns = [qa(f"问题{i}", LONG_ANSWER) for i in range(10)]
    current = [HumanMessage(content="帮我查"), AIMessage(content="", tool_calls=[call("get_my_applications")])]
    before = memory.tiers(flat(turns) + current[:1])
    during = memory.tiers(flat(turns) + current + [ToolMessage(content="x" * 5000, tool_call_id="t")])
    assert (before.middle_start, before.recent_start) == (during.middle_start, during.recent_start)

    # Turns of very different sizes: short questions, long answers, big tool replies, changes.
    mixed = []
    for i in range(30):
        mixed.append([
            qa(f"短{i}", "好。"),
            qa(f"长{i}", LONG_ANSWER * (1 + i % 3)),
            with_tool(f"读{i}", "get_my_applications", "x" * (200 * (i % 7)), "读到了。"),
            with_tool(f"改{i}", "propose_application_status", None, application_id="a1", status="submitted"),
        ][(i * 7) % 4])
    middles, recents = [], []
    for k in range(1, len(mixed) + 1):
        t = memory.tiers(flat(mixed[:k]))
        middles.append(t.middle_start)
        recents.append(t.recent_start)
    assert middles == sorted(middles) and recents == sorted(recents)
    assert middles[-1] > 0 and len(set(recents)) > 3


def test_the_recent_budget_is_on_top_of_the_two_turns_always_kept(small_budgets):
    big = with_tool("读申请", "get_my_applications", "x" * 3000, "你有 6 个申请。")
    short = [qa(f"短{i}", "好。") for i in range(5)]
    t = memory.tiers(flat(short + [big, [HumanMessage(content="然后呢")]]))
    assert t.recent == [*short, big, [HumanMessage(content="然后呢")]]


def test_turns_already_summarised_are_not_shown_again_in_the_middle_tier(small_budgets):
    turns = [qa(f"问题{i}", LONG_ANSWER) for i in range(12)] + [[HumanMessage(content="现在")]]
    t = memory.tiers(flat(turns))
    shifted = memory.tiers(flat(turns), covered=t.middle_start + 1)
    assert shifted.middle_start == t.middle_start + 1
    # Never past the recent tier.
    assert memory.tiers(flat(turns), covered=999).middle_start == t.recent_start


# ---------------------------------------------------------------------------------------------------
# Tool calls at the boundaries, and the middle tier's short form
# ---------------------------------------------------------------------------------------------------


def _paired(history: list) -> None:
    """Every tool reply follows the call it answers, and every call is answered (after closing)."""
    closed = with_unanswered_calls_closed(history)
    calls: set[str] = set()
    for message in closed:
        if isinstance(message, AIMessage):
            calls |= {c["id"] for c in message.tool_calls}
        if isinstance(message, ToolMessage):
            assert message.tool_call_id in calls, message
    answered = {m.tool_call_id for m in closed if isinstance(m, ToolMessage)}
    assert calls <= answered


def test_a_tool_call_is_never_split_from_its_reply_at_any_boundary(small_budgets):
    kinds = [
        lambda i: with_tool(f"查项目{i}", "search_programs", json.dumps([{"id": f"p{i}"}] * 10), "找到了。", keyword="港大"),
        lambda i: qa(f"问题{i}", LONG_ANSWER),
        lambda i: with_tool(f"改状态{i}", "propose_application_status", f"{CHANGED}把「港大」的申请状态改为已提交。",
                            "已改好。", application_id="a1", status="submitted"),
        lambda i: with_tool(f"再改{i}", "propose_application_status", None, application_id="a1", status="offered"),
    ]
    turns = []
    for i in range(16):
        turns.append(kinds[i % len(kinds)](i))
        for cut in range(1, len(turns) + 1):
            history = memory.view(flat(turns[:cut])).history
            assert isinstance(history[0], HumanMessage)
            _paired(history)


def test_the_middle_tier_keeps_the_applicant_verbatim_and_cuts_the_advisor(small_budgets):
    said = HumanMessage(content="我想申请港大计算机，均分 86。截止日期是 2027-01-15。", additional_kwargs=stamp())
    first = [said, AIMessage(content="", tool_calls=[c := call("search_programs", keyword="港大")]),
             ToolMessage(content=json.dumps([{"id": "p1", "program": "MSc CS"}] * 20), tool_call_id=c["id"], name="search_programs"),
             AIMessage(content=LONG_ANSWER)]
    turns = [first] + [qa(f"问题{i}", LONG_ANSWER) for i in range(3)] + [[HumanMessage(content="现在")]]
    t = memory.tiers(flat(turns))
    assert first in t.middle
    short = memory.compact(first)
    assert short[0] is said  # the very message, with the day it was sent
    assert len(short) == 2 and not short[1].tool_calls
    assert short[1].content == memory.first_sentences(LONG_ANSWER)
    assert "p1" not in short[1].content  # a read-only tool's reply is dropped


def test_changes_in_the_middle_tier_are_one_line_each_with_their_outcome():
    turn = [HumanMessage(content="改一下"),
            AIMessage(content="", tool_calls=[c1 := call("update_my_profile", fields_json='{"gpa_score": 86}')]),
            ToolMessage(content='已更新档案：{"gpa_score": 86}', tool_call_id=c1["id"], name="update_my_profile"),
            AIMessage(content="", tool_calls=[c2 := call("propose_portfolio_change", program_id="p1", action="add", tier="稳")]),
            ToolMessage(content=f"{DECLINED}把 p1 加入组合。没有改动。\n第二行", tool_call_id=c2["id"], name="propose_portfolio_change"),
            AIMessage(content="", tool_calls=[call("propose_application_status", application_id="a1", status="submitted")]),
            AIMessage(content="好的。")]
    lines = memory.actions(turn)
    assert lines == [
        '〔更新背景〕已更新档案：{"gpa_score": 86}',
        f"〔提议改组合〕{DECLINED}把 p1 加入组合。没有改动。",
        f"〔提议改状态〕申请：a1，状态：已提交 → {memory.UNANSWERED}",
    ]
    assert memory.compact(turn)[1].content == "\n".join([*lines, "好的。"])


def test_every_tool_that_asks_for_a_confirm_is_kept_as_a_change():
    for name in CONFIRMED_TOOLS:
        assert memory._is_action(name), name
    assert not memory._is_action("get_my_applications")


# ---------------------------------------------------------------------------------------------------
# The far tier: fallback, ledger, pending proposals
# ---------------------------------------------------------------------------------------------------


def _long_thread(n: int = 14) -> list[list]:
    turns = [with_tool("我想先申港大", "propose_application_status", None, application_id="hku", status="applying")]
    turns += [with_tool("把 UCL 加进去", "propose_portfolio_change", f"{CHANGED}把「UCL Data Science」加入组合。",
                        "已加入。", program_id="ucl", action="add", tier="稳")]
    turns += [qa(f"爱丁堡问题{i}", LONG_ANSWER) for i in range(n)]
    return turns + [[HumanMessage(content="现在的问题")]]


def test_without_a_summary_the_far_tier_is_shown_sentence_by_sentence_with_the_ledger(small_budgets):
    seen = memory.view(flat(_long_thread()))
    assert seen.far.startswith(memory.FAR_HEADING)
    assert memory.LINES_HEADING in seen.far and memory.SUMMARY_HEADING not in seen.far
    assert "申请者：爱丁堡问题0" in seen.far or "（更早的从略）" in seen.far
    # Both changes survive in the ledger: the one written and the one nobody answered.
    assert "〔提议改组合〕已执行：把「UCL Data Science」加入组合。" in seen.far
    assert f"〔提议改状态〕申请：hku，状态：准备中 → {memory.UNANSWERED}" in seen.far
    assert memory.estimate_tokens(seen.far) < memory.FALLBACK_BUDGET + 200


def test_a_pending_proposal_survives_even_when_the_summary_forgets_it(small_budgets):
    thread = flat(_long_thread())
    t = memory.tiers(thread)
    seen = memory.view(thread, summary="申请者在问爱丁堡的项目。", covered=len(t.far))
    assert "申请者在问爱丁堡的项目。" in seen.far
    assert memory.LINES_HEADING not in seen.far  # every far turn is summarised
    assert f"→ {memory.UNANSWERED}" in seen.far and "UCL Data Science" in seen.far


def test_the_ledger_keeps_every_write_and_unanswered_proposal_and_the_newest_idle_ones():
    n = memory.LEDGER_IDLE_MAX + 5
    turns = []
    for i in range(n):
        turns.append(with_tool(f"改{i}", "update_my_profile", f'已更新档案：{{"n": {i}}}', fields_json="{}"))
        turns.append(with_tool(f"不改{i}", "propose_portfolio_change", f"{DECLINED}把 p{i} 加入组合。没有改动。",
                               program_id=f"p{i}", action="add"))
        turns.append(with_tool(f"没回{i}", "propose_application_status", None, application_id=f"a{i}", status="submitted"))
    entries = memory.ledger(turns)
    assert entries[0] == "（更早的 5 项没有改动的提议从略）"
    assert sum("已更新档案" in e for e in entries) == n
    assert sum(memory.UNANSWERED in e for e in entries) == n
    assert sum(DECLINED in e for e in entries) == memory.LEDGER_IDLE_MAX
    assert f"把 p{n - 1} 加入组合" in entries[-2] and "把 p0 加入组合" not in "".join(entries)


# ---------------------------------------------------------------------------------------------------
# The summary
# ---------------------------------------------------------------------------------------------------


class Summariser:
    """Stands in for the chat model: records each prompt and answers with a numbered summary."""

    def __init__(self, fail: BaseException | None = None, delay: float = 0.0, text: str | None = None):
        self.prompts: list[str] = []
        self.tags: list = []
        self.fail, self.delay, self.text = fail, delay, text

    def __call__(self):
        return self

    def with_config(self, **kwargs):
        self.tags.append(kwargs.get("tags"))
        return self

    async def ainvoke(self, prompt):
        self.prompts.append(prompt)
        await asyncio.sleep(self.delay)
        if self.fail is not None:
            raise self.fail
        return AIMessage(content=self.text if self.text is not None else f"摘要{len(self.prompts)}：讨论了爱丁堡和 UCL。")


def test_nothing_is_summarised_below_the_threshold():
    model = Summariser()
    done = asyncio.run(memory.refresh(flat(_long_thread(3)), "", 0, model))
    assert done.update == {} and done.outcome == "none" and model.prompts == []


def test_the_summary_is_written_once_due_and_then_extended_with_new_turns_only(small_budgets):
    model = Summariser()
    turns = _long_thread()
    done = asyncio.run(memory.refresh(flat(turns), "", 0, model))
    assert done.outcome == "updated"
    covered = done.update["memory_turns"]
    assert done.update["memory_summary"] == "摘要1：讨论了爱丁堡和 UCL。"
    assert covered == len(memory.tiers(flat(turns)).far)
    assert "已有摘要：\n（无）" in model.prompts[0] and "申请者：我想先申港大" in model.prompts[0]
    # The change nobody answered and the one written reach the summariser as lines of their own.
    assert f"顾问操作：〔提议改状态〕申请：hku，状态：准备中 → {memory.UNANSWERED}" in model.prompts[0]
    assert model.tags == [[memory.TAG_NOSTREAM]]

    # The same thread again: nothing new is far, nothing is asked.
    again = asyncio.run(memory.refresh(flat(turns), done.update["memory_summary"], covered, model))
    assert again.outcome == "none" and len(model.prompts) == 1

    # Many more turns: the next call carries the old summary and only the turns after it.
    more = turns[:-1] + [qa(f"曼大问题{i}", LONG_ANSWER) for i in range(14)] + [[HumanMessage(content="再问")]]
    extended = asyncio.run(memory.refresh(flat(more), done.update["memory_summary"], covered, model))
    assert extended.outcome == "updated" and extended.update["memory_turns"] > covered
    assert "已有摘要：\n摘要1：讨论了爱丁堡和 UCL。" in model.prompts[1]
    assert "我想先申港大" not in model.prompts[1] and "曼大问题0" in model.prompts[1]


def test_a_long_backlog_is_summarised_a_slice_at_a_time(small_budgets, monkeypatch):
    monkeypatch.setattr(memory, "SUMMARY_INPUT_BUDGET", 400)
    turns = _long_thread(30)
    far = len(memory.tiers(flat(turns)).far)
    done = asyncio.run(memory.refresh(flat(turns), "", 0, Summariser()))
    assert 0 < done.update["memory_turns"] < far


@pytest.mark.parametrize("model", [
    Summariser(fail=RuntimeError("provider said no")),
    Summariser(text="   "),
])
def test_a_failed_summary_keeps_the_old_one_and_the_turn_goes_on(small_budgets, model):
    thread = flat(_long_thread())
    done = asyncio.run(memory.refresh(thread, "旧摘要", 1, model))
    assert done.update == {"memory_failed_at": len(memory.turns(thread))} and done.outcome.startswith("failed")
    # What the model is shown then: the old summary and the uncovered turns sentence by sentence.
    seen = memory.view(thread, "旧摘要", 1)
    assert "旧摘要" in seen.far and memory.LINES_HEADING in seen.far


def test_no_model_configured_is_a_failed_summary_too(small_budgets):
    def unconfigured():
        raise ModelNotConfigured("CHAT_API_KEY is not set")

    done = asyncio.run(memory.refresh(flat(_long_thread()), "", 0, unconfigured))
    assert done.update == {"memory_failed_at": 17} and done.outcome == "failed: ModelNotConfigured"


def test_a_slow_summary_is_not_waited_for_but_is_not_cancelled_either(small_budgets, monkeypatch):
    """The call the turn stops waiting for still finishes, so its tokens are still charged."""
    monkeypatch.setattr(memory, "SUMMARY_TIMEOUT_SECONDS", 0.05)
    model = Summariser(delay=0.3)
    finished = []

    async def scenario():
        done = await memory.refresh(flat(_long_thread()), "", 0, model)
        assert done.outcome == "failed: timeout" and done.update == {"memory_failed_at": 17}
        assert len(memory._late) == 1
        await asyncio.gather(*memory._late)
        finished.append(True)

    asyncio.run(scenario())
    assert finished and not memory._late


def test_a_late_call_that_fails_is_not_left_for_asyncio_to_log(small_budgets, monkeypatch):
    monkeypatch.setattr(memory, "SUMMARY_TIMEOUT_SECONDS", 0.05)
    model = Summariser(delay=0.2, fail=RuntimeError("401 key sk-something"))
    reported = []

    async def scenario():
        asyncio.get_running_loop().set_exception_handler(lambda loop, context: reported.append(context))
        done = await memory.refresh(flat(_long_thread()), "", 0, model)
        assert done.outcome == "failed: timeout"
        (late,) = memory._late
        await asyncio.wait({late})
        await asyncio.sleep(0)

    asyncio.run(scenario())
    import gc

    gc.collect()
    assert reported == [] and not memory._late


def test_after_a_failure_the_next_tries_wait_a_few_turns(small_budgets):
    model = Summariser()
    thread = flat(_long_thread())
    count = len(memory.turns(thread))
    waiting = asyncio.run(memory.refresh(thread, "", 0, model, failed_at=count - 1))
    assert waiting.outcome == "none" and model.prompts == []
    again = asyncio.run(memory.refresh(thread, "", 0, model, failed_at=count - memory.SUMMARY_RETRY_TURNS))
    assert again.outcome == "updated" and again.update["memory_failed_at"] == 0


def test_below_the_trigger_every_uncovered_far_line_is_shown(small_budgets):
    thread = flat(_long_thread())
    t = memory.tiers(thread)
    lines = [line for turn in t.far for line in memory.far_lines(turn)]
    if memory._lines_cost(lines) < memory.SUMMARY_TRIGGER:
        assert "（更早的从略）" not in memory.view(thread).far
    assert memory.FALLBACK_BUDGET > memory.SUMMARY_TRIGGER


# ---------------------------------------------------------------------------------------------------
# The intent router's view
# ---------------------------------------------------------------------------------------------------


def test_the_router_sees_the_newest_short_lines_and_no_tool_output(small_budgets):
    turns = [qa(f"问题{i}", LONG_ANSWER) for i in range(12)]
    turns += [with_tool("查港大", "search_programs", '[{"id": "secret-row"}]', "找到一个项目。", keyword="港大")]
    turns += [[HumanMessage(content="就它吧")]]
    text = memory.intent_history(flat(turns))
    lines = text.splitlines()
    assert lines[-2:] == ["用户：查港大", "顾问：找到一个项目。"]
    assert "secret-row" not in text and "就它吧" not in text
    assert all(len(line) <= len("顾问：") + memory.REPLY_CHARS + len(memory.CUT) for line in lines if line.startswith("顾问"))
    assert memory.estimate_tokens(text) <= memory.INTENT_BUDGET + len(lines)
    assert memory.intent_history([HumanMessage(content="第一句")]) == ""


def test_a_long_message_from_the_applicant_reaches_the_router_cut_not_dropped():
    pasted = "我本科武汉大学计算机，均分 86，雅思 7.0，想申港大和帝国理工的计算机硕士。" * 12
    thread = flat([qa(pasted, "收到。我记下了。"), [HumanMessage(content="就加它吧")]])
    lines = memory.intent_history(thread).splitlines()
    assert lines[0].startswith("用户：我本科武汉大学计算机") and len(lines[0]) <= len("用户：") + memory.INTENT_USER_CHARS + len(memory.CUT)
    assert lines[1] == "顾问：收到。我记下了。"


# ---------------------------------------------------------------------------------------------------
# The graph's nodes
# ---------------------------------------------------------------------------------------------------


class Recorder(BaseChatModel):
    """Records what it was sent and replies with plain text."""

    seen: list = []

    @property
    def _llm_type(self) -> str:
        return "recorder"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(list(messages))
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="答。"))])


def test_the_main_agent_is_shown_the_tiers_and_the_state_is_not_changed(small_budgets, monkeypatch):
    model = Recorder(seen=[])
    monkeypatch.setattr(graph_module, "get_chat_model", lambda **kwargs: model)
    thread = flat(_long_thread())
    stored = [m.model_copy(deep=True) for m in thread]
    state = {"messages": thread, "memory_summary": "摘要：讨论了爱丁堡。", "memory_turns": 2, "steps": 0}
    update = asyncio.run(graph_module.main_agent(state))

    assert thread == stored  # the thread the checkpoint keeps is untouched
    assert update["messages"][0].content == "答。"
    sent = model.seen[0]
    assert isinstance(sent[0], SystemMessage) and sent[0].content.startswith(graph_module.SYSTEM_PROMPT)
    assert "摘要：讨论了爱丁堡。" in sent[0].content and memory.LEDGER_HEADING in sent[0].content
    assert len(sent) - 1 < len(thread)
    assert sent[-1].content == "现在的问题"
    _paired(sent[1:])


def test_an_unanswered_call_in_the_recent_tier_is_still_closed_for_the_model(monkeypatch):
    model = Recorder(seen=[])
    monkeypatch.setattr(graph_module, "get_chat_model", lambda **kwargs: model)
    thread = flat([with_tool("改状态", "propose_application_status", None, application_id="a1", status="submitted"),
                   [HumanMessage(content="先不改了，问别的")]])
    asyncio.run(graph_module.main_agent({"messages": thread, "steps": 0}))
    sent = model.seen[0]
    assert any(isinstance(m, ToolMessage) and m.content == UNANSWERED_CALL for m in sent)
    assert len(thread) == 3  # the stored thread gets no closing reply


def test_classify_intent_extends_the_summary_beside_the_router(small_budgets, monkeypatch):
    model = Summariser()
    asked: list[str] = []

    async def classify(query, history):
        asked.append(history)
        return {"intent": "通用问答", "confidence": 1.0}

    monkeypatch.setattr(intent, "classify", classify)
    monkeypatch.setattr(graph_module, "get_chat_model", lambda **kwargs: model)
    monkeypatch.setattr(passages, "route", lambda session, question, label: [])
    monkeypatch.setattr(graph_module, "SessionLocal", _NoSession)
    thread = flat(_long_thread())
    update = asyncio.run(graph_module.classify_intent({"messages": thread}))
    assert update["memory_summary"].startswith("摘要1") and update["memory_turns"] > 0
    assert update["trace"]["memory_summary"] == "updated"
    assert asked == [memory.intent_history(thread)]


def test_a_router_outage_is_raised_and_the_summary_call_already_sent_still_finishes(small_budgets, monkeypatch):
    model = Summariser(delay=0.2)

    async def down(query, history):
        await asyncio.sleep(0.05)  # the summary call is sent by then
        raise RuntimeError("router down")

    monkeypatch.setattr(intent, "classify", down)
    monkeypatch.setattr(graph_module, "get_chat_model", lambda **kwargs: model)

    async def scenario():
        with pytest.raises(RuntimeError, match="router down"):
            await graph_module.classify_intent({"messages": flat(_long_thread())})
        assert len(model.prompts) == 1 and len(memory._late) == 1
        (late,) = memory._late
        reply = await late
        assert reply.content.startswith("摘要1")

    asyncio.run(scenario())


class _NoSession:
    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False


# ---------------------------------------------------------------------------------------------------
# Through the endpoint, with the checkpoint
# ---------------------------------------------------------------------------------------------------

USAGE = {"input_tokens": 40, "output_tokens": 2, "total_tokens": 42}
SUMMARY = "摘要：申请者一直在问爱丁堡的项目。"


class Scripted(BaseChatModel):
    """Answers every question at length, and the summary prompt with `SUMMARY`; records what the
    agent was sent."""

    seen: list = []

    @property
    def _llm_type(self) -> str:
        return "scripted-memory"

    def bind_tools(self, tools, **kwargs):
        return self

    def _reply(self, messages) -> AIMessage:
        if isinstance(messages[0], HumanMessage) and str(messages[0].content).startswith("你在为留学申请顾问压缩"):
            return AIMessage(content=SUMMARY, usage_metadata=USAGE)
        self.seen.append(list(messages))
        return AIMessage(content=LONG_ANSWER, usage_metadata=USAGE)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=self._reply(messages))])

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        reply = self._reply(messages)
        chunk = AIMessageChunk(content=reply.content, usage_metadata=USAGE)
        if run_manager:
            await run_manager.on_llm_new_token(reply.content, chunk=ChatGenerationChunk(message=chunk))
        yield ChatGenerationChunk(message=chunk)


@pytest.mark.usefixtures("require_db")
def test_a_long_conversation_is_stored_whole_while_the_model_sees_the_tiers(small_budgets, monkeypatch):
    from app.agent import checkpoint

    saver = checkpoint.Checkpointer()
    graph = build_graph(checkpointer=saver)
    monkeypatch.setattr(advisor, "graph", graph)
    monkeypatch.setattr(settings, "chat_api_key", "test-key")
    monkeypatch.setattr(settings, "advisor_subject_limits", "1000/60")
    monkeypatch.setattr(settings, "advisor_ip_limits", "1000/60")
    model = Scripted(seen=[])

    async def general(query, history):
        return {"intent": "通用问答", "confidence": 1.0}

    monkeypatch.setattr(graph_module, "get_chat_model", lambda **kwargs: model)
    monkeypatch.setattr(intent, "classify", general)
    client = TestClient(app)
    conversation = f"m{uuid.uuid4().hex[:10]}"
    tokens: list[str] = []
    try:
        for i in range(14):
            response = client.post(CHAT, json={"conversationId": conversation, "message": f"爱丁堡问题{i}"})
            assert response.status_code == 200
            tokens += [e["text"] for e in _events(response) if e["type"] == "token"]
        subject = client.cookies[COOKIE_NAME]
        thread = checkpoint.thread_id(subject, conversation)
        state = asyncio.run(graph.aget_state({"configurable": {"thread_id": thread}})).values
    finally:
        saver.close()
        advisor._running.clear()
        halt._requested.clear()

    stored = state["messages"]
    # Every question and every whole answer is in the thread.
    assert [m.content for m in stored if isinstance(m, HumanMessage)] == [f"爱丁堡问题{i}" for i in range(14)]
    assert [m.content for m in stored if isinstance(m, AIMessage)] == [LONG_ANSWER] * 14
    # The summary is kept with the conversation, and was never streamed to the applicant.
    assert state["memory_summary"] == SUMMARY and state["memory_turns"] > 0
    assert all(SUMMARY not in text for text in tokens)
    # The last call saw the summary in its system prompt and fewer messages than the thread holds.
    last = model.seen[-1]
    assert SUMMARY in last[0].content
    assert len(last) - 1 < len(stored) - 1
    assert last[-1].content == "爱丁堡问题13"


CHAT = "/api/advisor/chat"


def _events(response) -> list[dict]:
    return [json.loads(line[len("data: "):]) for line in response.text.splitlines() if line.startswith("data: ")]
