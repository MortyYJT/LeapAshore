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
//
// `alreadyStored` is the module's other question, and it is asked of the same payload: not "what may
// be written" but "does anything need to be". Its arguments are the payload and the rows the server
// served, so the answer survives a reload — which is what the page's trigger needs and what session
// memory, by definition, cannot give it. See its own docstring for the three ways a stored roadmap
// disagrees with the one this profile implies.

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

/** How a served row and a payload row are matched to each other: by material and program together. */
function identity(materialKey: string, programId: string): string {
  return JSON.stringify([materialKey, programId]);
}

/**
 * Whether the rows the server holds are already the rows this payload would leave there.
 *
 * This is the "does a recomputation have a reason to run" question, asked of the server's own data:
 * the payload is built from the profile and the definition the server gave this page, and the rows
 * are the server's. When the two agree there is nothing to store, and when they disagree the
 * disagreement is exactly what a recomputation is for.
 *
 * It exists because the page cannot answer that question from session memory. The earlier trigger was
 * "the server has no rows, or the fingerprint moved since the last write this session made", and the
 * second half is silent after a reload: a fresh page has no memory of a write, so a subject whose
 * rows are stale — a profile edited on another device, a recomputation whose `PUT` failed and whose
 * notice told the applicant to reload — reloaded into a page that compared nothing and wrote nothing.
 * The measured case: 31 rows on the server with no row for a material the profile had just made
 * applicable, the failed write's notice on screen, and a reload that issued no request at all, so the
 * material rendered and could never be ticked. A reload has to reconcile, and the only evidence that
 * survives it is the server's.
 *
 * The three ways to disagree, and nothing else:
 *
 * - a material key that applies and has no row at all. This is the measured case: the page renders
 *   the material, `toggleMaterial` finds no row to address, and the applicant is told to prepare
 *   something they can never mark done. Any origin counts, because a row the applicant or the advisor
 *   owns is still a row the tick can address;
 * - a `system` row whose key no longer applies. The recomputation would remove it, and until it does
 *   the server holds a requirement nobody renders. A `user` or `agent` row is never counted here: the
 *   removal pass leaves those alone, so a row the recomputation cannot touch is not a reason to run;
 * - a row the payload would write that differs from the stored one in the fields the recomputation
 *   owns — the phase it is placed in and the date it was computed for. That is what makes an intake
 *   change, whose only effect is on every date, a reason to reconcile as well. `schedule_origin` is
 *   deliberately not compared: a stored value the client does not produce is a claim about where a
 *   date came from, and rewriting it is not something a reload should decide on its own.
 *
 * What is deliberately not compared is everything else about a row: its `status`, its `completed_at`
 * and its `suggested_at` are not the recomputation's to state, and a `system` row for an applicable
 * key that the payload does not carry — one naming a program this batch has no rows for — is left
 * where it is, because the recomputation cannot touch it either.
 *
 * Both arguments come from one computation: `payload` is `toReplacePayload` called with the same
 * `tasks`, which is what makes the ownership rule and this comparison agree about which rows are the
 * client's to write. A caller that compared a payload built from a different row list would be asking
 * about two different recomputations.
 */
export function alreadyStored(payload: TaskReplacePayload, tasks: TaskRow[]): boolean {
  const applicable = new Set(payload.applicableKeys);
  const storedKeys = new Set<string>();
  const stored = new Map<string, TaskRow>();
  for (const task of tasks) {
    storedKeys.add(task.material_key);
    if (task.origin !== "system") continue;
    if (!applicable.has(task.material_key)) return false;
    stored.set(identity(task.material_key, task.program_id), task);
  }

  for (const key of applicable) {
    if (!storedKeys.has(key)) return false;
  }

  for (const row of payload.rows) {
    const existing = stored.get(identity(row.materialKey, row.programId));
    if (existing === undefined) return false;
    if (existing.phase !== row.phase) return false;
    if (existing.due_at !== row.dueAt) return false;
  }

  return true;
}
