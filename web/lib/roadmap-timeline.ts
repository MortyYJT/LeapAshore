// What the roadmap timeline draws (spec application-roadmap), derived from a built roadmap and today.
// Pure, so the rules for the current phase and for overdue phases are tested without a browser.

import type { Roadmap, RoadmapPhase } from "./types.ts";

export interface TimelinePhase {
  id: string;
  title: string;
  detail: string;
  /** Suggested start and end (the next phase's start, or the intake), or null without an intake. */
  start: string | null;
  end: string | null;
  done: number;
  total: number;
  complete: boolean;
  /** The earliest phase with an unticked task. */
  current: boolean;
  /** Its end has passed and a task is left. */
  overdue: boolean;
  phase: RoadmapPhase;
}

export interface Timeline {
  dated: boolean;
  anchor: string | null;
  phases: TimelinePhase[];
  current: TimelinePhase | null;
}

const day = (iso: string) => iso.slice(0, 10);

export function timelineOf(roadmap: Roadmap, today: Date): Timeline {
  const todayIso = today.toISOString().slice(0, 10);
  const dated = roadmap.anchorAt !== null;
  const currentId = roadmap.phases.find((p) => p.tasks.some((t) => !t.done))?.id ?? null;
  const phases = roadmap.phases.map((phase, index): TimelinePhase => {
    const start = phase.suggestedAt ? day(phase.suggestedAt) : null;
    const next = roadmap.phases[index + 1]?.suggestedAt ?? roadmap.anchorAt;
    const end = dated && next ? day(next) : null;
    const done = phase.tasks.filter((t) => t.done).length;
    const complete = phase.tasks.length > 0 && done === phase.tasks.length;
    return {
      id: phase.id,
      title: phase.title,
      detail: phase.detail,
      start,
      end,
      done,
      total: phase.tasks.length,
      complete,
      current: phase.id === currentId,
      overdue: end !== null && end < todayIso && !complete,
      phase,
    };
  });
  return {
    dated,
    anchor: roadmap.anchorAt,
    phases,
    current: phases.find((p) => p.current) ?? null,
  };
}
