import assert from "node:assert/strict";
import { test } from "node:test";

import { timelineOf } from "./roadmap-timeline.ts";
import type { Roadmap, RoadmapPhase } from "./types.ts";

const task = (id: string, done: boolean) => ({
  materialId: id, label: id, detail: "", done, scheduleOrigin: "suggested" as const, dueAt: null,
  deadlineSourceUrl: null,
});
const phase = (id: string, suggestedAt: string | null, done: boolean[]): RoadmapPhase => ({
  id, title: id, detail: "", suggestedAt, status: "pending", tasks: done.map((d, i) => task(`${id}-${i}`, d)),
});
const roadmap = (phases: RoadmapPhase[], anchorAt: string | null = "2027-07-15"): Roadmap => ({
  intake: "2027 S2", anchorAt, generatedAt: "", phases,
});
const TODAY = new Date("2026-10-29T00:00:00Z");

test("the current phase follows the ticks: the earliest phase with an unticked task", () => {
  const model = timelineOf(roadmap([
    phase("first", "2026-08-19", [true, true]),
    phase("second", "2026-10-18", [true, false]),
    phase("third", "2026-11-17", [false]),
  ]), TODAY);
  assert.deepEqual(model.phases.map((p) => p.current), [false, true, false]);
  assert.equal(model.current?.id, "second");
});

test("each phase ends where the next begins, and the last ends at the intake", () => {
  const model = timelineOf(roadmap([phase("a", "2026-08-19", [false]), phase("b", "2026-10-18", [false])]), TODAY);
  assert.deepEqual(model.phases.map((p) => [p.start, p.end]), [["2026-08-19", "2026-10-18"], ["2026-10-18", "2027-07-15"]]);
});

test("a phase whose end has passed with a task left is overdue; a finished one is not", () => {
  const model = timelineOf(roadmap([
    phase("late", "2026-06-01", [true, false]),
    phase("finished", "2026-07-01", [true]),
    phase("now", "2026-08-01", [false]),
    phase("later", "2026-12-01", [false]),
  ]), TODAY);
  assert.deepEqual(model.phases.map((p) => p.overdue), [true, false, false, false]);
  assert.deepEqual(model.phases.map((p) => p.complete), [false, true, false, false]);
});

test("without an intake nothing is dated, so nothing is overdue", () => {
  const model = timelineOf(roadmap([phase("a", null, [false]), phase("b", null, [false])], null), TODAY);
  assert.equal(model.dated, false);
  assert.deepEqual(model.phases.map((p) => [p.start, p.end, p.overdue]), [[null, null, false], [null, null, false]]);
  assert.equal(model.current?.id, "a");
});

test("every task ticked means there is no current phase", () => {
  assert.equal(timelineOf(roadmap([phase("a", "2026-08-19", [true])]), TODAY).current, null);
});
