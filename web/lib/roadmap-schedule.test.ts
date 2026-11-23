import assert from "node:assert/strict";
import { test } from "node:test";

import type { ApplicationRecord } from "./application-records.ts";
import { beijingToday } from "./deadlines.ts";
import { overviewOf } from "./overview.ts";
import { MIN_DAYS_PER_STEP, scheduleBound, schedulePhases, type PlannedPhase, type ScheduleBound } from "./roadmap-schedule.ts";

const INTAKE = "2027-07-15";
const SUBMISSION = 4;

/** The seven served phases back-planned from a July 2027 intake, as [start, end, steps]. */
const WINDOWS: [string, string, number][] = [
  ["2026-08-19", "2026-10-18", 5], // selection
  ["2026-10-18", "2026-11-17", 5], // academic
  ["2026-11-17", "2026-12-17", 4], // language
  ["2026-12-17", "2027-02-15", 4], // specialized
  ["2027-02-15", "2027-05-16", 5], // submission
  ["2027-05-16", "2027-06-15", 6], // decision
  ["2027-06-15", "2027-07-15", 2], // visa
];

/** The plan with `open[i]` steps still open in phase i (all open when left out). */
function plan(open: (number | undefined)[] = []): PlannedPhase[] {
  return WINDOWS.map(([start, end, total], index) => ({ start, end, total, open: open[index] ?? total }));
}

const days = (from: string, to: string) => Math.round((Date.parse(to) - Date.parse(from)) / 86_400_000);
const windows = (schedule: ReturnType<typeof schedulePhases>) => schedule.phases.map((phase) => [phase.start, phase.end]);

function assertContinuous(schedule: ReturnType<typeof schedulePhases>, from = 1) {
  for (let i = from; i < schedule.phases.length; i++) {
    assert.equal(schedule.phases[i].start, schedule.phases[i - 1].end, `phase ${i} starts where ${i - 1} ends`);
  }
}

test("with no unfinished phase past its window the plan is shown as it is", () => {
  const schedule = schedulePhases(plan([0, 0]), INTAKE, "2026-11-23", null, SUBMISSION);
  assert.deepEqual(windows(schedule), WINDOWS.map(([start, end]) => [start, end]));
  assert.equal(schedule.moved, false);
  assert.deepEqual(schedule.tight, []);
  assert.ok(schedule.phases.every((phase) => !phase.moved && !phase.tight));
});

test("two late phases are laid out again from today, in order, and squeezed into the plan's end of applying", () => {
  // The owner's state: nothing ticked in 锁定申请组合 or 学术与身份材料, today 23 November.
  const schedule = schedulePhases(plan(), INTAKE, "2026-11-23", null, SUBMISSION);
  assert.equal(schedule.moved, true);
  assert.equal(schedule.phases[0].start, "2026-11-23");
  // Everything before applying now fits between today and 16 May, in proportion to the plan's days.
  assert.equal(schedule.phases[SUBMISSION].end, "2027-05-16");
  const room = days("2026-11-23", "2027-05-16");
  const lengths = schedule.phases.slice(0, 5).map((phase) => days(phase.start, phase.end));
  const asked = [60, 30, 30, 60, 90];
  lengths.forEach((length, index) => assert.ok(Math.abs(length - (asked[index] * room) / 270) <= 1, `${index}: ${length}`));
  assertContinuous(schedule);
  // 174 days for what the plan gave 270 is more than half: not tight.
  assert.deepEqual(schedule.tight, []);
  // The phases after applying keep the plan.
  assert.deepEqual(windows(schedule).slice(5), [["2027-05-16", "2027-06-15"], ["2027-06-15", "2027-07-15"]]);
  assert.deepEqual(schedule.phases.map((phase) => phase.moved), [true, true, true, true, true, false, false]);
});

test("one late phase moves the next one along only as far as it overlaps; the rest keep the plan", () => {
  // 学术与身份材料 has one step open (6 of the plan's 30 days); 语言准备 has one of four (7.5 days).
  const schedule = schedulePhases(plan([0, 1, 1]), INTAKE, "2026-11-23", null, SUBMISSION);
  assert.deepEqual(windows(schedule).slice(0, 4), [
    ["2026-08-19", "2026-10-18"],
    ["2026-11-23", "2026-11-29"],
    // It now starts after the late phase and keeps the slack up to the next phase's planned start.
    ["2026-11-29", "2026-12-17"],
    ["2026-12-17", "2027-02-15"],
  ]);
  assert.deepEqual(schedule.phases.map((phase) => phase.moved), [false, true, true, false, false, false, false]);
  // A finished phase keeps its window; between it and the moved one is the gap to today.
  assertContinuous(schedule, 2);
  assert.deepEqual(schedule.tight, []);
});

test("a finished phase between late ones takes no time", () => {
  const schedule = schedulePhases(plan([2, 0, 1]), INTAKE, "2026-11-23", null, SUBMISSION);
  const [selection, academic, language] = schedule.phases;
  assert.equal(selection.start, "2026-11-23");
  assert.equal(academic.start, academic.end);
  assert.equal(academic.moved, false);
  assert.equal(language.start, academic.end);
  assertContinuous(schedule);
});

test("an early deadline is the bound before applying: too little time is tight, and the follow-up starts after it", () => {
  const bound: ScheduleBound = { date: "2027-01-15", school: "爱丁堡大学", checked: false };
  const schedule = schedulePhases(plan(), INTAKE, "2026-11-23", bound, SUBMISSION);
  assert.equal(schedule.phases[0].start, "2026-11-23");
  assert.equal(schedule.phases[SUBMISSION].end, "2027-01-15");
  assertContinuous(schedule);
  assert.equal(schedule.tight.length, 1);
  const [tight] = schedule.tight;
  assert.deepEqual(
    { group: tight.group, basis: tight.basis, from: tight.from, until: tight.until, days: tight.days, open: tight.open, planned: tight.planned, phases: tight.phases },
    { group: "apply", basis: "deadline", from: "2026-11-23", until: "2027-01-15", days: 53, open: 23, planned: 270, phases: [0, 1, 2, 3, 4] },
  );
  assert.equal(tight.bound, bound);
  assert.deepEqual(schedule.phases.map((phase) => phase.tight), [true, true, true, true, true, false, false]);
  // Nothing before applying runs past the deadline: the follow-up phase starts there instead of in May.
  assert.deepEqual(windows(schedule).slice(5), [["2027-01-15", "2027-06-15"], ["2027-06-15", "2027-07-15"]]);
  assert.equal(schedule.phases[5].moved, true);
});

test("a deadline after the plan's end of applying does not stretch anything", () => {
  const schedule = schedulePhases(plan([0, 1, 1]), INTAKE, "2026-11-23", { date: "2027-06-01", school: "x", checked: true }, SUBMISSION);
  assert.deepEqual(windows(schedule), windows(schedulePhases(plan([0, 1, 1]), INTAKE, "2026-11-23", null, SUBMISSION)));
});

test("a deadline after the plan's end of applying gives applying no more time than the plan, so later phases keep theirs", () => {
  for (const date of ["2027-06-30", "2027-09-01"]) {
    const schedule = schedulePhases(plan(), INTAKE, "2026-11-23", { date, school: "x", checked: true }, SUBMISSION);
    assert.equal(schedule.phases[SUBMISSION].end, "2027-05-16", date);
    assert.deepEqual(windows(schedule).slice(5), [["2027-05-16", "2027-06-15"], ["2027-06-15", "2027-07-15"]], date);
    assert.deepEqual(schedule.tight, [], date);
  }
});

test("once the plan's end of applying has passed, a deadline still ahead is the bound", () => {
  const schedule = schedulePhases(plan([0, 0, 0, 0, 3]), INTAKE, "2027-05-20", { date: "2027-06-10", school: "x", checked: true }, SUBMISSION);
  assert.equal(schedule.phases[SUBMISSION].end, "2027-06-10");
  // 21 days for the 54 the plan gives three open steps of 提交申请: tight, against the deadline.
  assert.deepEqual(schedule.tight.map((tight) => [tight.basis, tight.days, tight.over]), [["deadline", 21, null]]);
});

test("once something is laid out again, a deadline before the plan's end of applying bounds every phase before applying", () => {
  // The plan applies until 16 May; the deadline is 1 March. 98 days for 163.5 planned is not tight.
  const schedule = schedulePhases(plan([0, 1, 1]), INTAKE, "2026-11-23", { date: "2027-03-01", school: "x", checked: true }, SUBMISSION);
  assert.equal(schedule.phases[1].start, "2026-11-23");
  assert.equal(schedule.phases[SUBMISSION].end, "2027-03-01");
  assert.deepEqual(schedule.tight, []);
  assertContinuous(schedule, 2);
});

test("a deadline today leaves no time: every open step keeps a day, so the suggestion runs past it", () => {
  const schedule = schedulePhases(plan(), INTAKE, "2026-11-23", { date: "2026-11-23", school: "x", checked: true }, SUBMISSION);
  const [tight] = schedule.tight;
  assert.deepEqual([tight.days, tight.open], [0, 23]);
  assert.equal(schedule.phases[SUBMISSION].end, "2026-12-16"); // 23 days at one a day
  assert.equal(tight.over, "date");
  assert.equal(MIN_DAYS_PER_STEP, 1);
  assertContinuous(schedule);
});

test("with no deadline and the plan's end of applying already past, the bound is that day and the time is gone", () => {
  // 20 May 2027: applying was planned to end on 16 May; three steps of 提交申请 are open.
  const schedule = schedulePhases(plan([0, 0, 0, 0, 3]), INTAKE, "2027-05-20", null, SUBMISSION);
  const [tight] = schedule.tight;
  assert.deepEqual([tight.group, tight.basis, tight.until, tight.days, tight.open], ["apply", "plan", "2027-05-16", -4, 3]);
  assert.deepEqual([schedule.phases[SUBMISSION].start, schedule.phases[SUBMISSION].end], ["2027-05-20", "2027-05-23"]);
  // The follow-up phase, planned from 16 May, now starts after it, and both later phases fit before the intake.
  assert.deepEqual(windows(schedule).slice(5), [["2027-05-23", "2027-06-19"], ["2027-06-19", "2027-07-15"]]);
  assert.equal(schedule.tight.length, 1);
});

test("the phases after applying are fitted to the intake, and are tight when it is close", () => {
  // 20 June 2027, every step before applying done, the offer phase late with all six steps open.
  const schedule = schedulePhases(plan([0, 0, 0, 0, 0]), INTAKE, "2027-06-20", null, SUBMISSION);
  assert.deepEqual(windows(schedule).slice(5), [["2027-06-20", "2027-07-03"], ["2027-07-03", "2027-07-15"]]);
  const [tight] = schedule.tight;
  assert.deepEqual([tight.group, tight.basis, tight.days, tight.open, tight.planned, tight.phases], ["intake", "intake", 25, 8, 60, [5, 6]]);
  assert.equal(tight.over, null);
  // Never past the intake.
  assert.equal(schedule.phases.at(-1)!.end, INTAKE);
});

test("once the intake has passed nothing is laid out again", () => {
  const schedule = schedulePhases(plan(), "2026-07-15", "2026-11-23", null, SUBMISSION);
  assert.equal(schedule.expired, true);
  assert.equal(schedule.moved, false);
  assert.deepEqual(windows(schedule), WINDOWS.map(([start, end]) => [start, end]));
});

test("without a submission phase every phase is fitted to the intake", () => {
  const schedule = schedulePhases(plan(), INTAKE, "2026-11-23", { date: "2027-01-15", school: "x", checked: true }, -1);
  assert.equal(schedule.phases.at(-1)!.end, INTAKE);
  assert.equal(schedule.tight[0]?.basis ?? null, null);
  assertContinuous(schedule);
});

test("a phase is late from the day its window ends, by the Beijing calendar", () => {
  const onLastDay = schedulePhases(plan([0]), INTAKE, "2026-11-16", null, SUBMISSION);
  assert.equal(onLastDay.moved, false);
  const dayAfter = schedulePhases(plan([0]), INTAKE, "2026-11-17", null, SUBMISSION);
  assert.equal(dayAfter.phases[1].start, "2026-11-17");
  assert.equal(dayAfter.phases[1].moved, true);
  // 16:30 UTC on the 16th is already the 17th in Beijing.
  assert.equal(beijingToday(new Date("2026-11-16T16:30:00Z")), "2026-11-17");
  assert.equal(beijingToday(new Date("2026-11-16T15:59:00Z")), "2026-11-16");
});

function record(id: string, fields: Partial<ApplicationRecord> = {}): ApplicationRecord {
  return {
    id, programId: null, school: `学校 ${id}`, name: "MSc", round: null, status: "applying", deadline: null,
    sourceUrl: null, checkedAt: null, deadlineOrigin: null, materialsReady: false, materialNotes: "",
    materials: [], materialsExtracted: false, customMaterials: [], materialsDone: 0, materialsTotal: 0,
    version: "v1", ...fields,
  };
}

test("the bound is the earliest open deadline from today on, with whether it was checked", () => {
  const rows = overviewOf(
    [
      record("passed", { deadline: "2026-11-01" }),
      record("sent", { status: "submitted", deadline: "2026-12-01" }),
      record("undated"),
      record("later", { deadline: "2027-03-01", checkedAt: "2026-11-02T00:00:00Z" }),
      record("next", { deadline: "2027-01-15" }),
      record("given-up", { status: "withdrawn", deadline: "2026-12-05" }),
    ],
    "2026-11-23",
  ).rows;
  assert.deepEqual(scheduleBound(rows), { date: "2027-01-15", school: "学校 next", checked: false });
  assert.deepEqual(scheduleBound(rows.filter((row) => row.record.id !== "next")), { date: "2027-03-01", school: "学校 later", checked: true });
  assert.equal(scheduleBound(rows.filter((row) => ["passed", "sent", "undated"].includes(row.record.id))), null);
});

test("with fewer days to the intake than open steps, the intake cuts even a day per step short and says so", () => {
  const schedule = schedulePhases(plan(), INTAKE, "2027-07-10", null, SUBMISSION);
  const [apply] = schedule.tight;
  assert.equal(apply.over, "intake");
  assert.equal(schedule.phases[SUBMISSION].end, INTAKE);
  assert.ok(schedule.phases.every((phase) => phase.end <= INTAKE));
});

test("with nothing late, a deadline before the plan's end of applying still bounds every open phase before applying", () => {
  // 锁定申请组合 and 学术与身份材料 are done, so no phase is past its window; the deadline is 15 January.
  // The 180 days the plan gives the 13 open steps do not fit into the 53 days left: tight.
  const bound: ScheduleBound = { date: "2027-01-15", school: "格拉斯哥大学", checked: false };
  const schedule = schedulePhases(plan([0, 0]), INTAKE, "2026-11-23", bound, SUBMISSION);
  assert.equal(schedule.moved, true);
  assert.equal(schedule.phases[2].start, "2026-11-23");
  assert.equal(schedule.phases[SUBMISSION].end, "2027-01-15");
  assertContinuous(schedule, 3);
  assert.equal(schedule.tight.length, 1);
  const [tight] = schedule.tight;
  assert.deepEqual(
    [tight.group, tight.basis, tight.from, tight.until, tight.days, tight.open, tight.planned, tight.phases],
    ["apply", "deadline", "2026-11-23", "2027-01-15", 53, 13, 180, [2, 3, 4]],
  );
  // The finished phases keep their windows; the follow-up starts at the deadline, not in May.
  assert.deepEqual(windows(schedule).slice(0, 2), [["2026-08-19", "2026-10-18"], ["2026-10-18", "2026-11-17"]]);
  assert.equal(schedule.phases[5].start, "2027-01-15");
});

test("ticking the last late step does not make a deadline that still does not fit stop being tight", () => {
  const bound: ScheduleBound = { date: "2026-12-17", school: "格拉斯哥大学", checked: false };
  // One step of 学术与身份材料 open (late), then none.
  const before = schedulePhases(plan([0, 1]), INTAKE, "2026-11-23", bound, SUBMISSION);
  const after = schedulePhases(plan([0, 0]), INTAKE, "2026-11-23", bound, SUBMISSION);
  assert.equal(before.tight.length, 1);
  assert.equal(after.tight.length, 1);
  assert.equal(after.tight[0].basis, "deadline");
  assert.equal(after.phases[SUBMISSION].end, "2026-12-17");
  assert.ok(after.tight[0].days <= before.tight[0].days);
});

test("with nothing late, a deadline before the plan's end of applying that leaves enough time bounds without being tight", () => {
  // 129 days for the 180 planned is more than half.
  const schedule = schedulePhases(plan([0, 0]), INTAKE, "2026-11-23", { date: "2027-04-01", school: "x", checked: true }, SUBMISSION);
  assert.equal(schedule.phases[SUBMISSION].end, "2027-04-01");
  assert.deepEqual(schedule.tight, []);
  assert.ok(schedule.phases.slice(2, 5).every((phase) => phase.moved));
});

test("with nothing late, a deadline after every open phase before applying changes nothing", () => {
  // Only 语言准备 is open and it ends 17 December, before the 1 March deadline; applying is all done.
  const open = schedulePhases(plan([0, 0, 2, 0, 0]), INTAKE, "2026-11-23", { date: "2027-03-01", school: "x", checked: true }, SUBMISSION);
  assert.deepEqual(windows(open), WINDOWS.map(([start, end]) => [start, end]));
  assert.equal(open.moved, false);
  // And a deadline after the plan's end of applying never moves anything.
  const later = schedulePhases(plan([0, 0]), INTAKE, "2026-11-23", { date: "2027-06-01", school: "x", checked: true }, SUBMISSION);
  assert.deepEqual(windows(later), WINDOWS.map(([start, end]) => [start, end]));
  assert.deepEqual(later.tight, []);
});

test("a phase finished early whose window runs past today ends today, so the re-laid phases do not overlap it", () => {
  const bound: ScheduleBound = { date: "2027-01-15", school: "x", checked: true };
  // 语言准备 (17 November to 17 December) is done on 23 November; the deadline cuts into what follows.
  const schedule = schedulePhases(plan([0, 0, 0]), INTAKE, "2026-11-23", bound, SUBMISSION);
  assert.deepEqual(windows(schedule)[2], ["2026-11-17", "2026-11-23"]);
  assert.equal(schedule.phases[3].start, "2026-11-23");
  assertContinuous(schedule, 3);
  // Today 10 November: 学术与身份材料 (18 October to 17 November) is done, the next phase starts today.
  const early = schedulePhases(plan([0, 0]), INTAKE, "2026-11-10", { date: "2026-12-20", school: "x", checked: true }, SUBMISSION);
  assert.deepEqual(windows(early)[1], ["2026-10-18", "2026-11-10"]);
  assert.equal(early.phases[2].start, "2026-11-10");
  assert.equal(early.phases[SUBMISSION].end, "2026-12-20");
});
