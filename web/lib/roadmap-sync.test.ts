// Tests for the recomputation payload: the pure rule that decides what may be written back to
// `PUT /api/roadmap/tasks`, and what may not.
//
// The function under test takes no network and holds no state, so the three claims the design makes
// about a write are pinned here rather than in a browser. `note/superpowers/specs/2026-10-06-stage-2-m2-design.md`
// section 3.8 is the reason two of them exist:
//
// - the applicable keys travel **separately** from the rows, because "this key no longer applies" and
//   "this payload does not carry this key" are different claims, and a server that read the second as
//   the first would delete the visa rows whenever the fallback definition was the one in hand;
// - a definition that came from the built-in fallback therefore produces **no write at all**, and the
//   "do not write" answer is `null` rather than an empty payload, so a caller cannot mistake it for a
//   real one that happens to compute nothing;
// - a row the applicant or the advisor owns is never offered for rewriting, not even as an unchanged
//   copy: the recomputation's own contract is that it may only replace the rows it generated.
//
// The roadmap below is built by `buildRoadmap` itself rather than written out by hand, so the fixture
// cannot disagree with the builder about what a computed roadmap looks like.

import { test } from "node:test";
import assert from "node:assert/strict";

import { buildRoadmap, DEFAULT_DEFINITION } from "./roadmap.ts";
import { toReplacePayload } from "./roadmap-sync.ts";
import type { TaskRow } from "./roadmap-sync.ts";
import type { Profile, Roadmap, RoadmapDefinition } from "./types.ts";

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

/**
 * A definition with the two shapes the applicability filter exists for: a `specialized` phase whose
 * second material is a research-plan row the profile does not qualify for, and a phase the builder
 * renders.
 *
 * `spe-research` is deliberately in the definition and out of the roadmap: that is what makes the
 * applicable-key claim testable. A payload that listed every material the definition carries would
 * list it too, and the server would keep a row no one can render.
 */
const DEFINITION: RoadmapDefinition = {
  phases: [
    { id: "specialized", title: "专项申请材料", detail: "", offsetDays: 210 },
    { id: "visa", title: "签证与行前", detail: "", offsetDays: 30 },
  ],
  materials: {
    specialized: [
      { id: "spe-cv", label: "学术简历（CV）", detail: "一页为主。", appliesTo: "all" },
      { id: "spe-research", label: "研究计划", detail: "研究型才需要。", appliesTo: "research" },
    ],
    visa: [{ id: "visa-gs", label: "GS 陈述", detail: "签证材料。", appliesTo: "all" }],
  },
};

const NOW = new Date("2026-10-06T00:00:00Z");

function computedRoadmap(definition: RoadmapDefinition = DEFINITION): Roadmap {
  return buildRoadmap(PROFILE, [], NOW, definition);
}

/** One served task row, with the fields this module reads. */
function row(overrides: Partial<TaskRow> & Pick<TaskRow, "material_key" | "origin">): TaskRow {
  return {
    id: "task-1",
    program_id: "",
    phase: "specialized",
    status: "pending",
    schedule_origin: "suggested",
    suggested_at: null,
    due_at: "2026-06-09",
    completed_at: null,
    ...overrides,
  };
}

test("states every applicable key explicitly, so the server can tell absent from inapplicable", () => {
  // Design section 3.8 is the reason this function exists.
  //
  // Two claims have to be separable on the wire, and the payload carries both as different things:
  // `applicableKeys` names the materials the profile qualifies for this round, while `rows` carries
  // only the computed dates. `spe-research` applies to research degrees and this profile is a taught
  // master's, so it is absent from the keys — the server reads that as "no longer applicable" and may
  // remove a system row for it. A key the server holds and this payload does not mention at all is a
  // different thing the server cannot express from the rows alone, which is why the keys are here.
  const payload = toReplacePayload(DEFINITION, computedRoadmap(), []);
  assert.ok(payload, "a definition that was served is what makes a write possible");
  assert.deepEqual(payload.applicableKeys.slice().sort(), ["spe-cv", "visa-gs"]);
  assert.equal(payload.applicableKeys.includes("spe-research"), false);

  // The other direction is not merely allowed, it is the normal case: a key that is applicable and
  // has no row of its own is stated in the keys and nowhere else. `rows` is deliberately not padded
  // out to match, because sending a row for a key the caller did not compute would be a claim about
  // dates it never derived.
  const keysFromRows = new Set(payload.rows.map((task) => task.materialKey));
  assert.equal(keysFromRows.size, payload.rows.length, "no material may be sent twice");
  assert.deepEqual([...keysFromRows].sort(), ["spe-cv", "visa-gs"]);
});

test("sends no rows and no applicable keys when the definition came from the fallback", () => {
  // A fallback definition is a subset; writing from it would delete the visa tasks.
  //
  // `DEFAULT_DEFINITION` deliberately carries no `visa` phase, so a recomputation driven by it would
  // state an applicable-key set without `visa-gs` in it. The server would then delete the applicant's
  // visa system rows as no longer applicable, and the next run with the real definition would
  // recreate them as `pending` — losing `status` and `completed_at`, which is the exact loss the
  // `origin` rule exists to prevent. The decision is therefore made here, once, rather than being
  // left to a caller to remember: a definition this client did not read from the server never
  // produces a payload.
  //
  // The gate is a `null` definition rather than a comparison against `DEFAULT_DEFINITION`, because
  // there is exactly one way to hold a definition and that is to have read it. The page keeps the
  // served definition in state and leaves it `null` when the read failed; the fallback is what
  // `buildRoadmap` uses from its own default argument, so it never has to be named here, and a copy
  // of the constants a future build adds could not be mistaken for a served one.
  const roadmap = computedRoadmap(DEFAULT_DEFINITION);
  assert.ok(roadmap.phases.length > 0, "the fallback still builds a roadmap; it is only unwritable");
  assert.equal(toReplacePayload(null, roadmap, []), null, "no definition read means no write");
  // `null` rather than `{ applicableKeys: [], rows: [] }`: an empty payload is a caller's statement
  // that nothing applies, and it is the same shape a real recomputation of an empty roadmap would
  // have. A caller that lost the distinction would delete every system row in one request.
  assert.notDeepEqual(toReplacePayload(null, roadmap, []), { applicableKeys: [], rows: [] });
});

test("never sends a task the user or the advisor owns", () => {
  // The client must not even offer to rewrite them.
  //
  // A row whose `origin` is not `system` is not the recomputation's to change, and the server refuses
  // to touch it even when the payload carries it. Sending it anyway would mean the client's payload
  // disagreed with the rule the server enforces, and the disagreement would only be visible as a
  // count the caller did not expect — so the ownership test happens here, on the way out. The rows
  // below name the same material as the computed ones, which is the case where a payload built from
  // the roadmap alone would silently include them.
  const tasks = [
    row({ id: "mine", material_key: "spe-cv", origin: "user", status: "completed" }),
    row({ id: "ours", material_key: "visa-gs", origin: "system" }),
    // An advisor's row for a material this client does not compute at all: it owns neither the
    // roadmap entry nor a slot in the payload.
    row({ id: "theirs", material_key: "spe-research", origin: "agent" }),
  ];
  const payload = toReplacePayload(DEFINITION, computedRoadmap(), tasks);
  assert.ok(payload);
  assert.deepEqual(
    payload.rows.map((task) => task.materialKey),
    ["visa-gs"],
    "only the row the recomputation owns is offered",
  );
  // The assertion that matters: every row the payload offers is a material whose served row is
  // `system` or absent. Nothing here is a claim about a row a human owns.
  const owned = new Set(tasks.filter((t) => t.origin !== "system").map((t) => t.material_key));
  for (const task of payload.rows) {
    assert.equal(
      owned.has(task.materialKey),
      false,
      `${task.materialKey} is owned by a human or the advisor and must not be offered`,
    );
  }
  // And a user-owned row does not remove its key from `applicableKeys`: the material is still one the
  // applicant has to prepare, so the key stays applicable even though the row is not ours to write.
  assert.ok(payload.applicableKeys.includes("spe-cv"));
});

test("the rows carry the phase and the due date the builder computed", () => {
  // The wire names, not this side's: the route reads `materialKey`, `phase`, `dueAt` and
  // `scheduleOrigin`, and the phase has to be one the definition serves or the service answers 422.
  // The date is the one `buildRoadmap` derived from the intake — the client owns that arithmetic by
  // design and this payload is how the result reaches the server.
  const roadmap = computedRoadmap();
  const payload = toReplacePayload(DEFINITION, roadmap, []);
  assert.ok(payload);
  const cv = payload.rows.find((task) => task.materialKey === "spe-cv");
  assert.ok(cv, "the computed roadmap carries the CV row");
  assert.equal(cv.phase, "specialized");
  assert.equal(cv.programId, "");
  assert.equal(cv.dueAt, roadmap.phases[0].tasks[0].dueAt);
  assert.equal(cv.scheduleOrigin, "suggested");
});
