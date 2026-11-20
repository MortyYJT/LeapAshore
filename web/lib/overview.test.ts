import { test } from "node:test";
import assert from "node:assert/strict";

import type { ApplicationRecord } from "./application-records.ts";
import {
  LINE_COLOURS,
  assignLines,
  dateLabel,
  daysUntil,
  lineCode,
  nextSentence,
  overviewOf,
} from "./overview.ts";

const TODAY = "2026-11-20";

function record(id: string, fields: Partial<ApplicationRecord> = {}): ApplicationRecord {
  return {
    id,
    programId: null,
    school: `学校 ${id}`,
    name: "MSc",
    round: null,
    status: "applying",
    deadline: null,
    sourceUrl: null,
    checkedAt: null,
    deadlineOrigin: null,
    materialsReady: false,
    materialNotes: "",
    materials: [],
    materialsExtracted: false,
    customMaterials: [],
    materialsDone: 0,
    materialsTotal: 0,
    version: "v1",
    ...fields,
  };
}

test("daysUntil counts calendar days and is negative once the date has passed", () => {
  assert.equal(daysUntil("2026-11-20", TODAY), 0);
  assert.equal(daysUntil("2026-12-15", TODAY), 25);
  assert.equal(daysUntil("2026-11-19", TODAY), -1);
  // A timestamp is read by its date.
  assert.equal(daysUntil("2026-12-15T00:00:00Z", TODAY), 25);
});

test("lineCode takes a Chinese name's stem, at most three characters", () => {
  assert.equal(lineCode("香港大学"), "香港");
  assert.equal(lineCode("香港科技大学"), "香港科");
  assert.equal(lineCode("伦敦大学学院"), "伦敦");
  assert.equal(lineCode("杜伦大学"), "杜伦");
  assert.equal(lineCode("澳門科技大學"), "澳門科");
  assert.equal(lineCode("麻省理工学院"), "麻省理");
  // A name that is only the suffix keeps its own characters.
  assert.equal(lineCode("大学"), "大学");
});

test("lineCode reads a Latin name's own abbreviation or its initials", () => {
  assert.equal(lineCode("UCL"), "UCL");
  assert.equal(lineCode("Massachusetts Institute of Technology (MIT)"), "MIT");
  assert.equal(lineCode("University College London"), "UCL");
  assert.equal(lineCode("The University of Hong Kong"), "UHK");
  assert.equal(lineCode("Durham University"), "DU");
  assert.equal(lineCode("Stanford"), "STA");
  // An apostrophe is part of its word.
  assert.equal(lineCode("King's College London"), "KCL");
  assert.equal(lineCode("Queen’s University Belfast"), "QUB");
  assert.equal(lineCode("  "), "?");
});

test("assignLines gives each application its own colour while colours last", () => {
  const ids = ["catalog:a", "catalog:b", "p-1", "p-2", "p-3"];
  const lines = assignLines(ids);
  assert.equal(new Set(lines.values()).size, 5);
  // Up to five applications stay on the five original line colours.
  for (const colour of lines.values()) assert.ok(LINE_COLOURS.indexOf(colour) < 5, colour);
});

test("assignLines depends on the set of ids only, not on the order they arrive in", () => {
  const ids = Array.from({ length: 7 }, (_, i) => `record-${i}`);
  const forward = assignLines(ids);
  const backward = assignLines([...ids].reverse());
  for (const id of ids) assert.equal(forward.get(id), backward.get(id));
  assert.equal(new Set(forward.values()).size, 7);
});

test("assignLines reuses colours evenly once there are more applications than colours", () => {
  const ids = Array.from({ length: 19 }, (_, i) => `r${i}`);
  const counts = new Map<string, number>();
  for (const colour of assignLines(ids).values()) counts.set(colour, (counts.get(colour) ?? 0) + 1);
  assert.equal(counts.size, LINE_COLOURS.length);
  assert.ok(Math.max(...counts.values()) - Math.min(...counts.values()) <= 1, JSON.stringify([...counts]));
});

test("dateLabel adds the year only when the date is far enough to be ambiguous", () => {
  assert.equal(dateLabel("2026-12-15", TODAY), "12/15");
  assert.equal(dateLabel("2027-10-15", TODAY), "10/15");
  assert.equal(dateLabel("2027-12-15", TODAY), "2027/12/15");
  assert.equal(dateLabel("2025-10-01", TODAY), "2025/10/01");
});

test("overviewOf orders rows: unknown dates, then by date, then submitted", () => {
  const model = overviewOf(
    [
      record("late", { deadline: "2027-03-31" }),
      record("sent", { deadline: "2026-12-01", status: "submitted" }),
      record("unknown"),
      record("soon", { deadline: "2026-11-30", status: "considering" }),
      record("offer", { status: "offered", deadline: "2026-10-01" }),
      record("dropped", { status: "excluded" }),
    ],
    TODAY,
  );
  assert.deepEqual(model.rows.map((row) => row.record.id), ["unknown", "soon", "late", "sent"]);
  assert.equal(model.closed, 2);
  assert.equal(model.total, 6);
  const soon = model.rows[1];
  assert.equal(soon.days, 10);
  assert.equal(soon.soon, true);
  assert.equal(model.rows[2].soon, false);
  // A submitted application is not counted down, however near its date is.
  assert.equal(model.rows[3].soon, false);
  assert.equal(model.rows[3].sent, true);
});

test("overviewOf keeps one linear scale from today to past the last deadline", () => {
  const model = overviewOf([record("a", { deadline: "2027-03-31" }), record("b", { deadline: "2026-12-15" })], TODAY);
  assert.equal(model.horizon, 131 + 5);
  const [a, b] = [model.rows.find((r) => r.record.id === "a")!, model.rows.find((r) => r.record.id === "b")!];
  assert.equal(a.position, 131 / 136);
  assert.equal(b.position, 25 / 136);
  assert.equal(model.soonPosition, 14 / 136);
  // One tick per month start inside the scale.
  assert.deepEqual(model.ticks.map((tick) => tick.date), ["2026-12-01", "2027-01-01", "2027-02-01", "2027-03-01", "2027-04-01"]);
  assert.equal(model.ticks[0].position, 11 / 136);
});

test("overviewOf never shortens the scale below 90 days and gives no position without a date", () => {
  const model = overviewOf([record("a", { deadline: "2026-11-25" }), record("b"), record("c", { deadline: "2026-11-01" })], TODAY);
  assert.equal(model.horizon, 95);
  assert.equal(model.rows.find((r) => r.record.id === "b")!.position, null);
  // A passed date has no length on an axis that starts today.
  const passed = model.rows.find((r) => r.record.id === "c")!;
  assert.equal(passed.days, -19);
  assert.equal(passed.position, null);
  assert.equal(passed.soon, false);
});

test("overviewOf stops the scale at two years; a later deadline runs off its end", () => {
  const model = overviewOf([record("far", { deadline: "9999-12-31" }), record("near", { deadline: "2026-12-15" })], TODAY);
  assert.equal(model.horizon, 730 + 5);
  const [near, far] = model.rows;
  assert.equal(near.position, 25 / 735);
  assert.equal(near.beyond, false);
  assert.equal(far.position, 1);
  assert.equal(far.beyond, true);
  // A long scale is ticked by quarter, and labelled less often still.
  assert.deepEqual(model.ticks.map((tick) => tick.date.slice(0, 7)), ["2027-01", "2027-04", "2027-07", "2027-10", "2028-01", "2028-04", "2028-07", "2028-10"]);
  assert.deepEqual(model.ticks.map((tick) => tick.label).filter(Boolean), ["27 年 7 月", "28 年 1 月", "7 月"]);
});

test("overviewOf reads a date it cannot parse as unknown", () => {
  const model = overviewOf([record("odd", { deadline: "not a date" })], TODAY);
  assert.equal(model.rows[0].days, null);
  assert.equal(model.rows[0].position, null);
  assert.equal(model.horizon, 95);
});

test("overviewOf labels months sparsely and names the year when the scale is about a year or longer", () => {
  const short = overviewOf([record("a", { deadline: "2027-03-31" })], TODAY);
  assert.deepEqual(short.ticks.map((tick) => tick.label), [null, "1 月", "2 月", "3 月", "4 月"]);
  const long = overviewOf([record("a", { deadline: "2028-02-01" })], TODAY);
  const labels = long.ticks.map((tick) => tick.label).filter(Boolean);
  // The first label and the first one of each later year carry the year; the others do not.
  assert.deepEqual(labels, ["27 年 4 月", "7 月", "10 月", "28 年 1 月"]);
  // A label with a year is wider, so labels on a long scale keep more distance.
  const labelled = long.ticks.filter((tick) => tick.label);
  for (let i = 1; i < labelled.length; i++) assert.ok(labelled[i].position - labelled[i - 1].position > 0.15);
});

test("overviewOf lists what to do next: unknown dates first, then the nearest, three at most", () => {
  const model = overviewOf(
    [
      record("ready", { deadline: "2027-01-15", materialsReady: true }),
      record("unknown"),
      record("lacking", { deadline: "2026-12-15" }),
      record("passed", { deadline: "2026-11-01" }),
      record("far", { deadline: "2027-06-01" }),
      record("sent", { status: "submitted", deadline: "2026-11-25" }),
    ],
    TODAY,
  );
  assert.deepEqual(
    model.next.map((action) => [action.row.record.id, action.kind]),
    [["unknown", "confirm"], ["passed", "passed"], ["lacking", "materials"]],
  );
  assert.equal(nextSentence(model.next[0]), "截止日期还没确认。");
  assert.equal(nextSentence(model.next[1]), "11 月 1 日的截止日期已过。");
  assert.equal(nextSentence(model.next[2]), "还有 25 天，材料还没备齐。");
});

test("nextSentence says when the materials are ready and when the date is today", () => {
  const model = overviewOf(
    [record("ready", { deadline: "2027-01-15", materialsReady: true }), record("today", { deadline: TODAY })],
    TODAY,
  );
  assert.deepEqual(model.next.map((action) => action.kind), ["materials", "submit"]);
  assert.equal(nextSentence(model.next[0]), "今天截止，材料还没备齐。");
  assert.equal(nextSentence(model.next[1]), "还有 56 天，材料已就绪，还没提交。");
});

test("overviewOf names the nearest open deadline and the applications without one", () => {
  const model = overviewOf(
    [
      record("a", { school: "甲大学", deadline: "2026-12-15" }),
      record("b", { school: "乙大学" }),
      record("c", { school: "丙大学", deadline: "2026-11-01" }),
      record("d", { school: "丁大学", deadline: "2026-11-22", status: "submitted" }),
    ],
    TODAY,
  );
  // Neither a passed date nor a submitted application is "the nearest deadline".
  assert.equal(model.nearest?.record.id, "a");
  assert.deepEqual(model.unknown.map((row) => row.record.id), ["b"]);
  assert.equal(model.sentCount, 1);
});

test("overviewOf of no records is empty but still has a scale", () => {
  const model = overviewOf([], TODAY);
  assert.deepEqual(model.rows, []);
  assert.equal(model.horizon, 95);
  assert.equal(model.nearest, null);
  assert.equal(model.ticks.length, 3);
});
