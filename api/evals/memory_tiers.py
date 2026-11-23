"""How many tokens the advisor's model is sent per step, before and after the memory tiers
(`app.agent.memory`), on representative threads. No model is called.

    python -m evals.memory_tiers            # needs the local database (catalogue imported)

The threads are built, deterministically, from material in this repository:

- the applicant's messages are the messages of the tool-choice set (`tool_choice_cases.json`) and the
  questions of the faithfulness set;
- the advisor's answers to requirement questions are the 31 checked answers of the faithfulness set
  (`faithfulness_set_v2.json`, DeepSeek's real output, joined sentence by sentence); the short replies
  after a tool call are written here;
- the tool replies are what the real tools return on this database for the tool-choice set's eval
  account (`run_tools.Fixture`): `get_my_applications`, `get_my_profile`, `search_programs`.

Three threads: `qa` (mostly requirement questions), `manage` (reading and changing applications),
`verbose` (the `qa` thread with every answer three times as long, for a model that ignores 「回答简洁」).
For every turn the script counts what one model step would carry: the whole thread (what was sent
before) and the tiered view (middle and recent tiers, plus the far tier's text without a summary,
which is its largest form: the sentence-by-sentence fallback and the ledger). Counts are tiktoken
`cl100k_base`, which is not the chat model's tokenizer, and `memory.estimate_tokens`.
"""

import asyncio
import json
import sys
from collections import defaultdict
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent import memory

HERE = Path(__file__).resolve().parent


def _encoder():
    import tiktoken

    return tiktoken.get_encoding("cl100k_base")


def cl100k(messages, encode) -> int:
    total = 0
    for m in messages:
        total += memory.MESSAGE_OVERHEAD + len(encode(m.content if isinstance(m.content, str) else str(m.content)))
        for call in getattr(m, "tool_calls", None) or []:
            total += len(encode(call["name"] + json.dumps(call.get("args") or {}, ensure_ascii=False)))
    return total


class Material:
    def __init__(self) -> None:
        cases = json.loads((HERE / "tool_choice_cases.json").read_text())
        self.doc = cases
        self.by_kind = defaultdict(list)
        for case in cases["cases"]:
            self.by_kind[case["kind"]].append(case["message"])
        faithful = json.loads((HERE / "faithfulness_set_v2.json").read_text())["sentences"]
        grouped, questions = defaultdict(list), {}
        for row in faithful:
            grouped[row["question_id"]].append((row["sentence_index"], row["claim"]))
            questions[row["question_id"]] = row["question"]
        self.answers = [(questions[q], "".join(c for _, c in sorted(rows))) for q, rows in sorted(grouped.items())]
        self.tool_results = self._tool_results()

    def _tool_results(self) -> dict[str, str]:
        from evals.run_tools import Fixture

        from app.agent.tools import get_my_applications, get_my_profile, search_programs

        fixture = Fixture(self.doc["fixture"])
        problems = fixture.problems()
        if problems:
            raise SystemExit("not measuring: " + "; ".join(problems))
        try:
            fixture.build()
            config = {"configurable": {"client_id": fixture.subject}}
            return {
                "get_my_applications": get_my_applications.invoke({}, config=config),
                "get_my_profile": get_my_profile.invoke({}, config=config),
                "search_programs": search_programs.invoke({"keyword": "帝国理工 Computing"}),
            }
        finally:
            fixture.remove()


def _id(prefix: str, n: int) -> str:
    return f"{prefix}-{n:03d}"


def qa_turn(m: Material, i: int, repeat: int = 1) -> list:
    question, answer = m.answers[i % len(m.answers)]
    return [HumanMessage(content=question), AIMessage(content=answer * repeat)]


def search_turn(m: Material, i: int) -> list:
    rows = json.loads(m.tool_results["search_programs"]) if m.tool_results["search_programs"].startswith("[") else []
    names = "、".join(f"{r['school']} {r['program']}" for r in rows[:5])
    call = {"name": "search_programs", "args": {"keyword": "帝国理工 Computing"}, "id": _id("s", i)}
    return [HumanMessage(content=m.by_kind["search"][i % len(m.by_kind["search"])]),
            AIMessage(content="", tool_calls=[call]),
            ToolMessage(content=m.tool_results["search_programs"], tool_call_id=call["id"], name=call["name"]),
            AIMessage(content=f"学校库里找到 {len(rows)} 个项目：{names}。要把哪一个加入你的申请？")]


def read_turn(m: Material, i: int) -> list:
    call = {"name": "get_my_applications", "args": {}, "id": _id("r", i)}
    return [HumanMessage(content=m.by_kind["applications_read"][i % len(m.by_kind["applications_read"])]),
            AIMessage(content="", tool_calls=[call]),
            ToolMessage(content=m.tool_results["get_my_applications"], tool_call_id=call["id"], name=call["name"]),
            AIMessage(content="你现在有 6 个申请：港大计算机科学（考虑中）、帝国理工 Computing（准备中）等。"
                              "其中两个还没有截止日期，学校库里有采集到的轮次，要我按学校库的日期记上吗？")]


def change_turn(m: Material, i: int, answered: bool) -> list:
    read = {"name": "get_my_applications", "args": {}, "id": _id("cr", i)}
    call = {"name": "propose_application_status",
            "args": {"application_id": "catalog:university-of-hong-kong-master-of-science-in-computer-sc-b9098c",
                     "status": "submitted"}, "id": _id("c", i)}
    turn = [HumanMessage(content=m.by_kind["status"][i % len(m.by_kind["status"])]),
            AIMessage(content="", tool_calls=[read]),
            ToolMessage(content=m.tool_results["get_my_applications"], tool_call_id=read["id"], name=read["name"]),
            AIMessage(content="", tool_calls=[call])]
    if answered:
        turn += [ToolMessage(content="已执行：把「香港大学 Master of Science in Computer Science」的申请状态改为已提交。",
                             tool_call_id=call["id"], name=call["name"]),
                 AIMessage(content="已改好：港大计算机科学的申请状态现在是已提交。")]
    return turn


def profile_turn(m: Material, i: int) -> list:
    call = {"name": "update_my_profile", "args": {"fields_json": "{\"english_score\": \"IELTS 7.5\"}"}, "id": _id("p", i)}
    return [HumanMessage(content=m.by_kind["profile_update"][i % len(m.by_kind["profile_update"])]),
            AIMessage(content="", tool_calls=[call]),
            ToolMessage(content="已更新档案：{\"english_score\": \"IELTS 7.5\"}", tool_call_id=call["id"], name=call["name"]),
            AIMessage(content="已记下：雅思 7.5。")]


def threads(m: Material) -> dict[str, list[list]]:
    qa = [qa_turn(m, i) if i % 5 else search_turn(m, i) for i in range(40)]
    verbose = [qa_turn(m, i, 3) if i % 5 else search_turn(m, i) for i in range(40)]
    manage = []
    for i in range(40):
        kind = i % 6
        manage.append([read_turn, search_turn][kind % 2](m, i) if kind < 2 else
                      change_turn(m, i, answered=kind != 3) if kind < 4 else
                      profile_turn(m, i) if kind == 4 else qa_turn(m, i))
    return {"qa": qa, "manage": manage, "verbose": verbose}


class AtTheCap:
    """Stands in for the summarising model: answers with a summary as long as the prompt allows (400
    characters, cut from the dialogue it was given), so the summary path is measured at its largest."""

    def with_config(self, **kwargs):
        return self

    async def ainvoke(self, prompt: str) -> AIMessage:
        dialogue = prompt.split("新的对话：", 1)[1]
        return AIMessage(content=dialogue.replace("\n", " ")[:400])


def _old_intent_history(thread: list) -> str:
    """What the router was shown before the tiers: the last six messages' text, whole."""
    return "\n".join(f"{'用户' if isinstance(m, HumanMessage) else '顾问'}：{m.content}" for m in thread[:-1][-6:]
                     if isinstance(m, (HumanMessage, AIMessage)) and isinstance(m.content, str) and m.content)


def measure(turns: list[list], encode) -> list[dict]:
    rows = []
    summary, covered, calls = "", 0, 0
    for k in range(1, len(turns) + 1):
        # The step that answers turn k: every earlier turn, and turn k's question.
        thread = [msg for turn in turns[: k - 1] for msg in turn] + [turns[k - 1][0]]
        seen = memory.view(thread)
        t = memory.tiers(thread)
        far = [HumanMessage(content=seen.far)] if seen.far else []
        done = asyncio.run(memory.refresh(thread, summary, covered, AtTheCap))
        if done.update:
            summary, covered, calls = done.update["memory_summary"], done.update["memory_turns"], calls + 1
        summarised = memory.view(thread, summary, covered)
        far_summarised = [HumanMessage(content=summarised.far)] if summarised.far else []
        rows.append({
            "turn": k,
            "whole_cl100k": cl100k(thread, encode),
            "tiered_cl100k": cl100k(seen.history + far, encode),
            "tiered_estimate": memory.messages_tokens(seen.history) + memory.estimate_tokens(seen.far),
            "with_summary_cl100k": cl100k(summarised.history + far_summarised, encode),
            "summary_calls_so_far": calls,
            "tiers": [len(t.far), len(t.middle), len(t.recent)],
            "intent_history_cl100k": len(encode(memory.intent_history(thread))),
            "intent_history_before_cl100k": len(encode(_old_intent_history(thread))),
        })
    return rows


def calibration(turns_by_name: dict[str, list[list]], m: Material, encode) -> dict:
    """The estimate against cl100k over every distinct text the threads carry."""
    texts = {msg.content for turns in turns_by_name.values() for turn in turns for msg in turn if msg.content}
    texts |= set(m.tool_results.values())
    ratios = sorted(memory.estimate_tokens(t) / max(1, len(encode(t))) for t in texts)
    total_est = sum(memory.estimate_tokens(t) for t in texts)
    total_cl = sum(len(encode(t)) for t in texts)
    return {"texts": len(texts), "total_estimate": total_est, "total_cl100k": total_cl,
            "ratio_min": round(ratios[0], 3), "ratio_median": round(ratios[len(ratios) // 2], 3),
            "ratio_max": round(ratios[-1], 3)}


def main() -> int:
    encode = _encoder().encode
    m = Material()
    built = threads(m)
    result = {
        "budgets": {"recent": memory.RECENT_BUDGET, "recent_min_turns": memory.RECENT_MIN_TURNS,
                    "middle": memory.MIDDLE_BUDGET, "summary_trigger": memory.SUMMARY_TRIGGER,
                    "fallback": memory.FALLBACK_BUDGET, "summary_max_tokens": memory.SUMMARY_MAX_TOKENS,
                    "summary_input": memory.SUMMARY_INPUT_BUDGET, "ledger_idle_max": memory.LEDGER_IDLE_MAX,
                    "intent": memory.INTENT_BUDGET},
        "tool_results_cl100k": {k: len(encode(v)) for k, v in m.tool_results.items()},
        "calibration": calibration(built, m, encode),
        "threads": {name: measure(turns, encode) for name, turns in built.items()},
    }
    json.dump(result, sys.stdout, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
