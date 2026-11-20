import { test } from "node:test";
import assert from "node:assert/strict";
import type { ApplicationRecord } from "./application-records.ts";
import type { RecordMaterial } from "./materials.ts";
import {
  DEMO_MAX_PROGRAMS,
  VERTICAL_BELOW,
  demoMaterialRecords,
  drawsHorizontally,
  layoutMap,
  materialsModel,
} from "./materials-map.ts";

// Every requirement below is made up for these tests; none describes a real program.
function material(type: string, fields: Partial<RecordMaterial> = {}): RecordMaterial {
  return {
    key: type,
    type,
    count: null,
    note: null,
    quote: `FIXTURE: the page asks for ${type}.`,
    sourceUrl: "https://example.test/apply",
    digest: `d-${type}`,
    ready: false,
    changed: false,
    ...fields,
  };
}

function record(id: string, materials: RecordMaterial[] | null, fields: Partial<ApplicationRecord> = {}): ApplicationRecord {
  return {
    id: `catalog:${id}`,
    programId: id,
    school: `School ${id.toUpperCase()}`,
    name: "MSc Made Up",
    round: null,
    status: "applying",
    deadline: null,
    sourceUrl: null,
    checkedAt: null,
    deadlineOrigin: null,
    materials: materials ?? [],
    materialsExtracted: materials !== null,
    customMaterials: [],
    materialsDone: (materials ?? []).filter((m) => m.ready).length,
    materialsTotal: (materials ?? []).length,
    materialsReady: false,
    materialNotes: "",
    version: "v1",
    ...fields,
  };
}

const two = (fields: Partial<RecordMaterial> = {}) => material("recommendation", { count: 2, ...fields });

/** Five programs: a CV and transcripts everywhere, letters that differ at one, an essay with a limit at one, a test at one. */
function five(): ApplicationRecord[] {
  return [
    record("a", [material("cv"), material("transcript"), two(), material("personal_statement")], { deadline: "2027-01-10" }),
    record("b", [material("cv"), material("transcript"), two({ ready: true }), material("personal_statement", { note: "up to 500 words" })], { deadline: "2027-02-10" }),
    record("c", [material("cv"), material("transcript"), two(), material("personal_statement")], { deadline: "2027-03-10" }),
    record("d", [material("cv"), material("transcript"), two(), material("test_score", { note: "GRE recommended" })], { deadline: "2027-04-10" }),
    record("e", [material("cv"), material("transcript"), material("recommendation", { count: 3 })], { deadline: "2027-05-10" }),
  ];
}

test("a material every program asks for in the same form is shared, and the rest are columns", () => {
  const model = materialsModel(five());
  assert.deepEqual(model.shared.map((column) => column.type), ["transcript", "cv"]);
  assert.deepEqual(model.differing.map((column) => column.type), ["recommendation", "personal_statement", "test_score"]);
  assert.equal(model.lines.length, 5);
  assert.deepEqual(model.lines.map((line) => line.record.programId), ["a", "b", "c", "d", "e"], "nearest deadline first, as on the overview");
});

test("a count that departs from most programs is marked, and the others are not", () => {
  const letters = materialsModel(five()).differing[0];
  assert.equal(letters.common, "2 封");
  assert.deepEqual(letters.requirements.map((r) => [r.line.record.programId, r.caption, r.differs]), [
    ["a", "2 封", false], ["b", "2 封", false], ["c", "2 封", false], ["d", "2 封", false], ["e", "3 封", true],
  ]);
  assert.deepEqual(letters.absent, []);
});

test("something particular noted on one program marks that program only, and a program that does not ask is absent", () => {
  const [, essay, test_score] = materialsModel(five()).differing;
  assert.equal(essay.common, "", "most state no count: the common form is 'asked, no number'");
  assert.deepEqual(essay.requirements.map((r) => [r.line.record.programId, r.caption, r.differs]), [
    ["a", "要交", false], ["b", "另有说明", true], ["c", "要交", false],
  ]);
  assert.deepEqual(essay.absent.map((line) => line.record.programId), ["d", "e"]);
  // Asked by one program only: there is no common form, so nothing is said to differ.
  assert.equal(test_score.common, null);
  assert.deepEqual(test_score.requirements.map((r) => r.differs), [false]);
});

test("a program that was not read is kept apart: it has no stops and breaks no sharing", () => {
  const model = materialsModel([...five(), record("f", null), record("m", null, { programId: null, id: "manual-1" })]);
  assert.deepEqual(model.unread.map((line) => line.record.programId), ["f"]);
  assert.deepEqual(model.manual.map((line) => line.record.id), ["manual-1"]);
  // Still shared among the five that were read: the unread one is not counted as "does not ask".
  assert.deepEqual(model.shared.map((column) => column.type), ["transcript", "cv"]);
  assert.ok(model.differing.every((column) => column.absent.every((line) => line.record.programId !== "f")));
});

test("one program alone shares nothing and differs from nothing", () => {
  const model = materialsModel([record("a", [material("cv"), two()])]);
  assert.deepEqual(model.shared, []);
  assert.deepEqual(model.differing.map((column) => [column.type, column.common, column.requirements[0].differs]), [
    ["cv", null, false], ["recommendation", null, false],
  ]);
});

test("a page that was read and lists nothing is a line with no stops, not an unread program", () => {
  const model = materialsModel([record("a", [material("cv")]), record("b", [])]);
  assert.deepEqual(model.lines.map((line) => line.record.programId), ["a", "b"]);
  assert.deepEqual(model.unread, []);
  assert.deepEqual(model.shared, [], "one of two does not ask: not shared");
  assert.deepEqual(model.differing[0].absent.map((line) => line.record.programId), ["b"]);
});

test("other documents are never merged, and two entries of one type are counted together", () => {
  const model = materialsModel([
    record("a", [material("other", { note: "passport copy" }), material("other", { key: "other-2", note: "course descriptions" })]),
    record("b", [material("other", { note: "passport copy" })]),
  ]);
  assert.deepEqual(model.shared, []);
  const [other] = model.differing;
  assert.equal(other.name, "其他");
  assert.deepEqual(other.requirements.map((r) => [r.caption, r.entries.length]), [["2 项", 2], ["要交", 1]]);
});

test("the totals count requirements per program, and a hub is ready only when every line ticked it", () => {
  const records = five();
  records[0].materials[0].ready = true; // one CV of five
  const model = materialsModel(records);
  assert.equal(model.total, 4 + 4 + 4 + 4 + 3);
  assert.equal(model.done, 2);
  const cv = model.shared.find((column) => column.type === "cv")!;
  assert.deepEqual(cv.requirements.map((r) => r.ready), [true, false, false, false, false]);
  const hub = layoutMap(model, 1000).hubs.find((h) => h.column === cv)!;
  assert.equal(hub.ready, false);
  assert.ok(layoutMap(model, 1000).labels.some((label) => label.kind === "hub-state" && label.text === "备好 1/5"));
});

test("applications that are submitted or decided are left out and counted", () => {
  const model = materialsModel([...five(), record("s", [material("cv")], { status: "submitted" }), record("x", null, { status: "excluded" })]);
  assert.equal(model.lines.length, 5);
  assert.equal(model.closed, 2);
});

test("an application keeps the overview's colour and code", () => {
  const records = five();
  const again = materialsModel([...records].reverse());
  const first = materialsModel(records);
  assert.deepEqual(
    first.lines.map((line) => [line.record.id, line.line, line.code]),
    again.lines.map((line) => [line.record.id, line.line, line.code]),
  );
  assert.equal(new Set(first.lines.map((line) => line.line)).size, 5, "five applications, five colours");
});

test("a program that is also in the rail keeps the rail's colour, whatever else is drawn", () => {
  const records = five();
  const railIds = records.map((r) => r.id);
  const rail = materialsModel(records);
  const colourOf = (id: string) => rail.lines.find((line) => line.record.id === id)!.line;
  // A subset of the rail's programs.
  for (const line of materialsModel(records.slice(1, 4), railIds).lines) assert.equal(line.line, colourOf(line.record.id));
  // One of the rail's programs drawn with two that the rail does not list.
  const extra = [record("x", [material("cv")]), record("y", [material("cv")])];
  const mixed = materialsModel([records[2], ...extra], railIds);
  assert.equal(mixed.lines.find((line) => line.record.id === records[2].id)!.line, colourOf(records[2].id));
});

test("with no majority nothing is marked as different", () => {
  const counts = [2, 2, 3, 3];
  const model = materialsModel(counts.map((count, i) => record("abcd"[i], [material("recommendation", { count })])));
  const [letters] = model.differing;
  assert.equal(letters.common, null);
  assert.deepEqual(letters.requirements.map((r) => [r.caption, r.differs]), [["2 封", false], ["2 封", false], ["3 封", false], ["3 封", false]]);
});

test("every capsule and column gets at least 64px, or the map is drawn top to bottom", () => {
  for (const [sharedCount, differingCount] of [[7, 1], [1, 7], [4, 4], [2, 6]]) {
    const types = ["transcript", "language_score", "cv", "recommendation", "personal_statement", "test_score", "writing_sample", "portfolio"];
    const records = ["a", "b"].map((id, i) => record(id, types.map((type, t) => material(type, t < sharedCount ? {} : { note: `note ${i}` }))));
    const model = materialsModel(records);
    assert.equal(model.shared.length, sharedCount);
    assert.equal(model.differing.length, differingCount);
    for (const width of [640, 700, 820, 1000]) {
      const map = layoutMap(model, width);
      if (map.vertical) continue;
      const hubs = map.hubs.map((hub) => hub.x).sort((a, b) => a - b);
      const cols = [...new Set(map.stations.map((station) => station.x))].sort((a, b) => a - b);
      for (const xs of [hubs, cols]) for (let i = 1; i < xs.length; i++) assert.ok(xs[i] - xs[i - 1] >= 64 - 0.001, `${sharedCount}+${differingCount} at ${width}: ${xs[i] - xs[i - 1]}`);
    }
  }
});

test("a wide frame draws left to right, and everything stays inside it", () => {
  const model = materialsModel([...five(), record("f", null)]);
  const map = layoutMap(model, 1000);
  assert.equal(map.vertical, false);
  assert.equal(map.paths.length, 5);
  assert.equal(map.dotted.length, 1);
  assert.equal(map.hubs.length, 2);
  assert.equal(map.stations.length, 5 + 3 + 1);
  for (const station of map.stations) {
    assert.ok(station.x > 0 && station.x < map.width - 54, `station at ${station.x} is on its run`);
    assert.ok(station.y > 0 && station.y < map.height);
  }
  // Each line has its own run after the fan, 46px apart, and an unread program runs below them all.
  const ends = map.labels.filter((label) => label.kind === "end").map((label) => label.y);
  assert.deepEqual(ends.map((y, i) => (i ? y - ends[i - 1] : 0)), [0, 46, 46, 46, 46, 38], "the unread run sits closer: it has no caption");
  assert.ok(ends.at(-1)! < map.height);
  // A station sits on its own program's run.
  const run = new Map(map.labels.filter((label) => label.kind === "end").map((label) => [label.line!.record.id, label.y]));
  for (const station of map.stations) assert.equal(station.y, run.get(station.requirement.line.record.id));
});

test("a narrow frame draws top to bottom, inside 390px", () => {
  const model = materialsModel([...five(), record("f", null)]);
  const map = layoutMap(model, 358); // a 390px phone less its margins
  assert.equal(map.vertical, true);
  assert.ok(map.width <= 358);
  for (const station of map.stations) assert.ok(station.x > 62 && station.x < map.width);
  for (const hub of map.hubs) assert.ok(hub.x >= 0 && hub.x + hub.width <= map.width);
  assert.equal(new Set(map.labels.filter((label) => label.kind === "end").map((label) => label.x)).size, 6, "one lane per program");
});

test("a map with more columns than a wide frame can hold falls back to top to bottom", () => {
  const types = ["transcript", "language_score", "cv", "recommendation", "personal_statement", "test_score", "writing_sample", "portfolio", "other"];
  // Five programs: transcripts shared, the other eight types each with something noted.
  const records = ["a", "b", "c", "d", "e"].map((id, i) => record(id, types.map((type) => material(type, type === "transcript" ? {} : { note: `note ${i}` }))));
  const model = materialsModel(records);
  assert.equal(model.shared.length, 1);
  assert.equal(model.differing.length, 8);
  assert.equal(drawsHorizontally(model, VERTICAL_BELOW + 20), false);
  assert.equal(drawsHorizontally(model, 1000), true);
});

test("crowded lanes keep only the marked captions", () => {
  const records = "abcdefgh".split("").map((id, i) => record(id, [two(i === 7 ? { count: 3 } : {})]));
  const map = layoutMap(materialsModel(records), 358);
  assert.equal(map.stations.length, 8);
  assert.deepEqual(map.labels.filter((label) => label.kind === "caption").map((label) => [label.text, label.differs]), [["3 封", true]]);
});

test("nothing read yet draws only the dotted runs", () => {
  const map = layoutMap(materialsModel([record("a", null), record("b", null)]), 1000);
  assert.equal(map.paths.length, 0);
  assert.equal(map.dotted.length, 2);
  assert.equal(map.hubs.length + map.stations.length, 0);
  assert.ok(Number.isFinite(map.height) && map.height > 0);
});

test("the signed-out map is drawn only from what the catalogue serves", () => {
  const item = { key: "cv", type: "cv", count: null, note: null, quote: "FIXTURE: a CV.", sourceUrl: "https://example.test/a" };
  const program = (slug: string, university: string, materials: unknown) =>
    ({ slug, name: slug, nameEn: `MSc ${slug}`, university, materials }) as Parameters<typeof demoMaterialRecords>[0][number];

  // Not read, read with nothing listed, and a second program of a school already drawn are all left out.
  const programs = [
    program("p1", "U1", { items: [item] }),
    program("p2", "U2", null),
    program("p3", "U3", { items: [] }),
    program("p4", "U1", { items: [item] }),
    program("p5", "U5", { items: [item, { ...item, key: "recommendation", type: "recommendation", count: 2 }] }),
  ];
  const records = demoMaterialRecords(programs)!;
  assert.deepEqual(records.map((r) => r.programId), ["p1", "p5"]);
  assert.ok(records.every((r) => r.materialsExtracted && r.materials.every((m) => !m.ready)), "nothing is ticked in a demo");
  assert.deepEqual(records[1].materials.map((m) => [m.type, m.count, m.quote]), [["cv", null, "FIXTURE: a CV."], ["recommendation", 2, "FIXTURE: a CV."]]);

  // Too few read programs: no demo at all, never a made-up one.
  assert.equal(demoMaterialRecords(programs.slice(0, 4)), null);
  assert.equal(demoMaterialRecords([]), null);
  const many = Array.from({ length: 9 }, (_, i) => program(`q${i}`, `V${i}`, { items: [item] }));
  assert.equal(demoMaterialRecords(many)!.length, DEMO_MAX_PROGRAMS);
});
