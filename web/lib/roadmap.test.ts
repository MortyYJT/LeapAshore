// Characterisation tests for the roadmap builder.
//
// The builder shipped in T3 before any test existed. Every assertion passes an explicit `now` so the
// result is deterministic; the default argument would make these tests depend on the wall clock.

import { test } from "node:test";
import assert from "node:assert/strict";

import { buildRoadmap, intakeAnchor, PHASE_DEFS, roadmapProgress } from "./roadmap.ts";
import type { Profile } from "./types.ts";

const BASE: Profile = {
  educationLevel: "本科",
  schoolOrigin: "国内",
  schoolName: "北京邮电大学",
  domesticTier: "211",
  overseasBand: null,
  major: "软件工程",
  gpaScore: 82,
  gpaScale: 100,
  targetDegree: "授课型硕士",
  targetField: "计算机与数据",
  englishScore: "IELTS 6.5",
  annualBudgetCny: 300000,
  intake: "2027 S1",
};

const NOW = new Date("2026-10-05T00:00:00Z");
const build = (overrides: Partial<Profile> = {}, done: string[] = [], now = NOW) =>
  buildRoadmap({ ...BASE, ...overrides }, done, now);

test("parses the two Australian intake terms", () => {
  assert.equal(intakeAnchor("2027 S1").toISOString().slice(0, 10), "2027-02-15");
  assert.equal(intakeAnchor("2027 S2").toISOString().slice(0, 10), "2027-07-15");
});

test("falls back to a future term when the intake cannot be parsed", () => {
  const anchor = intakeAnchor("说不清");
  assert.ok(anchor.getTime() > Date.now() - 1000);
  assert.equal(anchor.getUTCMonth(), 1);
  assert.equal(anchor.getUTCDate(), 15);
});

test("produces the six defined phases in order", () => {
  const roadmap = build();
  assert.equal(roadmap.phases.length, 6);
  assert.deepEqual(
    roadmap.phases.map((p) => p.id),
    PHASE_DEFS.map((p) => p.id),
  );
});

test("counts backwards from the intake date", () => {
  const roadmap = build();
  assert.equal(roadmap.anchorAt, "2027-02-15");
  assert.equal(roadmap.phases[0].suggestedAt, "2026-03-22");
  assert.equal(roadmap.phases[5].suggestedAt, "2026-12-17");
});

test("marks phases whose suggested date has passed as overdue", () => {
  const roadmap = build();
  assert.deepEqual(
    roadmap.phases.map((p) => p.status),
    ["overdue", "overdue", "overdue", "overdue", "overdue", "pending"],
  );
});

test("marks every phase pending before the earliest suggested date", () => {
  const roadmap = build({}, [], new Date("2026-01-01T00:00:00Z"));
  assert.ok(roadmap.phases.every((p) => p.status === "pending"));
});

test("marks every phase overdue once the intake date has passed", () => {
  const roadmap = build({}, [], new Date("2027-03-01T00:00:00Z"));
  assert.ok(roadmap.phases.every((p) => p.status === "overdue"));
});

test("ships every date as a system suggestion, never as an official deadline", () => {
  const tasks = build().phases.flatMap((p) => p.tasks);
  assert.ok(tasks.length > 0);
  for (const task of tasks) {
    assert.equal(task.scheduleOrigin, "suggested");
  }
});

// The honesty rule from AGENTS.md: the official deadline is left empty and rendered as pending
// verification rather than filled with an invented date.
test("leaves official deadlines empty", () => {
  const tasks = build().phases.flatMap((p) => p.tasks);
  for (const task of tasks) {
    assert.equal(task.deadlineSourceUrl, null);
  }
});

test("promotes a phase to completed only when every material is ticked", () => {
  const roadmap = build();
  const selection = roadmap.phases[0];
  const allIds = selection.tasks.map((t) => t.materialId);

  const partial = build({}, allIds.slice(0, 1));
  assert.equal(partial.phases[0].status, "in_progress");

  const done = build({}, allIds);
  assert.equal(done.phases[0].status, "completed");
  assert.equal(roadmapProgress(done).done, allIds.length);
});

test("counts 29 materials for the taught-master default", () => {
  const roadmap = build();
  assert.equal(roadmapProgress(roadmap).total, 29);
  assert.equal(roadmapProgress(roadmap).done, 0);
});

test("adds a research proposal and supervisor step for a research degree", () => {
  const ids = build({ targetDegree: "研究型硕士" })
    .phases.find((p) => p.id === "specialized")!
    .tasks.map((t) => t.materialId);
  assert.ok(ids.includes("spe-research"));
  assert.ok(!ids.includes("spe-portfolio"));
});

test("adds a portfolio for design and arts fields", () => {
  const ids = build({ targetField: "传媒艺术与音乐" })
    .phases.find((p) => p.id === "specialized")!
    .tasks.map((t) => t.materialId);
  assert.ok(ids.includes("spe-portfolio"));
  assert.ok(!ids.includes("spe-research"));
});

test("carries the intake term onto the roadmap", () => {
  assert.equal(build({ intake: "2028 S2" }).intake, "2028 S2");
  assert.equal(build({ intake: "2028 S2" }).anchorAt, "2028-07-15");
});
