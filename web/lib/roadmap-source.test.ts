// Tests for the mapping from the served definition onto what `buildRoadmap` takes.
//
// The fixtures are written with the field names the route actually serves — `key`, `phase`, `title`,
// `detail`, `appliesTo`, `sortOrder` — taken from a live `GET /api/roadmap`. That detail is the point
// of this file. The first version of the adapter read `material.id` and `material.label` while the
// wire says `key` and `title`, and every test here passed, because the fixtures had been written to
// match the adapter instead of the server. Nothing type-checked the difference: both sides were
// declared in `roadmap-source.ts`, so the compiler was only ever comparing the adapter with its own
// wrong idea of the response. A served definition then rendered 33 empty material rows with a missing
// React key, and the only thing that noticed was the browser walkthrough's console check.
//
// Two tests here bind the mapping in different ways, and they are not interchangeable:
//
// - `the adapter reads the field names of a captured response body` maps
//   `roadmap-response.fixture.json`, a captured `GET /api/roadmap` body, so the names under test come
//   from the server. This is the binding that cannot be satisfied by agreeing with itself.
// - `the mapping round-trips the constants through the served field names` builds the wire shape from
//   `DEFAULT_DEFINITION` *and the served names in this file*. It catches a rename applied to one half
//   only — it does fail on the original defect — but if the constants' translation above and the
//   adapter below drift together, it stays green. It is a change detector for this file, not proof of
//   what the route sends, and the comment on it says so.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { DEFAULT_DEFINITION } from "./roadmap.ts";
import { toMaterialDefs, toPhaseDefs, toRoadmapDefinition, toTaskRows } from "./roadmap-source.ts";
import type { ServedMaterial, ServedRoadmapDefinition, ServedTask } from "./roadmap-source.ts";

/**
 * A `GET /api/roadmap` body captured from the running server, read here as the wire record it is.
 *
 * The file is `roadmap-response.fixture.json`; its `$comment` names the command that produced it. It
 * is not written by hand and must not be edited by hand — its value is that the names inside it were
 * not chosen by this repository. Every other fixture in this file is typed out against the
 * declarations in `roadmap-source.ts`, so those tests and the adapter they test can only ever
 * disagree with each other; the tests that use this object compare the adapter with the server.
 * When the route's shape changes on purpose, recapture the file rather than adapting it.
 */
const CAPTURED_RESPONSE: ServedRoadmapDefinition = (
  JSON.parse(readFileSync(new URL("./roadmap-response.fixture.json", import.meta.url), "utf8")) as {
    response: ServedRoadmapDefinition;
  }
).response;

/** Read a field the capture carries but this side does not declare, without typing it into the module. */
function wireField(material: ServedMaterial, field: string): unknown {
  return (material as unknown as Record<string, unknown>)[field];
}

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

// The wire field names, one material per phase, typed out against the declarations above. The capture
// at the top of this file is what keeps those declarations honest; these three are here because a test
// that names its own input can say exactly which phase key, applicability and order it means.
const SERVED_MATERIALS: ServedRoadmapDefinition["materials"] = [
  {
    key: "sel-goal",
    phase: "selection",
    title: "明确目标国家与方向",
    detail: "结合预算、就业方向和家庭意见，先锁定国家与专业大类。",
    appliesTo: "all",
    sortOrder: 0,
  },
  {
    key: "spe-portfolio",
    phase: "specialized",
    title: "作品集",
    detail: "设计、建筑、艺术类专业需要。",
    appliesTo: "portfolio",
    sortOrder: 3,
  },
  {
    key: "visa-gs-responses",
    phase: "visa",
    title: "GS 问卷逐题作答",
    detail: "申请表中逐题作答，每题不超过 150 词，且必须使用英文。",
    appliesTo: "all",
    sortOrder: 0,
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

// The route sends more than this module reads: every material also carries `source`, which
// `ServedMaterial` deliberately does not declare, because nothing on this side consumes it. Leaving a
// field out of the interface is a statement about this file, not about the route, so the mapping is
// checked on a body that still carries it.
test("a wire field this side does not model is ignored rather than fatal", () => {
  const sourced = CAPTURED_RESPONSE.materials.filter((material) => wireField(material, "source") != null);
  assert.ok(sourced.length > 0, "the captured body carries a material with a source");
  const materials = toMaterialDefs(CAPTURED_RESPONSE);
  for (const material of sourced) {
    const item = materials[material.phase].find((m) => m.id === material.key);
    assert.equal(item?.label, material.title, `material ${material.key}`);
  }
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
 * perform, re-derived here from the constants. What it is *not* is an independent record of the
 * server: it and `toPhaseDefs`/`toMaterialDefs` are two spellings of the same guess, written in the
 * same file, so a rename applied to both leaves the test below green. Only the captured body above
 * breaks that symmetry.
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
      });
    });
  }
  return { phases, materials };
}

test("the adapter reads the field names of a captured response body", () => {
  // The binding the round-trip test below cannot provide. The expectations are derived from the
  // capture, so they are the server's words and not this file's: reading `material.id` and
  // `material.label` — the defect this module was rewritten for — leaves every id and label undefined
  // on the 33 served materials. A wrong phase field name fails the phase comparison the same way.
  assert.ok(CAPTURED_RESPONSE.phases.length > 0, "the capture must carry phases");

  const definition = toRoadmapDefinition(CAPTURED_RESPONSE);
  assert.deepEqual(
    definition.phases,
    CAPTURED_RESPONSE.phases.map((phase) => ({
      key: phase.key,
      id: phase.key,
      title: phase.title,
      detail: phase.subtitle ?? "",
      offsetDays: phase.offsetDays,
    })),
    "every served phase, mapped field by field",
  );

  const materials = toMaterialDefs(CAPTURED_RESPONSE);
  for (const material of CAPTURED_RESPONSE.materials) {
    assert.deepEqual(
      materials[material.phase].find((m) => m.id === material.key),
      {
        id: material.key,
        label: material.title,
        detail: material.detail,
        appliesTo: material.appliesTo,
      },
      `material ${material.key}`,
    );
  }
  assert.equal(Object.values(materials).flat().length, CAPTURED_RESPONSE.materials.length);

  // The capture has to stay a record of the server's spelling. These two lines are what notice if it
  // is ever regenerated from the declarations in `roadmap-source.ts` instead of recaptured.
  const firstMaterial = CAPTURED_RESPONSE.materials[0] as unknown as Record<string, unknown>;
  assert.equal("key" in firstMaterial && "title" in firstMaterial, true);
  assert.equal("id" in firstMaterial || "label" in firstMaterial, false);
});

// One task row, in the spelling `GET /api/roadmap` serves under `tasks`. Every name below was read off
// a live response body; none of them is the database's own spelling, because `TaskOut` carries the same
// `alias_generator` as the rest of the API's schemas.
const SERVED_TASK: ServedTask = {
  id: "0f0f0f0f-0000-0000-0000-000000000000",
  materialKey: "aca-transcript",
  programId: "",
  phase: "academic",
  status: "pending",
  suggestedAt: null,
  dueAt: "2026-05-21",
  scheduleOrigin: "suggested",
  origin: "system",
  documentId: null,
  completedAt: null,
  createdAt: "2026-10-07T12:41:51.352633Z",
  updatedAt: "2026-10-07T12:41:51.352633Z",
};

test("maps a served task row from the wire's camelCase to the names the payload rule reads", () => {
  // The defect this pins, measured in a browser before it was fixed: `roadmap-sync.ts` looked a row up
  // by `row.material_key`, the wire names it `materialKey`, and nothing failed loudly — every lookup
  // missed, so `toggleMaterial` returned early, no `PATCH` was sent, and the checkbox flipped straight
  // back. No type error, no console error, no failing test: the mapping had simply never been bound to
  // the route. `TaskRow` names its fields after the columns, which is what the pure payload rule is
  // written against, so the rename has to happen here and this is the test that holds it.
  const [row] = toTaskRows([SERVED_TASK]);
  assert.deepEqual(row, {
    id: SERVED_TASK.id,
    material_key: "aca-transcript",
    program_id: "",
    phase: "academic",
    status: "pending",
    suggested_at: null,
    due_at: "2026-05-21",
    schedule_origin: "suggested",
    origin: "system",
    completed_at: null,
  });
});

test("a response with no tasks is an empty row list, not a crash", () => {
  // The route always serves the key, but a subject created before M2b could answer without it, and an
  // older build's captured body does not carry it either. Both mean the same thing: no rows yet.
  assert.deepEqual(toTaskRows(undefined), []);
  assert.deepEqual(toTaskRows([]), []);
});

test("the task adapter reads the field names of a captured response body", () => {
  // The binding the constant above cannot provide, for the reason this file's header records: a
  // constant typed out against `ServedTask` and an adapter written from the same declaration are two
  // spellings of one guess, and a wire name both halves got wrong keeps every one of those tests
  // green. `roadmap-response.fixture.json` now carries the `tasks` array of a real `GET /api/roadmap`,
  // captured after a `PUT` wrote two rows and a `PATCH` claimed one, so the names below are the
  // server's and the two `origin` values are both present in the data.
  const captured = CAPTURED_RESPONSE.tasks ?? [];
  assert.ok(captured.length > 0, "the capture must carry the caller's own task rows");

  // Field by field, with the wire's names spelled out as literals rather than read through
  // `ServedTask`. Reading the expectation through the declaration is exactly what would let a renamed
  // declaration agree with an adapter renamed the same way: both sides would produce `undefined`, and
  // `undefined` equals `undefined`.
  const expected = captured.map((task) => {
    const wire = task as unknown as Record<string, unknown>;
    return {
      id: wire["id"],
      material_key: wire["materialKey"],
      program_id: wire["programId"],
      phase: wire["phase"],
      status: wire["status"],
      suggested_at: wire["suggestedAt"],
      due_at: wire["dueAt"],
      schedule_origin: wire["scheduleOrigin"],
      origin: wire["origin"],
      completed_at: wire["completedAt"],
    };
  });
  assert.deepEqual(toTaskRows(captured), expected);

  // The capture has to stay a record of the server's spelling, the same way the material test above
  // keeps its own. These two lines are what notice if it is ever regenerated from the declarations
  // instead of recaptured.
  const firstWire = captured[0] as unknown as Record<string, unknown>;
  assert.equal(
    "materialKey" in firstWire && "scheduleOrigin" in firstWire && "completedAt" in firstWire,
    true,
  );
  assert.equal(
    "material_key" in firstWire || "schedule_origin" in firstWire || "completed_at" in firstWire,
    false,
  );

  // The values that make the mapping worth binding: both ownership values and both completion states
  // are in the capture, so a wrong `origin` or `completedAt` reading fails on a real row rather than
  // on a row this file invented.
  assert.deepEqual([...new Set(captured.map((task) => task.origin))].sort(), ["system", "user"]);
  assert.equal(captured.some((task) => task.completedAt !== null), true, "one row is completed");
  assert.equal(captured.some((task) => task.completedAt === null), true, "one row is not");
});

test("the mapping round-trips the constants through the served field names", () => {
  // What this checks: a served name that one half of the file changed on its own. It is a change
  // detector for this file, not evidence about the route — `servedFromConstants` above and the
  // adapter are the same guess written twice, so drifting both together keeps it green. The captured
  // body in the test above is the check that cannot agree with itself, and it fails on the same
  // defect independently.
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
