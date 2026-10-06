// Tests for the mapping from the served definition onto what `buildRoadmap` takes.
//
// The fixtures are written with the field names the route actually serves — `key`, `phase`, `title`,
// `detail`, `appliesTo`, `sortOrder`, `source` — copied from a live `GET /api/roadmap`. That detail is
// the point of this file. The first version of the adapter read `material.id` and `material.label`
// while the wire says `key` and `title`, and every test here passed, because the fixtures had been
// written to match the adapter instead of the server. Nothing type-checked the difference: both sides
// were declared in `roadmap-source.ts`, so the compiler was only ever comparing the adapter with its
// own wrong idea of the response. A served definition then rendered 33 empty material rows with a
// missing React key, and the only thing that noticed was the browser walkthrough's console check.
//
// The last test here is the one that closes that hole: it builds the wire shape *from the frontend
// constants* and asserts the mapping round-trips. It compares the adapter's output against the
// constants themselves rather than against a hand-written expectation, so a field name that stops
// matching the server has to fail here.

import assert from "node:assert/strict";
import test from "node:test";

import { DEFAULT_DEFINITION } from "./roadmap.ts";
import { toMaterialDefs, toPhaseDefs, toRoadmapDefinition } from "./roadmap-source.ts";
import type { ServedRoadmapDefinition } from "./roadmap-source.ts";

test("maps the served definition onto the shape buildRoadmap already takes", () => {
  const phases = toPhaseDefs({
    phases: [
      { key: "selection", title: "锁定申请组合", subtitle: null, offsetDays: 330, sortOrder: 0 },
      { key: "visa", title: "签证与行前", subtitle: null, offsetDays: 30, sortOrder: 6 },
    ],
    materials: [],
  });
  assert.equal(phases.length, 2);
  assert.equal(phases[0].key, "selection");
  assert.equal(phases[0].offsetDays, 330);
});

test("keeps the served order rather than sorting again", () => {
  const phases = toPhaseDefs({
    phases: [
      { key: "b", title: "b", subtitle: null, offsetDays: 10, sortOrder: 1 },
      { key: "a", title: "a", subtitle: null, offsetDays: 20, sortOrder: 0 },
    ],
    materials: [],
  });
  assert.deepEqual(
    phases.map((p) => p.key),
    ["b", "a"],
  );
});

// The builder names a phase `id` and renders it as a string; the wire names it `key`. Both are on the
// returned definition so the caller never has to know which vocabulary it is holding.
test("a served phase carries the wire key as both key and id", () => {
  const [phase] = toPhaseDefs({
    phases: [{ key: "visa", title: "签证与行前", subtitle: "行前安排。", offsetDays: 30, sortOrder: 6 }],
    materials: [],
  });
  assert.equal(phase.key, "visa");
  assert.equal(phase.id, "visa");
  // The wire's `subtitle` is the frontend's `detail`; the rename is the whole mapping for this field.
  assert.equal(phase.detail, "行前安排。");
});

test("a phase with no subtitle renders as an empty description, not as the word null", () => {
  // The authored visa phase really does serve `subtitle: null` (measured against the live route).
  const [phase] = toPhaseDefs({
    phases: [{ key: "visa", title: "签证与行前", subtitle: null, offsetDays: 30, sortOrder: 6 }],
    materials: [],
  });
  assert.equal(phase.detail, "");
});

// The wire field names, one material of each kind: two transcribed ones with no source, and one
// authored material that carries a source object.
const SERVED_MATERIALS: ServedRoadmapDefinition["materials"] = [
  {
    key: "sel-goal",
    phase: "selection",
    title: "明确目标国家与方向",
    detail: "结合预算、就业方向和家庭意见，先锁定国家与专业大类。",
    appliesTo: "all",
    sortOrder: 0,
    source: null,
  },
  {
    key: "spe-portfolio",
    phase: "specialized",
    title: "作品集",
    detail: "设计、建筑、艺术类专业需要。",
    appliesTo: "portfolio",
    sortOrder: 3,
    source: null,
  },
  {
    key: "visa-gs-responses",
    phase: "visa",
    title: "GS 问卷逐题作答",
    detail: "申请表中逐题作答，每题不超过 150 词，且必须使用英文。",
    appliesTo: "all",
    sortOrder: 0,
    source: {
      url: "https://immi.homeaffairs.gov.au/visas/getting-a-visa/visa-listing/student-500/genuine-student-requirement",
      title: "Genuine Student requirement",
      status: "待核验",
    },
  },
];

test("groups materials under their phase and renames key/title to id/label", () => {
  const materials = toMaterialDefs({
    phases: [],
    materials: [
      { ...SERVED_MATERIALS[0], key: "b-2", phase: "b", title: "b2", sortOrder: 1 },
      { ...SERVED_MATERIALS[0], key: "a-1", phase: "a", title: "a1", sortOrder: 0 },
      { ...SERVED_MATERIALS[0], key: "b-1", phase: "b", title: "b1", sortOrder: 0 },
    ],
  });
  assert.deepEqual(Object.keys(materials), ["b", "a"]);
  assert.deepEqual(
    materials.b.map((m) => m.id),
    ["b-2", "b-1"],
  );
  assert.equal(materials.b[0].label, "b2");
  assert.deepEqual(
    materials.a.map((m) => m.id),
    ["a-1"],
  );
});

test("a material keeps its applicability, and the wire's sortOrder is not carried", () => {
  const materials = toMaterialDefs({ phases: [], materials: SERVED_MATERIALS });
  assert.deepEqual(materials.specialized, [
    { id: "spe-portfolio", label: "作品集", detail: "设计、建筑、艺术类专业需要。", appliesTo: "portfolio" },
  ]);
  // The array position is the order, so `sortOrder` must not survive as a field of its own.
  assert.deepEqual(Object.keys(materials.specialized[0]).sort(), ["appliesTo", "detail", "id", "label"]);
});

// A sourceless material serves `source: null` and the authored visa materials serve an object.
// Nothing renders it yet, so the mapping must at least not choke on either shape.
test("a served source is carried past the mapping without being read", () => {
  const materials = toMaterialDefs({ phases: [], materials: SERVED_MATERIALS });
  assert.deepEqual(
    materials.visa.map((m) => m.id),
    ["visa-gs-responses"],
  );
});

// The foreign key makes this unreachable from the database, but a material whose phase the definition
// does not list must still be mapped somewhere rather than dropped: losing a requirement silently is
// the failure this product exists to avoid.
test("a material naming an unlisted phase is grouped, not discarded", () => {
  const materials = toMaterialDefs({
    phases: [],
    materials: [{ ...SERVED_MATERIALS[0], key: "x-1", phase: "unknown" }],
  });
  assert.deepEqual(
    materials.unknown.map((m) => m.id),
    ["x-1"],
  );
});

test("holds no definition of its own when the server sends nothing", () => {
  // An empty definition maps to an empty definition. Falling back to the constants is
  // `buildRoadmap`'s job, and duplicating it here would make the page's `catch` unreachable.
  assert.deepEqual(toPhaseDefs({ phases: [], materials: [] }), []);
  assert.deepEqual(toMaterialDefs({ phases: [], materials: [] }), {});
});

// The two halves are the same mapping, so the page can hold one object instead of two.
test("joins the two halves into the single definition buildRoadmap takes", () => {
  const definition = toRoadmapDefinition({
    phases: [{ key: "selection", title: "锁定申请组合", subtitle: null, offsetDays: 330, sortOrder: 0 }],
    materials: [SERVED_MATERIALS[0]],
  });
  assert.equal(definition.phases.length, 1);
  assert.equal(definition.phases[0].id, "selection");
  assert.deepEqual(
    definition.materials.selection.map((m) => m.id),
    ["sel-goal"],
  );
});

/**
 * The served shape rebuilt from the frontend constants: phases renamed `id` → `key` and `detail` →
 * `subtitle`, materials renamed `id` → `key` and `label` → `title`, each material carrying the phase
 * key its array came from and its array index as `sortOrder`.
 *
 * This is the same translation `scripts/verify-roadmap-mirror.cjs` and `api/app/seed_roadmap.py`
 * perform, re-derived here from the constants rather than copied from the server, so the comparison in
 * the test below is between two independent spellings of the same data.
 */
function servedFromConstants(): ServedRoadmapDefinition {
  const phases = DEFAULT_DEFINITION.phases.map((phase, index) => ({
    key: phase.id,
    title: phase.title,
    subtitle: phase.detail,
    offsetDays: phase.offsetDays,
    sortOrder: index,
  }));
  const materials: ServedRoadmapDefinition["materials"] = [];
  for (const [phaseKey, items] of Object.entries(DEFAULT_DEFINITION.materials)) {
    items.forEach((item, index) => {
      materials.push({
        key: item.id,
        phase: phaseKey,
        title: item.label,
        detail: item.detail,
        appliesTo: item.appliesTo,
        sortOrder: index,
        source: null,
      });
    });
  }
  return { phases, materials };
}

test("the mapping round-trips the constants through the served field names", () => {
  // The shape of the response is the one thing this module can get wrong without a type error, so it
  // is asserted against the constants rather than against a fixture. Reading `material.id` and
  // `material.label` — the mistake this file was rewritten for — leaves every id and label undefined
  // here, because the items this function builds carry `key` and `title` and nothing else.
  const served = servedFromConstants();
  const definition = toRoadmapDefinition(served);

  assert.deepEqual(
    definition.phases.map((p) => p.id),
    DEFAULT_DEFINITION.phases.map((p) => p.id),
  );
  assert.deepEqual(
    definition.phases.map((p) => p.title),
    DEFAULT_DEFINITION.phases.map((p) => p.title),
  );
  assert.deepEqual(
    definition.phases.map((p) => p.detail),
    DEFAULT_DEFINITION.phases.map((p) => p.detail),
  );
  assert.deepEqual(
    definition.phases.map((p) => p.offsetDays),
    DEFAULT_DEFINITION.phases.map((p) => p.offsetDays),
  );

  // Every material, compared field by field against the constant it came from. A wrong field name on
  // either side fails here rather than producing a plausible looking but empty row.
  const servedMaterials = toMaterialDefs(served);
  for (const [phaseKey, items] of Object.entries(DEFAULT_DEFINITION.materials)) {
    assert.deepEqual(servedMaterials[phaseKey], items, `materials of ${phaseKey}`);
  }
  const empty = Object.values(servedMaterials)
    .flat()
    .filter((m) => m.label === undefined || m.id === undefined);
  assert.equal(empty.length, 0, "no material may reach the builder without its id and label");
});
