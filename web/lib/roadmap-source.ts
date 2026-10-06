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
 * `source` is carried because the wire carries it, and this interface is the honest description of a
 * response body: a material with no source row really does send `null`, and the two authored visa
 * materials really do send an object. Nothing here renders it yet — every date the roadmap shows is
 * still a system suggestion — and `SourceRef` is declared in `api/app/schemas/roadmap.py`, not on
 * this side, so naming its fields here would invent a contract the frontend does not read.
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
  source: unknown;
}

/** The whole definition, exactly as `GET /api/roadmap` serves it. */
export interface ServedRoadmapDefinition {
  phases: ServedPhase[];
  materials: ServedMaterial[];
}

/** One phase definition as `buildRoadmap` reads it, plus the wire's own name for the phase. */
export type PhaseDef = RoadmapDefinition["phases"][number] & { key: string };

/**
 * The served phases as the definitions `buildRoadmap` walks.
 *
 * `key` is kept on each returned definition so the caller can still name the wire identifier, and
 * `id` is added because that is what the builder and every caller of it use. Both hold the same
 * value; the duplication is the seam between the two vocabularies, not a second field to maintain.
 * A `subtitle` of `null` becomes `""`, which is how a phase without a description already renders:
 * `FlowView` puts `detail` in a paragraph, and the null would either print as "null" or need a check
 * at every render site.
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
