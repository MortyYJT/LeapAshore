import { test } from "node:test";
import assert from "node:assert/strict";

import {
  DEMO_DATED,
  DEMO_PROGRAM_IDS,
  DEMO_SCHOOL_IDS,
  demoProgramHref,
  demoRecords,
  loadDemoPrograms,
  type DemoProgram,
  type DemoQuery,
} from "./demo.ts";
import { overviewOf } from "./overview.ts";

const TODAY = "2026-11-20";

/** A catalogue program with the deadlines given as `[date, source]` pairs. */
function program(slug: string, school: string, dates: (string | [string, string])[] | null = []): DemoProgram {
  return {
    slug,
    name: `${slug} 中文名`,
    nameEn: `MSc ${slug}`,
    university: school,
    universityId: `id-${school}`,
    deadlines:
      dates &&
      dates.map((entry) => {
        const [date, sourceUrl] = typeof entry === "string" ? [entry, `https://example.test/${slug}`] : entry;
        return { label: "Round", date, sourceUrl };
      }),
  };
}

function byId(records: ReturnType<typeof demoRecords>) {
  return new Map((records ?? []).map((record) => [record.programId, record]));
}

test("the preferred list is longer than the demo and has no duplicates", () => {
  assert.equal(new Set(DEMO_PROGRAM_IDS).size, DEMO_PROGRAM_IDS.length);
  assert.equal(new Set(DEMO_SCHOOL_IDS).size, DEMO_SCHOOL_IDS.length);
  assert.ok(DEMO_PROGRAM_IDS.length > DEMO_DATED);
});

test("dates, names and sources are the catalogue's own; nothing is filled in", () => {
  const records = demoRecords(
    [
      program("a", "甲大学", [["2027-01-06", "https://a.example/apply"], "2027-03-10"]),
      program("b", "乙大学", ["2027-02-01"]),
    ],
    TODAY,
  );
  const a = byId(records).get("a")!;
  assert.equal(a.id, "demo:a");
  assert.equal(a.school, "甲大学");
  assert.equal(a.name, "MSc a");
  assert.equal(a.deadline, "2027-01-06");
  assert.equal(a.sourceUrl, "https://a.example/apply");
  assert.equal(a.deadlineOrigin, "collected");
  // Nobody has checked a collected date, and the catalogue's round label is not the applicant's round.
  assert.equal(a.checkedAt, null);
  assert.equal(a.round, null);
});

test("a program shows its earliest deadline that has not passed", () => {
  const records = demoRecords(
    [program("a", "甲大学", ["2026-11-06", "2027-01-01", "2027-02-26"]), program("b", "乙大学", ["2026-11-20"])],
    TODAY,
  );
  assert.equal(byId(records).get("a")!.deadline, "2027-01-01");
  // A deadline on today's date is still open.
  assert.equal(byId(records).get("b")!.deadline, "2026-11-20");
});

test("a program whose every deadline has passed is left out, not drawn as unknown", () => {
  const records = demoRecords(
    [
      program("past", "甲大学", ["2026-10-01", "2026-11-19"]),
      program("b", "乙大学", ["2027-01-10"]),
      program("c", "丙大学", ["2027-02-10"]),
    ],
    TODAY,
  );
  assert.deepEqual([...byId(records).keys()].sort(), ["b", "c"]);
});

test("one program without any collected date is drawn as unknown; a missing list is not 'no date'", () => {
  const records = demoRecords(
    [
      program("b", "乙大学", ["2027-01-10"]),
      program("old-server", "丁大学", null),
      program("none-1", "戊大学", []),
      program("c", "丙大学", ["2027-02-10"]),
      program("none-2", "己大学", []),
    ],
    TODAY,
  );
  const unknown = (records ?? []).filter((record) => record.deadline === null);
  assert.deepEqual(unknown.map((record) => record.programId), ["none-1"]);
  assert.equal(unknown[0].sourceUrl, null);
  assert.equal(unknown[0].deadlineOrigin, null);
  assert.equal(unknown[0].status, "considering");
  assert.ok(!byId(records).has("old-server"));
});

test("at most four dated programs, in the order of the list, one per school", () => {
  const records = demoRecords(
    [
      program("a1", "甲大学", ["2027-03-01"]),
      program("a2", "甲大学", ["2027-01-01"]),
      program("b", "乙大学", ["2027-02-01"]),
      program("c", "丙大学", ["2027-04-01"]),
      program("d", "丁大学", ["2027-05-01"]),
      program("e", "戊大学", ["2027-01-15"]),
    ],
    TODAY,
  );
  assert.deepEqual([...byId(records).keys()].sort(), ["a1", "b", "c", "d"]);
});

test("a deadline within two weeks is shown when the catalogue has one, wherever it is in the list", () => {
  const listed = [
    program("a", "甲大学", ["2027-03-01"]),
    program("b", "乙大学", ["2027-02-01"]),
    program("c", "丙大学", ["2027-04-01"]),
    program("d", "丁大学", ["2027-05-01"]),
    program("soon-later", "戊大学", ["2026-12-04"]),
    program("soon", "己大学", ["2026-11-27"]),
  ];
  const records = demoRecords(listed, TODAY)!;
  assert.deepEqual(records.map((record) => record.programId).sort(), ["a", "b", "c", "soon"]);
  const model = overviewOf(records, TODAY);
  assert.equal(model.nearest?.record.programId, "soon");
  assert.equal(model.nearest?.soon, true);
  // Fifteen days away is not "within two weeks".
  const none = demoRecords([...listed.slice(0, 4), program("x", "庚大学", ["2026-12-05"])], TODAY)!;
  assert.ok(!none.some((record) => record.programId === "x"));
});

test("the applicant's side is a fixed mix: the nearest still open, one submitted, one ready, one being considered", () => {
  const records = demoRecords(
    [
      program("d", "丁大学", ["2027-03-22"]),
      program("a", "甲大学", ["2026-12-01"]),
      program("c", "丙大学", ["2027-01-31"]),
      program("b", "乙大学", ["2027-01-06"]),
      program("none", "戊大学", []),
    ],
    TODAY,
  )!;
  const state = (id: string) => {
    const record = byId(records).get(id)!;
    return [record.status, record.materialsReady];
  };
  assert.deepEqual(state("a"), ["applying", false]);
  assert.deepEqual(state("b"), ["submitted", true]);
  assert.deepEqual(state("c"), ["applying", true]);
  assert.deepEqual(state("d"), ["considering", false]);
  assert.deepEqual(state("none"), ["considering", false]);

  // The overview then has every kind of row and every kind of next action.
  const model = overviewOf(records, TODAY);
  assert.equal(model.rows.length, 5);
  assert.equal(model.sentCount, 1);
  assert.equal(model.unknown.length, 1);
  assert.deepEqual(model.next.map((action) => action.kind), ["confirm", "materials", "submit"]);
});

test("with fewer than two dated programs there is no demo", () => {
  assert.equal(demoRecords([program("a", "甲大学", ["2027-01-01"]), program("none", "乙大学", [])], TODAY), null);
  assert.equal(demoRecords([], TODAY), null);
  // Two are enough, and they still show an open and a submitted application.
  const two = demoRecords([program("a", "甲大学", ["2027-01-01"]), program("b", "乙大学", ["2027-02-01"])], TODAY)!;
  assert.deepEqual(two.map((record) => record.status).sort(), ["applying", "submitted"]);
});

test("a date that cannot be read does not count as a deadline", () => {
  const records = demoRecords(
    [program("bad", "甲大学", ["soon"]), program("b", "乙大学", ["2027-01-10"]), program("c", "丙大学", ["2027-02-10"])],
    TODAY,
  );
  assert.ok(!byId(records).has("bad"));
});

test("the same programs give the same records on every call", () => {
  const listed = [program("a", "甲大学", ["2027-01-01"]), program("b", "乙大学", ["2027-02-01"]), program("n", "丙大学", [])];
  assert.deepEqual(demoRecords(listed, TODAY), demoRecords(listed, TODAY));
});

test("a demo row links to the program's own public page", () => {
  assert.equal(demoProgramHref({ programId: "ucl-computer-science-msc-9d29ee" }), "/programs/ucl-computer-science-msc-9d29ee");
  assert.equal(demoProgramHref({ programId: "a b/c" }), "/programs/a%20b%2Fc");
});

// ---------- reading the catalogue ----------

function reader(answers: { listed: DemoProgram[]; pool?: DemoProgram[] | Error }) {
  const asked: DemoQuery[] = [];
  const read = async (query: DemoQuery) => {
    asked.push(query);
    if (query.ids) return answers.listed;
    if (answers.pool instanceof Error) throw answers.pool;
    return answers.pool ?? [];
  };
  return { asked, read };
}

test("the preferred programs are asked for by id and put back in the list's order", async () => {
  const ids = DEMO_PROGRAM_IDS.slice(0, 5);
  // The API answers in its own order (by id).
  const listed = [...ids].reverse().map((slug, i) => program(slug, `学校 ${i}`, ["2027-01-10"]));
  const { asked, read } = reader({ listed });
  const programs = await loadDemoPrograms(TODAY, read);
  assert.deepEqual(asked, [{ ids: [...DEMO_PROGRAM_IDS] }]);
  assert.deepEqual(programs.map((p) => p.slug), ids);
});

test("when the list comes up short, computing programs at the same schools fill in, nearest date first", async () => {
  const listed = [
    program(DEMO_PROGRAM_IDS[0], "甲大学", ["2027-01-10"]),
    program(DEMO_PROGRAM_IDS[1], "乙大学", ["2026-11-01"]),
  ];
  const pool = [
    program("pool-late", "丙大学", ["2027-06-01"]),
    program(DEMO_PROGRAM_IDS[0], "甲大学", ["2027-01-10"]),
    program("pool-none", "丁大学", []),
    program("pool-early", "戊大学", ["2026-10-01", "2027-02-01"]),
  ];
  const { asked, read } = reader({ listed, pool });
  const programs = await loadDemoPrograms(TODAY, read);
  assert.equal(asked.length, 2);
  assert.deepEqual(asked[1], { provider: [...DEMO_SCHOOL_IDS], q: "Comput", hasRequirements: true, limit: 100 });
  // The listed programs keep their place; the pool follows without repeating them.
  assert.deepEqual(programs.map((p) => p.slug), [DEMO_PROGRAM_IDS[0], DEMO_PROGRAM_IDS[1], "pool-early", "pool-late", "pool-none"]);
  assert.deepEqual(demoRecords(programs, TODAY)!.map((record) => record.programId).sort(), [DEMO_PROGRAM_IDS[0], "pool-early", "pool-late", "pool-none"].sort());
});

test("a full list does not ask for more, and a failed top-up keeps what the list gave", async () => {
  const full = DEMO_PROGRAM_IDS.slice(0, DEMO_DATED).map((slug, i) => program(slug, `学校 ${i}`, ["2027-01-10"]));
  const enough = reader({ listed: full });
  await loadDemoPrograms(TODAY, enough.read);
  assert.equal(enough.asked.length, 1);

  const short = reader({ listed: full.slice(0, 2), pool: new Error("502") });
  const programs = await loadDemoPrograms(TODAY, short.read);
  assert.equal(short.asked.length, 2);
  assert.equal(programs.length, 2);
});
