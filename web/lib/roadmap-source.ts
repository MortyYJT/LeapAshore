// Maps the served roadmap definition onto the shape `web/lib/roadmap.ts` already builds from.
//
// Only the names and the nesting change here: the server sends phases and a flat material list keyed
// by phase, while `buildRoadmap` takes per-phase definitions and a material list per phase. The
// values themselves — titles, details, offsets, applicability — are copied through untouched.
//
// The ordering is not touched either. The server orders phases by the timeline and materials by
// `(phase order, material sort_order)`, so sorting again here would be a second rule that can
// disagree with the first, and the disagreement would be invisible: both orders come from the same
// data, so a re-sort only shows up once the two rules drift. `toPhaseDefs` keeps the array it is
// given, and `toMaterialDefs` groups materials by phase without moving them within a group.
//
// The field names below are the ones the route actually serves, copied from a live response:
//
//   {"key":"sel-goal","phase":"selection","title":"明确目标国家与方向","detail":"…",
//    "appliesTo":"all","sortOrder":0,"source":null}
//
// They are also exported so a test can build the served shape from the frontend constants and check
// that the mapping round-trips. That test exists because getting these names wrong is not a
// type error anywhere in this file: it produced a roadmap that rendered every material as an empty
// row with a missing key, and the only reason it was caught is that the browser walkthrough reports
// console errors. Inferring the names from what the builder wants, rather than from the wire, is the
// mistake this header is here to prevent.
//
// That round-trip test builds its input from the constants and the adapter in this same file, so it
// only catches a name that one of the two halves changed on its own. The binding to the server's
// spelling is `web/lib/roadmap-response.fixture.json` — a captured `GET /api/roadmap` body — which
// `roadmap-source.test.ts` maps and compares field by field.

import type { TaskRow } from "./roadmap-sync";
import type { RoadmapDefinition, MaterialItem } from "./types";

/** One phase as it arrives over the wire, in the camelCase the API serialises. */
export interface ServedPhase {
  /** The phase key. `buildRoadmap` calls it `id`; the wire calls it `key`. */
  key: string;
  title: string;
  /** The phase's description. `null` when the phase has none, as the authored visa phase does. */
  subtitle: string | null;
  /** Days before the intake date, counted backwards. */
  offsetDays: number;
  sortOrder: number;
}

/**
 * One material as it arrives over the wire.
 *
 * The response also carries `source` — `null` for a transcribed material and an object for the two
 * authored visa ones — and it is deliberately not declared here. Nothing on this side reads it, every
 * date the roadmap shows is still a system suggestion, and `SourceRef` is declared in
 * `api/app/schemas/roadmap.py` rather than on this side, so a field naming it would describe a
 * contract this module does not have. The captured fixture keeps the byte of the response that says
 * it is there.
 */
export interface ServedMaterial {
  /** The material key, which is `MaterialItem["id"]` on this side. */
  key: string;
  /** The phase key this material belongs to. */
  phase: string;
  /** The material's name, which is `MaterialItem["label"]` on this side. */
  title: string;
  detail: string;
  appliesTo?: MaterialItem["appliesTo"];
  sortOrder: number;
}

/**
 * One task row as it arrives over the wire.
 *
 * Every field here is camelCase, because that is what the route serves: `TaskOut` carries the same
 * `alias_generator` the rest of the API's schemas do, so `material_key` leaves as `materialKey`.
 * Assuming otherwise is not a type error anywhere — the mapping above only reads `phase` and `key`,
 * which are single words — and it is silent at runtime: `rowsRef.current.find((row) => row.material_key
 * === materialId)` simply never matches, so every tick returned early and the checkbox flipped back.
 * Measured in a browser against the running server: a click on a material produced no `PATCH` at all.
 * `web/lib/api.test.ts` captures the row with these names, and `roadmap-response.fixture.json` is the
 * body this declaration is a claim about.
 */
export interface ServedTask {
  id: string;
  materialKey: string;
  programId: string;
  phase: string;
  status: string;
  suggestedAt: string | null;
  dueAt: string | null;
  scheduleOrigin: string;
  origin: string;
  documentId: string | null;
  completedAt: string | null;
  createdAt: string;
  updatedAt: string;
}

/**
 * The wire's task rows as this side's `TaskRow`, which names its fields the way the database columns
 * do.
 *
 * The renaming happens here, at the edge, rather than inside the payload rule, for the same reason the
 * definition is mapped in this file: `toReplacePayload` is a pure function about who owns a row, and
 * it should not also have to know which spelling the transport chose. The two enum columns are
 * narrowed rather than passed through, so a value outside the three the rule understands cannot be
 * read as an owner it does not have.
 */
export function toTaskRows(served: ServedTask[] | undefined): TaskRow[] {
  return (served ?? []).map((task) => ({
    id: task.id,
    material_key: task.materialKey,
    program_id: task.programId,
    phase: task.phase,
    status: task.status,
    suggested_at: task.suggestedAt,
    due_at: task.dueAt,
    schedule_origin: task.scheduleOrigin as TaskRow["schedule_origin"],
    origin: task.origin as TaskRow["origin"],
    completed_at: task.completedAt,
  }));
}

/**
 * The whole definition, exactly as `GET /api/roadmap` serves it.
 *
 * `tasks` is not part of the definition and is mapped by `toTaskRows` rather than by anything the
 * roadmap builder reads: it is the caller's own half of the same response, so `toRoadmapDefinition` is
 * given a body that carries it and ignores it.
 */
export interface ServedRoadmapDefinition {
  phases: ServedPhase[];
  materials: ServedMaterial[];
  tasks?: ServedTask[];
}

/**
 * One phase definition as `buildRoadmap` reads it, plus the wire's own name for the phase.
 *
 * `key` and `id` always hold the same string, and the duplication is kept on purpose: the brief's
 * acceptance test for this mapper reads `phases[0].key`, because that is the name the wire uses,
 * while `buildRoadmap` and every caller of it read `id`. Dropping either one means editing a test this
 * fix round was told not to touch, or changing what the builder walks, so the seam stays where the
 * two vocabularies meet and `toPhaseDefs` writes both from the single served value.
 */
export type PhaseDef = RoadmapDefinition["phases"][number] & { key: string };

/**
 * The served phases as the definitions `buildRoadmap` walks.
 *
 * `id` is added alongside the wire's `key` (see `PhaseDef`). A `subtitle` of `null` becomes `""`,
 * which is how a phase without a description already renders: `FlowView` puts `detail` in a
 * paragraph, and the null would either print as "null" or need a check at every render site.
 */
export function toPhaseDefs(definition: ServedRoadmapDefinition): PhaseDef[] {
  return definition.phases.map((phase) => ({
    key: phase.key,
    id: phase.key,
    title: phase.title,
    detail: phase.subtitle ?? "",
    offsetDays: phase.offsetDays,
  }));
}

/**
 * The served materials grouped by phase, in the order they arrived.
 *
 * `id` and `label` are this side's names for the wire's `key` and `title`. `sortOrder` is dropped
 * rather than carried: the array position within the group is the order, and keeping a second copy of
 * it would leave two answers to the same question. A material naming a phase that is not in the
 * definition still lands in its own group instead of being discarded — nothing renders that group
 * unless a phase claims it, and silently dropping a requirement would be the worse of the two.
 */
export function toMaterialDefs(definition: ServedRoadmapDefinition): Record<string, MaterialItem[]> {
  const byPhase: Record<string, MaterialItem[]> = {};
  for (const material of definition.materials) {
    const item: MaterialItem = {
      id: material.key,
      label: material.title,
      detail: material.detail,
      appliesTo: material.appliesTo,
    };
    (byPhase[material.phase] ??= []).push(item);
  }
  return byPhase;
}

/** Both halves of the mapping, for the one call the page makes on mount. */
export function toRoadmapDefinition(definition: ServedRoadmapDefinition): RoadmapDefinition {
  return { phases: toPhaseDefs(definition), materials: toMaterialDefs(definition) };
}
