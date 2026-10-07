// Tests for the page's read of the served roadmap definition: what the page holds when the read
// succeeds, and — the reason this file exists — what it holds when the read fails.
//
// `roadmap-sync.test.ts` pins the mapper's half of §3.8: `toReplacePayload(null, …)` is `null`, so a
// caller that has no definition writes nothing. That test calls the mapper with `null` itself, so it
// says nothing about whether the page ever arrives in that state. The page's half is
// `roadmap-definition.ts`: the read's failure branch has to leave the definition `null` rather than
// fill it with the built-in `DEFAULT_DEFINITION`. Filling it in is the mistake that reintroduces the
// deletion §3.8 is about — the fallback has no visa phase, so the recomputation built from it would
// state an applicable-key set without the visa keys and the server would delete those rows and their
// completion state — and it is invisible to every other test in this directory, because the built-in
// copy is a definition like any other to the mapper.
//
// The read is driven here through `readRoadmapDefinition`, the same function the page calls in its
// mount effect, with a loader that rejects. That is the only way to reach the failure branch without
// stopping the backend, and it is why the page's read lives in this module rather than in the
// component, where nothing in `npm test` could execute it.

import assert from "node:assert/strict";
import test from "node:test";

import { DEFAULT_DEFINITION, buildRoadmap } from "./roadmap.ts";
import { fetchRoadmapDefinition } from "./api.ts";
import {
  LOCAL_DEFINITION_NOTICE,
  NO_DEFINITION_READ,
  readRoadmapDefinition,
} from "./roadmap-definition.ts";
import { toReplacePayload } from "./roadmap-sync.ts";
import type { ServedRoadmapDefinition } from "./roadmap-source.ts";
import type { Profile } from "./types.ts";

/** The profile the page under test would have: a taught master's, so `visa-gs` and `spe-cv` apply. */
const PROFILE: Profile = {
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
  annualBudgetCny: 250_000,
  intake: "2027 S1",
};

const NOW = new Date("2026-10-06T00:00:00Z");

/**
 * One definition as the route serves it, carrying both halves the page reads: the phases and materials
 * the builder walks, and the caller's own task row. The visa phase is here because its absence from
 * `DEFAULT_DEFINITION` is what makes the fallback dangerous to write from.
 */
const SERVED: ServedRoadmapDefinition = {
  phases: [
    { key: "specialized", title: "专项申请材料", subtitle: null, offsetDays: 210, sortOrder: 0 },
    { key: "visa", title: "签证与行前", subtitle: null, offsetDays: 30, sortOrder: 1 },
  ],
  materials: [
    {
      key: "spe-cv",
      phase: "specialized",
      title: "学术简历（CV）",
      detail: "一页为主。",
      appliesTo: "all",
      sortOrder: 0,
    },
    {
      key: "visa-gs",
      phase: "visa",
      title: "GS 陈述",
      detail: "签证材料。",
      appliesTo: "all",
      sortOrder: 0,
    },
  ],
  tasks: [
    {
      id: "0f0f0f0f-0000-0000-0000-000000000000",
      materialKey: "spe-cv",
      programId: "",
      phase: "specialized",
      status: "pending",
      suggestedAt: "2026-06-09",
      dueAt: "2026-06-09",
      scheduleOrigin: "suggested",
      origin: "system",
      documentId: null,
      completedAt: null,
      createdAt: "2026-10-07T12:41:51.352633Z",
      updatedAt: "2026-10-07T12:41:51.352633Z",
    },
  ],
};

test("a failed read leaves the page with no definition, so there is nothing to write from", async () => {
  // The loader rejects the way `fetchRoadmapDefinition` does when the route answers 500 or the response
  // cannot be walked. The page's answer to that must be `null`, not the built-in copy.
  const read = await readRoadmapDefinition(async () => {
    throw new Error("读取路线图定义失败：500");
  });

  assert.equal(
    read.definition,
    null,
    "a failed read must leave no definition at all; the built-in copy here is the §3.8 deletion",
  );
  assert.equal(read.notice, LOCAL_DEFINITION_NOTICE, "the fallback is rendered, so it is announced");
  assert.equal(read.tasks, null, "nothing was read, so the rows already on screen must be kept");
  assert.equal(NO_DEFINITION_READ.definition, null, "the state before the read answers is not a write");

  // The consequence, through the rule that consumes the definition rather than through a second
  // equality with `null`: the page renders the built-in copy for this state, and that copy must not
  // produce a payload. Written this way, the check fails for *any* definition the failure branch hands
  // over — a second fallback added later would be caught here too, which a comparison against
  // `DEFAULT_DEFINITION` would not do.
  const roadmap = buildRoadmap(PROFILE, [], NOW, read.definition ?? DEFAULT_DEFINITION);
  assert.ok(roadmap.phases.length > 0, "the fallback still renders; it is only unwritable");
  assert.equal(
    toReplacePayload(read.definition, roadmap, []),
    null,
    "a read that failed may not reach a write, because its applicable keys omit the visa materials",
  );
});

test("a body the mapper cannot walk takes the fallback and announces it", async () => {
  // The reviewer measured four shapes of the same body on the mount read — `tasks: [null]`,
  // `tasks: {}`, `tasks: 5` and `tasks: "pending"` — and the load-bearing half here is the `try` in
  // `readRoadmapDefinition`: the transport refuses these (see the loader's own test), but the mapping
  // is code, and wrapping the load alone meant a mapping throw escaped as a rejected promise. The
  // page's `.then` never ran, `definitionRead` stayed at `NO_DEFINITION_READ`, the six built-in phases
  // rendered with no notice, and the rejection appeared only in the browser console. The assertions
  // below are the two halves of the fix: the answer is the fallback with a notice, and the promise
  // resolves — a rejection would fail this test at the `await` rather than at an equality.
  for (const tasks of [[null], {}, 5, "pending"] as unknown[]) {
    const loader = async () => ({ ...SERVED, tasks } as ServedRoadmapDefinition);
    const read = await readRoadmapDefinition(loader);
    assert.equal(read.definition, null, `tasks ${JSON.stringify(tasks)} must not reach a definition`);
    assert.equal(read.notice, LOCAL_DEFINITION_NOTICE, "a fallback nobody announced is the silent bug");
    assert.equal(read.tasks, null, "no rows were read, so the rows on screen are kept");
  }

  // The same claim through the real transport rather than through a loader that answers a bad shape:
  // `fetchRoadmapDefinition` is what the page passes to this function, so the refusal and the
  // fallback have to meet in the middle. The stub is installed only for the call.
  const original = globalThis.fetch;
  globalThis.fetch = (async () =>
    new Response(JSON.stringify({ ...SERVED, tasks: [null] }), { status: 200 })) as typeof fetch;
  try {
    const read = await readRoadmapDefinition(fetchRoadmapDefinition);
    assert.equal(read.notice, LOCAL_DEFINITION_NOTICE, "a null row did not reach the notice");
    assert.equal(read.definition, null, "a null row produced a definition the builder would walk");
  } finally {
    globalThis.fetch = original;
  }
});

test("a served read is the only thing that gives the page a definition and its rows", async () => {
  const read = await readRoadmapDefinition(async () => SERVED);

  assert.equal(read.notice, null, "the fallback notice does not survive a successful read");
  assert.deepEqual(
    read.definition?.phases.map((phase) => phase.id),
    ["specialized", "visa"],
    "the served definition is what the page holds, visa phase and all",
  );
  // The rows arrive in the same response and are mapped to this side's column-style names at the edge;
  // the page reads the served definition and its own rows from one call, which is why they are one
  // answer here.
  assert.deepEqual(
    read.tasks?.map((row) => [row.material_key, row.schedule_origin, row.origin]),
    [["spe-cv", "suggested", "system"]],
  );

  const payload = toReplacePayload(
    read.definition,
    buildRoadmap(PROFILE, [], NOW, read.definition ?? DEFAULT_DEFINITION),
    read.tasks ?? [],
  );
  assert.ok(payload, "a definition that was read is what makes a write possible");
  assert.deepEqual(payload.applicableKeys.slice().sort(), ["spe-cv", "visa-gs"]);
});
