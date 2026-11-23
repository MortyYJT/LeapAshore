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
  const model = timelineOf(roadmap([phase("a", "2026-08-19", [true]), phase("b", "2026-10-18", [false])]), TODAY);
  assert.deepEqual(model.phases.map((p) => [p.start, p.end]), [["2026-08-19", "2026-10-18"], ["2026-10-18", "2027-07-15"]]);
  assert.deepEqual(model.phases.map((p) => p.planned), [{ start: "2026-08-19", end: "2026-10-18" }, { start: "2026-10-18", end: "2027-07-15" }]);
});

test("a phase whose window has passed with a task left is laid out again from today, and what follows moves along with it", () => {
  const model = timelineOf(roadmap([
    phase("late", "2026-06-01", [true, false]),
    phase("finished", "2026-07-01", [true]),
    phase("now", "2026-08-01", [false]),
    phase("later", "2026-12-01", [false]),
  ]), TODAY);
  // The finished phase after it takes no time; the later ones are fitted between it and the intake.
  assert.deepEqual(model.phases.map((p) => p.moved), [true, false, true, true]);
  assert.equal(model.phases[1].start, model.phases[1].end);
  assert.equal(model.phases.at(-1)!.end, "2027-07-15");
  assert.deepEqual(model.phases.map((p) => p.complete), [false, true, false, false]);
  assert.equal(model.moved, true);
  assert.equal(model.phases[0].start, "2026-10-29");
  assert.deepEqual(model.phases[0].planned, { start: "2026-06-01", end: "2026-07-01" });
  assert.deepEqual(model.tight, []);
});

test("the earliest open deadline bounds the phases before applying once they are laid out again", () => {
  const plan = roadmap([phase("selection", "2026-08-19", [false]), phase("submission", "2026-10-18", [false]), phase("decision", "2027-05-16", [false])]);
  const model = timelineOf(plan, TODAY, { date: "2026-11-08", school: "x", checked: false });
  assert.equal(model.phases[1].end, "2026-11-08");
  assert.equal(model.tight[0].basis, "deadline");
  assert.deepEqual(model.phases.map((p) => p.tight), [true, true, false]);
});

test("without an intake nothing is dated, so nothing is laid out again", () => {
  const model = timelineOf(roadmap([phase("a", null, [false]), phase("b", null, [false])], null), TODAY);
  assert.equal(model.dated, false);
  assert.deepEqual(model.phases.map((p) => [p.start, p.end, p.moved]), [[null, null, false], [null, null, false]]);
  assert.equal(model.current?.id, "a");
});

test("every task ticked means there is no current phase", () => {
  assert.equal(timelineOf(roadmap([phase("a", "2026-08-19", [true])]), TODAY).current, null);
});
