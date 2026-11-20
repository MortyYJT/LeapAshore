import assert from "node:assert/strict";
import { test } from "node:test";

import type { AdvisorEvent } from "./advisor.ts";
import {
  answerText,
  applyEvent,
  beginAnswer,
  failTurn,
  finishTurn,
  formatDuration,
  hasPending,
  newTurn,
  restore,
  serialize,
  starterQuestions,
  stepTitle,
  stopTurn,
  voidPending,
  type ConfirmBlock,
  type StepBlock,
  type Turn,
} from "./advisor-run.ts";
import { overviewOf } from "./overview.ts";
import type { ApplicationRecord } from "./application-records.ts";

const play = (turn: Turn, events: AdvisorEvent[]) => events.reduce(applyEvent, turn);
const steps = (turn: Turn) => turn.blocks.filter((b): b is StepBlock => b.type === "step");
const confirms = (turn: Turn) => turn.blocks.filter((b): b is ConfirmBlock => b.type === "confirm");

const SEARCH: AdvisorEvent[] = [
  { type: "step", id: "t-intent", status: "running", kind: "intent", name: "classify_intent", title: "判断问题类型" },
  { type: "step", id: "t-intent", status: "done", ms: 412, result: "归为「修改申请」，交给顾问处理" },
  { type: "intent", intent: "业务操作", confidence: 1 },
  { type: "step", id: "call-1", status: "running", kind: "tool", name: "search_programs", title: "搜索项目", args: [{ label: "关键词", value: "悉尼 计算机" }] },
  { type: "tool", name: "search_programs" },
  { type: "step", id: "call-1", status: "done", ms: 80, result: "找到 2 个项目", items: ["悉尼大学 计算机科学硕士"] },
  { type: "token", text: "找到" },
  { type: "token", text: "了。" },
];

const PROPOSAL: AdvisorEvent[] = [
  { type: "step", id: "call-2", status: "running", kind: "tool", name: "propose_portfolio_change", title: "提议修改" },
  { type: "step", id: "call-2", status: "waiting", ms: 30, result: "等你确认" },
  {
    type: "confirm", id: "int-1", stepId: "call-2", summary: "把「甲大学 数据科学硕士」加入选校组合，档位：稳",
    target: { programId: "p1", school: "甲大学", program: "数据科学硕士" },
    changes: [{ label: "选校组合", before: "不在组合里", after: "加入" }],
  },
];

test("a step is one block from its first event to its last, and the reply follows the steps in order", () => {
  const turn = finishTurn(play(newTurn("t1", "有哪些项目"), SEARCH));
  assert.deepEqual(turn.blocks.map((b) => b.type), ["step", "step", "text"]);
  const [intent, search] = steps(turn);
  assert.equal(intent.status, "done");
  assert.equal(intent.ms, 412);
  assert.equal(intent.name, "classify_intent");
  assert.deepEqual(search.args, [{ label: "关键词", value: "悉尼 计算机" }]);
  assert.equal(search.result, "找到 2 个项目");
  assert.equal(answerText(turn), "找到了。");
  assert.equal(turn.state, "done");
  assert.equal(turn.refused, false);
});

test("text after a step starts a new block, so the transcript keeps what happened in order", () => {
  const turn = play(newTurn("t1", "q"), [
    { type: "token", text: "先查一下。" },
    { type: "step", id: "c1", status: "running", kind: "tool", name: "get_my_profile" },
    { type: "step", id: "c1", status: "done", ms: 5, result: "已填 3 项，未填 8 项" },
    { type: "token", text: "查到了。" },
  ]);
  assert.deepEqual(turn.blocks.map((b) => b.type), ["text", "step", "text"]);
  assert.equal(answerText(turn), "先查一下。\n\n查到了。");
});

test("a tool this page has never heard of is drawn under its own name", () => {
  const turn = play(newTurn("t1", "q"), [
    { type: "step", id: "c9", status: "running", kind: "tool", name: "set_application_deadline", args: [{ label: "deadline", value: "2027-01-15" }] },
    { type: "step", id: "c9", status: "done", ms: 12, result: "已保存", write: true },
  ]);
  const [step] = steps(turn);
  assert.equal(stepTitle(step), "set_application_deadline");
  assert.equal(step.write, true);
  assert.equal(stepTitle({ name: "search_programs" }), "搜索项目");
  assert.equal(stepTitle({ name: "search_programs", title: "找项目" }), "找项目");
});

test("a refused gate marks the turn as a refusal and draws no source cards", () => {
  const turn = finishTurn(
    play(newTurn("t1", "某校的要求？"), [
      { type: "citations", gate: "refuse", citations: [] },
      { type: "token", text: "这所学校还没有收录，我不能凭印象回答。" },
    ]),
  );
  assert.equal(turn.refused, true);
  assert.deepEqual(turn.blocks.map((b) => b.type), ["text"]);
});

test("the sources the gate let through are kept as the server sent them", () => {
  const citation = { n: 1, programId: "p1", program: "甲大学 数据科学硕士", title: "MSc", url: "https://example.edu/msc", status: "待核验" as const, quotes: ["Tuition fee: US$61,000 per year."] };
  const turn = play(newTurn("t1", "q"), [{ type: "citations", gate: "pass", citations: [citation] }]);
  assert.deepEqual(turn.blocks, [{ type: "citations", gate: "pass", citations: [citation] }]);
  assert.equal(turn.refused, false);
});

test("a proposed change leaves the turn waiting, with what it will change", () => {
  const turn = finishTurn(play(newTurn("t1", "加入"), PROPOSAL));
  assert.equal(turn.state, "waiting");
  assert.equal(hasPending(turn), true);
  const [card] = confirms(turn);
  assert.equal(card.state, "pending");
  assert.deepEqual(card.changes, [{ label: "选校组合", before: "不在组合里", after: "加入" }]);
  assert.equal(steps(turn)[0].status, "waiting");
});

test("confirming continues the same turn: the proposal is confirmed, then written in its own step", () => {
  const waiting = finishTurn(play(newTurn("t1", "加入"), PROPOSAL));
  const held = beginAnswer(waiting, "int-1", true);
  assert.equal(held.state, "running");
  assert.equal(confirms(held)[0].answer, true);
  assert.equal(confirms(held)[0].state, "pending");
  const turn = finishTurn(
    play(held, [
      { type: "step", id: "call-2:write", status: "running", kind: "tool", name: "propose_portfolio_change", title: "写入", write: true },
      { type: "step", id: "call-2", status: "done", result: "你已确认" },
      { type: "step", id: "call-2:write", status: "done", ms: 40, result: "已保存", write: true },
      { type: "token", text: "已经加进去了。" },
    ]),
  );
  assert.equal(turn.state, "done");
  assert.equal(confirms(turn)[0].state, "approved");
  assert.deepEqual(turn.blocks.map((b) => b.type), ["step", "confirm", "step", "text"]);
  // The proposal keeps the time it took; the confirm stream does not send one for it.
  assert.equal(steps(turn)[0].ms, 30);
  assert.equal(steps(turn)[0].result, "你已确认");
  assert.equal(steps(turn)[1].title, "写入");
});

test("declining closes the proposal and nothing is written", () => {
  const held = beginAnswer(finishTurn(play(newTurn("t1", "加入"), PROPOSAL)), "int-1", false);
  const turn = finishTurn(play(held, [{ type: "step", id: "call-2", status: "declined", result: "已取消，没有改动" }, { type: "token", text: "好的，没有改。" }]));
  assert.equal(confirms(turn)[0].state, "declined");
  assert.equal(steps(turn).length, 1);
  assert.equal(steps(turn)[0].status, "declined");
});

test("an answer the server refused before running leaves the change waiting", () => {
  const held = beginAnswer(finishTurn(play(newTurn("t1", "加入"), PROPOSAL)), "int-1", true);
  const turn = finishTurn(play(held, [{ type: "error", code: "rate_limited", message: "发送太频繁了，请 12 秒后再试。" }]));
  assert.equal(turn.state, "waiting");
  assert.equal(confirms(turn)[0].state, "pending");
  assert.equal(confirms(turn)[0].answer, undefined);
  // Trying again drops the old error rather than stacking a second one under it.
  assert.equal(beginAnswer(turn, "int-1", true).blocks.some((b) => b.type === "error"), false);
});

test("a change the server no longer has is gone, not confirmed", () => {
  const held = beginAnswer(finishTurn(play(newTurn("t1", "加入"), PROPOSAL)), "int-1", true);
  const turn = finishTurn(play(held, [{ type: "error", code: "nothing_pending", message: "没有待确认的操作，可能已经处理过或已过期。" }]));
  assert.equal(confirms(turn)[0].state, "gone");
  assert.equal(turn.state, "failed");
});

test("a confirm from a thread without step ids settles by the answer that was sent", () => {
  const old = finishTurn(play(newTurn("t1", "加入"), [{ type: "confirm", id: "int-9", summary: "把「甲大学 数据科学硕士」加入选校组合" }]));
  const turn = finishTurn(play(beginAnswer(old, "int-9", true), [{ type: "token", text: "好了。" }]));
  assert.equal(confirms(turn)[0].state, "approved");
});

test("writing a new message voids a change nobody answered", () => {
  const turn = voidPending(finishTurn(play(newTurn("t1", "加入"), PROPOSAL)));
  assert.equal(confirms(turn)[0].state, "void");
  assert.equal(steps(turn)[0].status, "stopped");
  assert.equal(turn.state, "done");
  const untouched = finishTurn(play(newTurn("t2", "q"), SEARCH));
  assert.equal(voidPending(untouched), untouched);
});

test("stopping marks what was running and says only what is known", () => {
  const reading = stopTurn(play(newTurn("t1", "q"), SEARCH.slice(0, 1)));
  assert.equal(reading.state, "stopped");
  assert.equal(steps(reading)[0].status, "stopped");
  assert.equal(reading.note, "已停止。停下之前没有写入任何改动。");

  const midTool = stopTurn(play(newTurn("t1", "q"), SEARCH.slice(0, 4)));
  assert.equal(midTool.note, "已停止。「搜索项目」当时还没返回，结果没有显示出来。");

  const afterWrite = stopTurn(
    play(newTurn("t1", "q"), [
      { type: "step", id: "c1", status: "running", kind: "tool", name: "update_my_profile", write: true },
      { type: "step", id: "c1", status: "done", ms: 9, result: "已保存 1 项", write: true },
      { type: "token", text: "记下了，" },
    ]),
  );
  assert.equal(afterWrite.note, "已停止。停下之前保存的改动还在。");
  assert.equal(answerText(afterWrite), "记下了，");
});

test("a turn the server stopped is shown as stopped, not as finished", () => {
  const turn = finishTurn(
    play(newTurn("t1", "q"), [
      ...SEARCH.slice(0, 4),
      { type: "step", id: "call-1", status: "stopped", ms: 900, result: "已停止，没有执行" },
      { type: "stopped", wrote: false },
    ]),
  );
  assert.equal(turn.state, "stopped");
  assert.equal(steps(turn)[1].status, "stopped");
  assert.ok(turn.note?.includes("别处"));
});

test("a dropped connection fails the turn and the step that was running", () => {
  const turn = failTurn(play(newTurn("t1", "q"), SEARCH.slice(0, 4)), "网络错误，请稍后再试。");
  assert.equal(turn.state, "failed");
  assert.equal(steps(turn)[1].status, "failed");
  assert.deepEqual(turn.blocks.at(-1), { type: "error", code: "network", message: "网络错误，请稍后再试。" });
});

test("a step the server opened but never closed does not spin for ever", () => {
  const turn = finishTurn(play(newTurn("t1", "q"), [...SEARCH.slice(0, 4), { type: "error", code: "advisor_failed", message: "顾问暂时出错了，请稍后再试。" }]));
  assert.equal(steps(turn)[1].status, "failed");
  assert.equal(turn.state, "failed");
});

test("durations read as a person would say them", () => {
  assert.equal(formatDuration(412), "0.4s");
  assert.equal(formatDuration(9949), "9.9s");
  assert.equal(formatDuration(12_400), "12s");
  assert.equal(formatDuration(65_000), "1m 05s");
});

function record(id: string, school: string, name: string, deadline: string | null, status = "applying"): ApplicationRecord {
  return {
    id, programId: null, school, name, round: null, status, deadline, sourceUrl: null, checkedAt: null,
    deadlineOrigin: null, materialsReady: false, materialNotes: "", version: "1",
  };
}

test("starter questions name the applicant's own applications and nothing else", () => {
  const overview = overviewOf(
    [record("a", "甲大学", "数据科学硕士", null), record("b", "乙大学", "MSc Computing", "2027-01-15"), record("c", "丙大学", "MSc AI", "2027-03-01", "submitted")],
    "2026-11-20",
  );
  assert.deepEqual(starterQuestions(overview), [
    "甲大学 数据科学硕士 的申请截止日期是哪天？",
    "乙大学 MSc Computing 的语言和均分要求是什么？",
    "按截止日期排一下我的申请，接下来先做哪个？",
  ]);
  const one = overviewOf([record("b", "乙大学", "MSc Computing", "2027-01-15")], "2026-11-20");
  assert.deepEqual(starterQuestions(one), ["乙大学 MSc Computing 的语言和均分要求是什么？", "我这个申请接下来该准备什么？"]);
});

test("without applications the starter questions name none", () => {
  for (const overview of [null, overviewOf([], "2026-11-20"), overviewOf([record("c", "丙大学", "MSc AI", null, "submitted")], "2026-11-20")]) {
    const questions = starterQuestions(overview);
    assert.equal(questions.length, 2);
    assert.ok(questions.every((q) => !/大学|MSc/.test(q)));
  }
});

test("a conversation comes back after a reload, for the account it belongs to only", () => {
  const done = finishTurn(play(newTurn("t1", "有哪些项目"), SEARCH));
  const raw = serialize("me@example.com", "conv_1", [done]);
  assert.deepEqual(restore(raw, "me@example.com"), { conversationId: "conv_1", turns: [done] });
  assert.equal(restore(raw, "other@example.com"), null);
  assert.equal(restore(raw, ""), null);
  assert.equal(restore(null, "me@example.com"), null);
  assert.equal(restore("{not json", "me@example.com"), null);
  assert.equal(restore(JSON.stringify({ v: 1, owner: "", conversationId: "bad id!", turns: [] }), ""), null);
});

test("a turn cut off by the reload says so, and a change that was waiting still waits", () => {
  const running = play(newTurn("t1", "q"), SEARCH.slice(0, 4));
  const back = restore(serialize("", "c1", [running]), "")!.turns[0];
  assert.equal(back.state, "lost");
  assert.equal(steps(back)[1].status, "stopped");
  assert.ok(back.note?.includes("刷新"));

  const answering = beginAnswer(finishTurn(play(newTurn("t2", "加入"), PROPOSAL)), "int-1", true);
  const waiting = restore(serialize("", "c1", [answering]), "")!.turns[0];
  assert.equal(waiting.state, "waiting");
  assert.equal(confirms(waiting)[0].state, "pending");
  assert.equal(confirms(waiting)[0].answer, undefined);
});

test("only the latest turns are kept in the browser", () => {
  const turns = Array.from({ length: 40 }, (_, i) => finishTurn(newTurn(`t${i}`, `q${i}`)));
  const back = restore(serialize("", "c1", turns), "")!;
  assert.equal(back.turns.length, 30);
  assert.equal(back.turns[0].id, "t10");
});
