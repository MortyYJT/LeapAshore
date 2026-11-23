import assert from "node:assert/strict";
import { test } from "node:test";

import type { ApplicationRecord } from "./application-records.ts";
import { overviewOf } from "./overview.ts";
import { TALL_CLEAR, TALL_LABEL_PITCH, TALL_MIN_STRETCH, headline, laneWhen, layoutTall, roadmapMap, stretchLabel, stretchWhen, tightWords, windowWords } from "./roadmap-map.ts";
import { timelineOf } from "./roadmap-timeline.ts";
import type { Roadmap, RoadmapPhase } from "./types.ts";

const TODAY = "2026-11-21";
const NOW = new Date(`${TODAY}T00:00:00Z`);

const task = (id: string, done: boolean) => ({
  materialId: id, label: `task ${id}`, detail: "", done, scheduleOrigin: "suggested" as const, dueAt: null,
  deadlineSourceUrl: null,
});
const phase = (id: string, suggestedAt: string | null, done: boolean[]): RoadmapPhase => ({
  id, title: id, detail: "", suggestedAt, status: "pending", tasks: done.map((d, i) => task(`${id}-${i}`, d)),
});
const roadmap = (phases: RoadmapPhase[], anchorAt: string | null = "2027-07-15"): Roadmap => ({
  intake: anchorAt ? "2027 S2" : "", anchorAt, generatedAt: "", phases,
});

function record(id: string, fields: Partial<ApplicationRecord> = {}): ApplicationRecord {
  return {
    id, programId: null, school: `学校 ${id}`, name: "MSc", round: null, status: "applying", deadline: null,
    sourceUrl: null, checkedAt: null, deadlineOrigin: null, materialsReady: false, materialNotes: "",
    materials: [], materialsExtracted: false, customMaterials: [], materialsDone: 0, materialsTotal: 0,
    version: "v1", ...fields,
  };
}

/** The seven served phases for a July 2027 intake, on time: the first two ticked, the third begun. */
const SEVEN = roadmap([
  phase("selection", "2026-08-19", [true, true, true, true, true]),
  phase("academic", "2026-10-18", [true, true, true, true, true]),
  phase("language", "2026-11-17", [true, false, false, false]),
  phase("specialized", "2026-12-17", [false, false, false, false]),
  phase("submission", "2027-02-15", [false, false, false, false, false]),
  phase("decision", "2027-05-16", [false, false, false, false, false, false]),
  phase("visa", "2027-06-15", [false, false]),
]);

function mapOf(plan: Roadmap, records: ApplicationRecord[] = [], today = TODAY) {
  return roadmapMap(timelineOf(plan, new Date(`${today}T00:00:00Z`)), overviewOf(records, today).rows, today);
}

const near = (actual: number, expected: number) => assert.ok(Math.abs(actual - expected) < 1e-9, `${actual} is not ${expected}`);

test("the axis runs from the first phase's start to the intake, and today is on it", () => {
  const map = mapOf(SEVEN);
  assert.equal(map.dated, true);
  assert.equal(map.span, 330);
  near(map.today!, 94 / 330);
  near(map.soonEnd!, (94 + 14) / 330);
  assert.equal(map.stretches[0].start, 0);
  assert.equal(map.stretches.at(-1)!.end, 1);
});

test("the stretches tile the axis in order: each starts where the one before ends", () => {
  const { stretches } = mapOf(SEVEN);
  for (let i = 1; i < stretches.length; i++) near(stretches[i].start, stretches[i - 1].end);
  near(stretches[1].start, 60 / 330);
  near(stretches[1].end, 90 / 330);
});

test("a phase's tasks are stations spaced evenly inside its stretch, in the phase's order", () => {
  const stretch = mapOf(SEVEN).stretches[2];
  assert.deepEqual(stretch.stations.map((station) => station.id), ["language-0", "language-1", "language-2", "language-3"]);
  const width = stretch.end - stretch.start;
  stretch.stations.forEach((station, index) => near(station.position, stretch.start + (width * (index + 0.5)) / 4));
  assert.deepEqual(mapOf(SEVEN).stretches[2].stations.map((station) => station.done), [true, false, false, false]);
});

test("a stretch is complete when every task is ticked, and open otherwise", () => {
  assert.deepEqual(mapOf(SEVEN).stretches.map((stretch) => stretch.state), ["complete", "complete", "open", "open", "open", "open", "open"]);
  assert.ok(mapOf(SEVEN).stretches.every((stretch) => stretch.lead === null));
});

test("a stretch's name trails its end while there is room, leads its start after that, and goes above (the first) or below (any other) when neither side has room", () => {
  assert.deepEqual(mapOf(SEVEN).stretches.map((stretch) => stretch.label), ["after", "after", "after", "after", "before", "before", "before"]);
  const long = mapOf(roadmap([phase("a", "2026-08-19", [false]), phase("b", "2026-09-19", [false])]));
  assert.deepEqual(long.stretches.map((stretch) => stretch.label), ["after", "below"]);
  // Only the first goes above: there it has the row to itself.
  const first = mapOf(roadmap([phase("a", "2026-08-19", [false]), phase("b", "2027-06-19", [false])]));
  assert.deepEqual(first.stretches.map((stretch) => stretch.label), ["above", "before"]);
});

test("a short window crowded with tasks puts its first two stations on the drop into it", () => {
  // Six tasks in thirty of 330 days; five in thirty is not crowded, and the first stretch has no drop.
  assert.deepEqual(mapOf(SEVEN).stretches.map((stretch) => stretch.onDrop), [0, 0, 0, 0, 0, 2, 0]);
  const first = mapOf(roadmap([phase("a", "2026-08-19", [false, false, false, false, false, false]), phase("b", "2026-08-29", [false])]));
  assert.equal(first.stretches[0].onDrop, 0);
  const undated = mapOf(roadmap([phase("a", null, [false]), phase("b", null, [false, false, false, false, false, false])], null));
  assert.deepEqual(undated.stretches.map((stretch) => stretch.onDrop), [0, 0]);
});

test("the axis starts today when the first phase is still ahead", () => {
  const map = mapOf(roadmap([phase("a", "2027-01-01", [false]), phase("b", "2027-03-01", [false])]));
  assert.equal(map.today, 0);
  near(map.stretches[0].start, 41 / map.span);
  assert.equal(map.span, 236);
});

test("the axis ends today when the intake has passed, so today stays on it", () => {
  const map = mapOf(roadmap([phase("a", "2026-01-01", [false])], "2026-07-15"));
  assert.equal(map.today, 1);
  assert.equal(map.todayLabel, "before");
  assert.ok(map.stretches[0].end < 1);
});

test("an application with a date ahead is a lane to a terminus on that date, nearest first", () => {
  const map = mapOf(SEVEN, [record("b", { deadline: "2027-01-31" }), record("a", { deadline: "2026-12-01" })]);
  assert.deepEqual(map.lanes.map((lane) => [lane.row.record.id, lane.kind]), [["a", "ahead"], ["b", "ahead"]]);
  near(map.lanes[0].end, (94 + 10) / 330);
  near(map.lanes[1].end, (94 + 71) / 330);
  assert.deepEqual(map.listed, []);
});

test("a deadline today is still a lane, ending on today's line", () => {
  const map = mapOf(SEVEN, [record("a", { deadline: TODAY })]);
  near(map.lanes[0].end, map.today!);
  assert.equal(map.lanes[0].kind, "ahead");
});

test("a date past the intake runs off the axis and has no terminus", () => {
  const map = mapOf(SEVEN, [record("a", { deadline: "2027-09-01" })]);
  assert.deepEqual([map.lanes[0].kind, map.lanes[0].end, map.lanes[0].label], ["beyond", 1, "over"]);
});

test("an application without a date is a dotted run after the dated ones, with no position claimed", () => {
  const map = mapOf(SEVEN, [record("a"), record("b", { deadline: "2027-03-22" })]);
  assert.deepEqual(map.lanes.map((lane) => [lane.row.record.id, lane.kind]), [["b", "ahead"], ["a", "unknown"]]);
  assert.ok(map.lanes[1].end > map.today! && map.lanes[1].end <= 1);
  assert.equal(laneWhen(map.lanes[1], TODAY), "待确认");
  assert.equal(laneWhen(map.lanes[0], TODAY), "03/22");
});

test("a date that has passed is listed, never drawn as a milestone ahead", () => {
  const map = mapOf(SEVEN, [record("a", { deadline: "2026-11-01" }), record("b", { deadline: "2026-12-01" })]);
  assert.deepEqual(map.lanes.map((lane) => lane.row.record.id), ["b"]);
  assert.deepEqual(map.listed.map((row) => row.record.id), ["a"]);
});

test("a submitted application keeps its lane while its date is ahead and is only listed without one", () => {
  const map = mapOf(SEVEN, [record("a", { status: "submitted", deadline: "2027-01-06" }), record("b", { status: "submitted" })]);
  assert.deepEqual(map.lanes.map((lane) => [lane.row.record.id, lane.row.sent]), [["a", true]]);
  assert.deepEqual(map.listed.map((row) => row.record.id), ["b"]);
});

test("applications with a result or given up are not on the map at all", () => {
  const map = mapOf(SEVEN, [record("a", { status: "admitted", deadline: "2027-01-06" })]);
  assert.equal(map.lanes.length + map.listed.length, 0);
});

test("a lane's label goes after its end when there is room, else over the line, else before today's bar", () => {
  const map = mapOf(SEVEN, [record("a", { deadline: "2026-12-01" }), record("b", { deadline: "2027-06-30" })]);
  assert.deepEqual(map.lanes.map((lane) => lane.label), ["after", "over"]);
  // Late in the axis a short line has room on neither: the label goes before today's bar.
  const late = mapOf(SEVEN, [record("c", { deadline: "2027-06-30" })], "2027-06-01");
  assert.equal(late.lanes[0].label, "before");
});

test("month starts are ticked; a label that would sit on today's is left out; January carries its year", () => {
  const map = mapOf(SEVEN);
  assert.deepEqual(map.ticks.map((tick) => tick.date).slice(0, 3), ["2026-09-01", "2026-10-01", "2026-11-01"]);
  assert.equal(map.ticks.length, 11);
  const labels = Object.fromEntries(map.ticks.map((tick) => [tick.date, tick.label]));
  assert.equal(labels["2026-10-01"], "10 月");
  // 1 December is ten days after today: today's label is there.
  assert.equal(labels["2026-12-01"], null);
  assert.equal(labels["2027-01-01"], "27 年 1 月");
  for (const tick of map.ticks) near(tick.position, (Date.parse(tick.date) - Date.parse("2026-08-19")) / 86400000 / 330);
});

test("without an intake there is no axis: no today, no ticks, no lanes, and every application is listed", () => {
  const plan = roadmap([phase("a", null, [true, true]), phase("b", null, [false, false, false, false]), phase("c", null, [])], null);
  const map = mapOf(plan, [record("x", { deadline: "2026-12-01" }), record("y")]);
  assert.equal(map.dated, false);
  assert.deepEqual([map.today, map.soonEnd, map.ticks.length, map.lanes.length], [null, null, 0, 0]);
  assert.deepEqual(map.listed.map((row) => row.record.id).sort(), ["x", "y"]);
  // In order, by how many stations each holds; a phase without tasks still has a place, and none is under two slots.
  assert.equal(map.span, 8);
  assert.deepEqual(map.stretches.map((stretch) => [stretch.start, stretch.end]), [[0, 2 / 8], [2 / 8, 6 / 8], [6 / 8, 1]]);
  // Nothing is overdue without dates.
  assert.deepEqual(map.stretches.map((stretch) => stretch.state), ["complete", "open", "open"]);
});

test("the headline names the current stretch with its suggested end", () => {
  assert.equal(headline(timelineOf(SEVEN, NOW)), "现在在「language」，还有 3 项没做，建议 12 月 17 日前做完。");
  const onTime = roadmap([phase("a", "2026-08-19", [true]), phase("b", "2026-11-17", [true, false, false]), phase("c", "2026-12-17", [false])]);
  assert.equal(headline(timelineOf(onTime, NOW)), "现在在「b」，还有 2 项没做，建议 12 月 17 日前做完。");
  const undated = roadmap([phase("a", null, [true]), phase("b", null, [false, false])], null);
  assert.equal(headline(timelineOf(undated, NOW)), "现在在「b」，还有 2 项没做。");
  assert.equal(headline(timelineOf(roadmap([phase("a", "2026-08-19", [true])]), NOW)), "所有步骤都做完了。");
});

test("a stretch reads in words for a reader who cannot see the map", () => {
  const [, , current] = mapOf(SEVEN).stretches;
  assert.equal(stretchLabel(current), "language，建议 11 月 17 日开始，1/4 项做完，当前这一段");
  assert.equal(stretchWhen(current.phase, TODAY), "建议 11/17 起");
  assert.equal(windowWords(current.phase), "建议 11 月 17 日到 12 月 17 日。");
});

// ---------------------------------------------------------------------------------------------------
// Phases laid out again from today (lib/roadmap-schedule.ts)
// ---------------------------------------------------------------------------------------------------

/** The owner's state: nothing ticked in the first two phases, whose windows have passed. */
const LATE = roadmap(SEVEN.phases.map((p, index) => (index < 3 ? { ...p, tasks: p.tasks.map((t) => ({ ...t, done: false })) } : p)));

test("late phases are drawn from today like any open stretch: nothing is overdue, and the axis starts today", () => {
  const timeline = timelineOf(LATE, NOW);
  const map = roadmapMap(timeline, [], TODAY);
  assert.ok(map.stretches.every((stretch) => stretch.state === "open"));
  assert.equal(map.today, 0);
  assert.equal(map.stretches[0].start, 0);
  for (let i = 1; i < map.stretches.length; i++) near(map.stretches[i].start, map.stretches[i - 1].end);
  assert.ok(map.stretches.every((stretch) => stretch.lead === null));
  assert.equal(map.stretches.at(-1)!.end, 1);
  assert.equal(headline(timeline), `现在在「selection」，还有 5 项没做。按今天重新排，建议 ${timeline.phases[0].end!.slice(5, 7).replace(/^0/, "")} 月 ${Number(timeline.phases[0].end!.slice(8))} 日前做完。`);
  assert.equal(stretchWhen(timeline.phases[0], TODAY), "重排后 今天起");
  assert.match(windowWords(timeline.phases[0])!, /^系统按今天重新排的建议：11 月 21 日到 .+（原来建议 8 月 19 日到 10 月 18 日）。$/);
  assert.match(stretchLabel(map.stretches[0]), /，系统按今天重新排过，当前这一段$/);
  assert.deepEqual(timeline.tight, []);
});

test("a late phase after a finished one is reached by a thin lead from the finished one's end to today", () => {
  const plan = roadmap(LATE.phases.map((p, index) => (index === 0 ? SEVEN.phases[0] : p)));
  const map = mapOf(plan);
  const [selection, academic] = map.stretches;
  assert.equal(selection.start, 0);
  near(academic.lead!, selection.end);
  near(academic.start, map.today!);
  assert.ok(map.stretches.slice(2).every((stretch) => stretch.lead === null));
  assert.equal(academic.onDrop, 0);
  // A finished phase moved along by re-laid ones does not offer its new place as a suggestion.
  const early = timelineOf(roadmap(LATE.phases.map((p, index) => (index === 2 ? { ...p, tasks: p.tasks.map((t) => ({ ...t, done: true })) } : p))), NOW);
  assert.equal(stretchWhen(early.phases[2], TODAY), null);
  assert.equal(windowWords(early.phases[2]), "原来建议 11 月 17 日到 12 月 17 日。");
  const tall = layoutTall(map);
  near(tall.stretches[1].lead!, tall.stretches[0].y1);
  near(tall.stretches[1].y0, tall.todayY!);
});

test("with too little time before the earliest deadline the late stretches carry 「时间很紧」 and the words give the numbers", () => {
  const rows = overviewOf([record("e", { school: "爱丁堡大学", deadline: "2027-01-15" })], TODAY).rows;
  const timeline = timelineOf(LATE, NOW, { date: "2027-01-15", school: "爱丁堡大学", checked: false });
  const map = roadmapMap(timeline, rows, TODAY);
  assert.deepEqual(map.stretches.map((stretch) => stretch.phase.tight), [true, true, true, true, true, false, false]);
  assert.equal(timeline.tight.length, 1);
  assert.equal(
    tightWords(timeline.tight[0], timeline, TODAY),
    `离最早的截止日期 1 月 15 日（爱丁堡大学，日期待核对）只剩 55 天，申请前还有 ${timeline.tight[0].open} 项没做，原计划给这些步骤留了 ${timeline.tight[0].planned} 天。`,
  );
  assert.match(stretchLabel(map.stretches[0]), /时间很紧/);
});

test("「时间很紧」 for the phases after applying is measured to the intake", () => {
  const done = roadmap(SEVEN.phases.map((p, index) => (index < 5 ? { ...p, tasks: p.tasks.map((t) => ({ ...t, done: true })) } : p)));
  const timeline = timelineOf(done, new Date("2027-06-20T00:00:00Z"));
  assert.equal(tightWords(timeline.tight[0], timeline, "2027-06-20"), "离入学只有 25 天，「decision」等还有 8 项没做，原计划给这些步骤留了 60 天。");
});

test("once the intake has passed the headline asks for a new one, and nothing is painted late", () => {
  const timeline = timelineOf(roadmap(LATE.phases, "2026-07-15"), NOW);
  assert.equal(timeline.expired, true);
  assert.match(headline(timeline), /入学时间已经过了/);
  assert.ok(mapOf(roadmap(LATE.phases, "2026-07-15")).stretches.every((stretch) => stretch.state === "open"));
});

// ---------------------------------------------------------------------------------------------------
// Top to bottom
// ---------------------------------------------------------------------------------------------------

const TWELVE = [
  ["a", "2026-12-01"], ["b", "2026-12-10"], ["c", "2026-12-15"], ["d", "2027-01-06"], ["e", "2027-01-15"], ["f", "2027-01-15"],
  ["g", "2027-01-15"], ["h", "2027-01-31"], ["i", "2027-02-28"], ["j", "2027-03-22"], ["k", "2027-03-22"], ["l", null],
].map(([id, deadline]) => record(id!, { deadline }));

test("top to bottom, time is linear: one scale for the stretches, the stations and the lanes", () => {
  const map = mapOf(SEVEN, [record("a", { deadline: "2026-12-01" })]);
  const tall = layoutTall(map);
  assert.equal(tall.scale, 2.6);
  const y = (position: number) => tall.stretches[0].y0 + position * map.span * tall.scale;
  near(tall.todayY!, y(map.today!));
  near(tall.endY, y(1));
  near(tall.lanes[0].y1, y(map.lanes[0].end));
  near(tall.lanes[0].y0, tall.todayY!);
  for (const { stretch, y0, y1, stations } of tall.stretches) {
    near(y0, y(stretch.start));
    near(y1, y(stretch.end));
    stations.forEach(({ station, y: at }) => near(at, y(station.position)));
  }
});

test("a long axis is drawn at a smaller scale, never below the floor", () => {
  const far = mapOf(roadmap([phase("a", "2027-06-01", [false])], "2028-11-21"));
  assert.equal(far.span, 731);
  assert.equal(layoutTall(far).scale, 1.5);
});

test("labels are at least a line apart, in date order, and never above their terminus", () => {
  const tall = layoutTall(mapOf(SEVEN, TWELVE));
  // The application without a date has no lane here.
  assert.equal(tall.lanes.length, 11);
  for (let i = 0; i < tall.lanes.length; i++) {
    const lane = tall.lanes[i];
    assert.ok(lane.labelY >= lane.y1 - 1e-9, `${lane.lane.row.record.id} label above its terminus`);
    if (i > 0) {
      assert.ok(lane.labelY - tall.lanes[i - 1].labelY >= TALL_LABEL_PITCH - 1e-9);
      assert.ok(lane.x > tall.lanes[i - 1].x);
    }
  }
  // Three applications due the same day share a terminus level and get three label lines.
  const sameDay = tall.lanes.filter((lane) => lane.lane.row.record.deadline === "2027-01-15");
  assert.equal(new Set(sameDay.map((lane) => lane.y1)).size, 1);
  assert.equal(new Set(sameDay.map((lane) => lane.labelY)).size, 3);
  assert.ok(tall.height >= Math.max(...tall.lanes.map((lane) => lane.labelY)) + 20);
});

test("the piece that crosses to a label only passes lanes that have already ended", () => {
  const tall = layoutTall(mapOf(SEVEN, TWELVE));
  for (const lane of tall.lanes) {
    for (const other of tall.lanes) {
      if (other.x >= lane.x) continue;
      // `other` is to the left: its line, and the piece running on to its own label, end above this label's level.
      assert.ok(other.labelY < lane.labelY, `${lane.lane.row.record.id} crosses ${other.lane.row.record.id}`);
      assert.ok(other.y1 <= lane.labelY);
    }
  }
});

test("a label level with its terminus is reached straight across; a lower one down the lane, then across at 45 degrees", () => {
  const tall = layoutTall(mapOf(SEVEN, [record("a", { deadline: "2027-01-15" }), record("b", { deadline: "2027-01-15" }), record("c", { deadline: "2027-01-16" })]));
  const [a, b, c] = tall.lanes;
  assert.equal(a.leader, `M${a.x} ${a.y1}H${tall.labelRight + 5}`);
  assert.equal(b.leader, `M${b.x} ${b.y1}V${b.labelY - 6}L${b.x - 6} ${b.labelY}H${tall.labelRight + 5}`);
  near(b.labelY, a.labelY + TALL_LABEL_PITCH);
  near(c.labelY, b.labelY + TALL_LABEL_PITCH);
});

test("a date written with its year gets a wider label column", () => {
  const near = layoutTall(mapOf(SEVEN, [record("a", { deadline: "2027-06-30" })]));
  const far = layoutTall(mapOf(roadmap([phase("a", "2027-06-01", [false])], "2028-02-15"), [record("a", { deadline: "2027-11-30" })]));
  assert.ok(far.labelRight > near.labelRight);
  assert.ok(far.lanes[0].x > far.labelRight);
});

test("when the intake has passed, the line still ends on the intake, above today", () => {
  const map = mapOf(roadmap([phase("a", "2026-01-01", [false])], "2026-07-15"), [record("a", { deadline: "2026-12-01" })]);
  const tall = layoutTall(map);
  near(tall.intakeY, tall.stretches[0].y1);
  assert.ok(tall.intakeY < tall.todayY!);
  near(tall.todayY!, tall.endY);
  // With the intake ahead, the two are the same place.
  const usual = layoutTall(mapOf(SEVEN));
  near(usual.intakeY, usual.endY);
});

test("a deadline today keeps its label clear of today's bar", () => {
  const tall = layoutTall(mapOf(SEVEN, [record("a", { deadline: TODAY })]));
  near(tall.lanes[0].y1, tall.todayY!);
  near(tall.lanes[0].labelY, tall.todayY! + TALL_CLEAR);
});

test("with no application to draw, the left column only holds today's label", () => {
  const none = layoutTall(mapOf(SEVEN));
  const some = layoutTall(mapOf(SEVEN, TWELVE));
  assert.ok(none.labelRight > 0 && none.labelRight < some.labelRight);
  assert.ok(none.journeyX < 100);
  assert.ok(none.todayX[0] > none.labelRight && none.todayX[1] > none.journeyX);
  assert.ok(some.journeyX > some.lanes.at(-1)!.x);
  // Eleven lanes still leave the phases' names more than a third of a 358px frame.
  assert.ok(some.journeyX < 358 * 0.6, String(some.journeyX));
});

test("without an intake the tall map is the stretches in order, one slot per station", () => {
  const plan = roadmap([phase("a", null, [true, true]), phase("b", null, [false, false, false, false])], null);
  const tall = layoutTall(mapOf(plan, TWELVE));
  assert.equal(tall.todayY, null);
  assert.equal(tall.lanes.length, 0);
  assert.equal(tall.labelRight, 0);
  assert.ok(tall.journeyX < 20);
  near(tall.stretches[1].y1 - tall.stretches[1].y0, 4 * tall.scale);
  near(tall.stretches[0].stations[1].y - tall.stretches[0].stations[0].y, tall.scale);
});

test("top to bottom, a stretch squeezed into a few days is opened up for its name, and dates keep their order", () => {
  const rows = overviewOf([record("m", { deadline: "2026-12-20" }), record("e", { deadline: "2027-01-15" })], TODAY).rows;
  const timeline = timelineOf(LATE, NOW, { date: "2026-12-20", school: "m", checked: false });
  const tall = layoutTall(roadmapMap(timeline, rows, TODAY));
  for (const { y0, y1, stations } of tall.stretches) {
    assert.ok(y1 - y0 >= TALL_MIN_STRETCH - 1e-9);
    assert.ok(stations.every(({ y }) => y > y0 && y < y1));
  }
  for (let i = 1; i < tall.stretches.length; i++) near(tall.stretches[i].y0, tall.stretches[i - 1].y1);
  // The first deadline ends where applying ends; the later one further down, both under today.
  near(tall.lanes[0].y1, tall.stretches[4].y1);
  assert.ok(tall.todayY! < tall.lanes[0].y1 && tall.lanes[0].y1 < tall.lanes[1].y1 && tall.lanes[1].y1 < tall.endY);
});
