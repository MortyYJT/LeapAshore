// The recomputation's write rule: what the client is allowed to offer the server, and when it is
// allowed to offer anything at all.
//
// `buildRoadmap` computes the timeline from the profile and the definition; this module turns that
// result into the body of `PUT /api/roadmap/tasks`. It is a pure function on purpose: the rule it
// encodes has two ways of losing the applicant's data, and both are decidable from its arguments
// alone, so they are settled in unit tests rather than in a browser.
//
// The `origin` rule (`api/app/services/roadmap_tasks.py`) says a recomputation may replace only the
// rows the client itself generated. The server enforces it; this side is where offering the wrong
// rows is prevented, because a payload that disagrees with the rule is a bug that would otherwise
// show up as a count nobody expected.
//
// The second rule is section 3.8 of `note/superpowers/specs/2026-10-06-stage-2-m2-design.md`. The
// built-in `DEFAULT_DEFINITION` in `roadmap.ts` deliberately omits the visa phase — it is the copy
// for a page that cannot reach the server, not a second version of the truth. A recomputation driven
// by it computes zero visa materials, so it would state an applicable-key set without the visa keys
// in it, the server would read that as "no longer applicable" and delete the visa system rows, and
// the next run with the real definition would recreate them as `pending`. The applicant's `status`
// and `completed_at` would be gone, which is the exact loss the `origin` rule exists to prevent.
//
// So the payload is only ever built from a definition that was read from the server:
//
// - a definition the page did not read produces **no write**, and the answer is `null` rather than an
//   empty payload, so a caller cannot mistake "do not write" for "write nothing" — the second is a
//   real statement that nothing applies this round, and it would delete every system row in one
//   request. The gate is spelled as a `null` definition rather than as a comparison against
//   `DEFAULT_DEFINITION`, because there is exactly one way to hold a definition and that is to have
//   read it: the page keeps the served definition in state and leaves it `null` when the read failed,
//   so the built-in copy is what `buildRoadmap` falls back to through its own default argument and is
//   never a value this function has to recognise;
// - `applicableKeys` travels **separately** from `rows`, because "this key is no longer applicable"
//   and "this payload does not carry this key" are different claims. The keys are the materials the
//   current profile qualifies for, taken from the roadmap that was just computed, so a material the
//   profile does not apply to is absent from the keys and only from the keys;
// - a material whose served row is owned by the applicant or the advisor is still listed as
//   applicable — they have to prepare it — but no row is sent for it. The row's dates and status
//   belong to whoever owns it now.

import type { PhaseTask, Roadmap, RoadmapDefinition } from "./types";

/** One served task row, as the route names its fields on this side of the adapter. */
export interface TaskRow {
  id: string;
  material_key: string;
  program_id: string;
  phase: string;
  status: string;
  suggested_at: string | null;
  due_at: string | null;
  /**
   * Where the row's dates came from. `suggested` and `official` are the server's two stored values;
   * `user` is the third this side's `PhaseTask` names for a date the applicant set by hand.
   */
  schedule_origin: "suggested" | "official" | "user";
  /**
   * Who owns the row. `system` is a row a recomputation wrote and may therefore replace; `user` is
   * one the applicant edited and `agent` one the advisor wrote, and neither is ever offered back.
   */
  origin: "system" | "user" | "agent";
  completed_at: string | null;
}

/** One row of `PUT /api/roadmap/tasks`, in the camelCase the route serialises. */
export interface TaskReplaceRow {
  materialKey: string;
  /** The empty string, which is the value the column and its uniqueness constraint use. */
  programId: string;
  phase: string;
  dueAt: string | null;
  scheduleOrigin: "suggested" | "official" | "user";
}

/** The whole replacement body: the applicable key set, and the rows computed for it. */
export interface TaskReplacePayload {
  applicableKeys: string[];
  rows: TaskReplaceRow[];
}

/**
 * What one replacement did, as `TaskReplaceResult` serves it.
 *
 * The four counts are disjoint: `created` and `updated` are the rows this call wrote, `removed` the
 * system rows it deleted, and `kept` every existing row it left exactly as it was. The caller knows
 * what it sent, so the counts are not an account of the request — they are the server's own statement
 * about the rows the caller does not own, which is the half it cannot compute.
 */
export interface TaskReplaceResult {
  created: number;
  updated: number;
  removed: number;
  kept: number;
}

/**
 * The body of the recomputation, or `null` for "do not write at all".
 *
 * `definition` is the served definition the roadmap was built from, or `null` when the page built it
 * from the built-in copy; see the header. `definitions` from the fallback return `null` before
 * anything else is looked at, so a caller cannot reach a payload by forgetting the gate.
 */
export function toReplacePayload(
  definition: RoadmapDefinition | null,
  roadmap: Roadmap,
  tasks: TaskRow[],
): TaskReplacePayload | null {
  if (definition === null) return null;

  // The roadmap is what the profile qualifies for this round, so its material ids are the applicable
  // keys. Reading them off `definition.materials` instead would state that a material the profile
  // filters out still applies, which is the claim the server deletes rows on.
  const applicableKeys: string[] = [];
  const rows: TaskReplaceRow[] = [];
  const seen = new Set<string>();
  const owned = new Set(
    tasks.filter((task) => task.origin !== "system").map((task) => task.material_key),
  );

  for (const phase of roadmap.phases) {
    for (const task of phase.tasks) {
      if (seen.has(task.materialId)) continue;
      seen.add(task.materialId);
      applicableKeys.push(task.materialId);
      // Not offered: a row the applicant or the advisor owns. It is not even sent unchanged, because
      // sending it would be this payload's claim about a row it does not own, and the server would
      // have to refuse it.
      if (owned.has(task.materialId)) continue;
      rows.push(toRow(task, phase.id));
    }
  }

  return { applicableKeys, rows };
}

/**
 * One computed task as the route reads it.
 *
 * `dueAt` is the date `buildRoadmap` derived from the intake, which is the client's arithmetic to own
 * by design. The field is sent as `null` rather than dropped when the builder produced none: on this
 * route `null` is the claim that the row has no date, while an omitted field leaves whatever the
 * server holds — and a recomputation that silently kept a deadline it no longer computed would be
 * the divergence this payload exists to make visible.
 */
function toRow(task: PhaseTask, phase: string): TaskReplaceRow {
  return {
    materialKey: task.materialId,
    programId: "",
    phase,
    dueAt: task.dueAt,
    scheduleOrigin: task.scheduleOrigin,
  };
}
