// What the roadmap timeline draws (spec application-roadmap), derived from a built roadmap and today.
// Pure, so the rules for the current phase and for the phases' windows are tested without a browser.
// When each phase is suggested to happen is decided in one place, lib/roadmap-schedule.ts.

import { schedulePhases, type ScheduleBound, type Tight } from "./roadmap-schedule.ts";
import type { Roadmap, RoadmapPhase } from "./types.ts";

export interface TimelinePhase {
  id: string;
  title: string;
  detail: string;
  /**
   * Suggested start and end, or null without an intake. Normally the plan back-planned from the
   * intake; for an unfinished phase whose planned window has passed, the window laid out again from
   * today (lib/roadmap-schedule.ts).
   */
  start: string | null;
  end: string | null;
  /** The window back-planned from the intake, whatever `start` and `end` say now. */
  planned: { start: string; end: string } | null;
  done: number;
  total: number;
  complete: boolean;
  /** The earliest phase with an unticked task. */
  current: boolean;
  /** Unfinished, and its window was laid out again from today. */
  moved: boolean;
  /** Unfinished, and there is not enough time left for it (see `Timeline.tight`). */
  tight: boolean;
  phase: RoadmapPhase;
}

export interface Timeline {
  dated: boolean;
  anchor: string | null;
  phases: TimelinePhase[];
  current: TimelinePhase | null;
  /** Some phase was laid out again from today. */
  moved: boolean;
  /** The intake is today or past, so nothing could be fitted before it. */
  expired: boolean;
  /** The groups of phases that have too little time left, before applying first. */
  tight: Tight[];
}

const day = (iso: string) => iso.slice(0, 10);

/**
 * The timeline on `today` (midnight UTC of the Beijing calendar day). `bound` is the earliest open
 * application deadline (`scheduleBound`), which the phases before applying are fitted to once they
 * have to be laid out again; without it they are fitted to the plan's own end of applying.
 */
export function timelineOf(roadmap: Roadmap, today: Date, bound: ScheduleBound | null = null): Timeline {
  const todayIso = today.toISOString().slice(0, 10);
  const currentId = roadmap.phases.find((p) => p.tasks.some((t) => !t.done))?.id ?? null;
  const planned = roadmap.phases.map((phase, index) => {
    const start = phase.suggestedAt ? day(phase.suggestedAt) : null;
    const next = roadmap.phases[index + 1]?.suggestedAt ?? roadmap.anchorAt;
    const end = roadmap.anchorAt !== null && next ? day(next) : null;
    return start && end ? { start, end } : null;
  });
  const dated = roadmap.anchorAt !== null;
  const counts = roadmap.phases.map((phase) => {
    const done = phase.tasks.filter((t) => t.done).length;
    return { done, total: phase.tasks.length };
  });

  const schedule =
    dated && planned.every((window) => window !== null)
      ? schedulePhases(
          planned.map((window, index) => ({ ...window!, open: counts[index].total - counts[index].done, total: counts[index].total })),
          day(roadmap.anchorAt!),
          todayIso,
          bound,
          roadmap.phases.findIndex((phase) => phase.id === "submission"),
        )
      : null;

  const phases = roadmap.phases.map((phase, index): TimelinePhase => {
    const { done, total } = counts[index];
    const window = schedule?.phases[index] ?? null;
    return {
      id: phase.id,
      title: phase.title,
      detail: phase.detail,
      start: window?.start ?? planned[index]?.start ?? (phase.suggestedAt ? day(phase.suggestedAt) : null),
      end: window?.end ?? planned[index]?.end ?? null,
      planned: planned[index],
      done,
      total,
      complete: total > 0 && done === total,
      current: phase.id === currentId,
      moved: window?.moved ?? false,
      tight: window?.tight ?? false,
      phase,
    };
  });
  return {
    dated,
    anchor: roadmap.anchorAt,
    phases,
    current: phases.find((p) => p.current) ?? null,
    moved: schedule?.moved ?? false,
    expired: schedule?.expired ?? false,
    tight: schedule?.tight ?? [],
  };
}
