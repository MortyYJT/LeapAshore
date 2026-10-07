// The page's read of the served roadmap definition, and the state that read leaves it holding.
//
// This is a module rather than a few lines inside the page's effect because of what the failure
// branch decides. Section 3.8 of `note/superpowers/specs/2026-10-06-stage-2-m2-design.md` is why the
// built-in `DEFAULT_DEFINITION` must never reach the recomputation: it deliberately omits the visa
// phase, so a write built from it would state an applicable-key set without the visa keys, and the
// server would read that as "no longer applicable" and delete the applicant's visa rows together with
// their completion state. The page's write gate is "is there a definition at all" — `toReplacePayload`
// answers `null` for a `null` definition — so the gate only holds while a failed read leaves the
// definition `null`. A read that fell back to the built-in copy would hand the mapper a definition
// and the visa rows would go.
//
// The page is a component, so nothing in `npm test` could reach a decision taken inside its
// `useEffect`, and the mistake is invisible in a browser until the next load has lost the rows. The
// mapper's own test file pins the mapper's half (`toReplacePayload(null, …)`); this file pins the
// page's half, on the code the page actually runs: `readRoadmapDefinition` is called with
// `fetchRoadmapDefinition` on mount, and its answer is what the page holds. `roadmap-definition.test.ts`
// drives the same function with a loader that rejects, which is the only way to make the failure
// branch reachable without taking the backend down.

import { toRoadmapDefinition, toTaskRows } from "./roadmap-source.ts";
import type { ServedRoadmapDefinition } from "./roadmap-source.ts";
import type { TaskRow } from "./roadmap-sync.ts";
import type { RoadmapDefinition } from "./types.ts";

/** Shown while the roadmap is built from the built-in copy because the definition read failed. */
export const LOCAL_DEFINITION_NOTICE =
  "路线图定义未能从服务器读取，当前显示的是内置副本，可能缺少服务器上的最新阶段。";

/**
 * What one read of the served definition leaves the page holding.
 *
 * The three fields travel together because one response carries all three, and because the failure
 * answer is the same for all of them: nothing was read.
 */
export interface DefinitionRead {
  /**
   * The definition the roadmap is built from and the write gate reads, or `null` when the read failed.
   *
   * `null` is an answer here, not a missing value. `buildRoadmap` reads it as "use the built-in copy",
   * `toReplacePayload` reads it as "do not write", and only a successful read can put anything else in
   * it — which is what makes §3.8 structural rather than a rule someone has to remember. It is
   * deliberately not a comparison against `DEFAULT_DEFINITION`: there is exactly one way to hold a
   * definition here and that is to have read it, so a second fallback added later could not be
   * mistaken for a served one.
   */
  definition: RoadmapDefinition | null;
  /** The notice to show while the page renders the built-in fallback, or `null` when it read one. */
  notice: string | null;
  /**
   * The caller's own task rows from the same response, or `null` when the read failed.
   *
   * An empty array and `null` are different claims: the first is the server saying this subject has no
   * rows yet, the second is that nobody asked. A caller that re-reads rows has to keep the ones it
   * already has on `null` rather than replace them with none.
   */
  tasks: TaskRow[] | null;
}

/** The state before any read has answered: nothing to write, nothing to say, no rows read. */
export const NO_DEFINITION_READ: DefinitionRead = { definition: null, notice: null, tasks: null };

/**
 * Read the definition once and answer with the state the page should hold.
 *
 * `load` is `fetchRoadmapDefinition` in the page and a stub in the tests; the network is not reached
 * from here, so the failure branch below is testable without a server and without taking one down.
 * This function does not reject: "the read failed" is part of its answer rather than an exception the
 * caller has to remember to catch, because the caller's next step is the same either way.
 *
 * The `try` covers the mapping as well as the load, and that is a claim about what a read is. The
 * transport refuses a body it cannot walk (`unwalkableReason` in `api.ts`), but the transport is not
 * the only thing that can fail on the way to this answer: `toRoadmapDefinition` and `toTaskRows` are
 * code, and a shape the checks do not anticipate — an entry that is a bare value, a field whose type
 * the wire broke — throws inside them. When the mapping sat outside the `try` that throw escaped as a
 * rejected promise, the caller's `.then` never ran, the page kept rendering the six built-in phases
 * with an empty `definitionRead` and *no notice at all*, and the rejection surfaced only in the
 * browser console: the silent fallback this module exists to prevent, arriving by a different door.
 * Wrapping the load alone is what let that regress. The decision this module makes — "the read did
 * not produce a definition, and the page must say so" — is one decision, so every way of failing to
 * read takes the same branch.
 */
export async function readRoadmapDefinition(
  load: () => Promise<ServedRoadmapDefinition>,
): Promise<DefinitionRead> {
  try {
    const served = await load();
    return {
      definition: toRoadmapDefinition(served),
      // Whatever the previous read had to say about the fallback no longer applies: this one succeeded.
      notice: null,
      tasks: toTaskRows(served.tasks),
    };
  } catch {
    // The branch the whole module exists for. The definition stays `null` and the built-in copy is
    // never put here: the page renders the fallback through `buildRoadmap`'s own default argument, so
    // the copy is on screen without ever becoming a definition the write gate could accept. The
    // notice is the other half — a roadmap that quietly omits the phases this build does not carry
    // looks exactly like one built from the server's answer.
    return { definition: null, notice: LOCAL_DEFINITION_NOTICE, tasks: null };
  }
}
