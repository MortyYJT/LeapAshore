// When each roadmap phase is suggested to happen, given the plan, today and the applicant's deadlines.
//
// The plan is back-planned from the intake (`buildRoadmap`): each phase starts a fixed number of days
// before it and ends where the next one starts. That plan is what the task rows store, and it stays
// as it is. This module only decides what the page shows on a given day:
//
// - While no unfinished phase's window has ended, the plan is shown unchanged.
// - Once one has (its end is on or before today, Beijing date), the unfinished phases are laid out
//   again from today, in order. A phase asks for the days the plan gave it, times the share of its
//   steps still open; a phase with nothing open asks for none.
// - Phases before applying (up to and including the submission phase) must end by the earlier of
//   the earliest upcoming deadline among the applicant's open applications and where the plan ended
//   them; once that planned end has passed, by the deadline alone (or, without one, by that passed
//   day, which leaves no time). Later phases must end by the intake. A group that does not fit is
//   compressed in proportion into the time it has, but the group as a whole keeps at least one day
//   per open step: past that the suggestion would be fiction, so it runs past the date and the group
//   is reported as tight. Only the intake caps that.
// - A group is tight when it has less than half the days the plan would give its open steps.
// - A phase that is not late keeps its window when the re-laid ones finish before it starts; the
//   slack goes to the re-laid phase before it, so the line stays continuous. Between the two groups
//   the slack goes to the first later phase instead (it starts earlier), because nothing before
//   applying may run past the deadline it was fitted to.
// - Once the intake itself has passed there is nothing left to fit: the plan is shown unchanged and
//   the page asks for a new intake.
//
// No date here is invented: every boundary is computed from today, the intake the applicant chose,
// the plan derived from it, and a deadline from the applicant's own application records.

import type { OverviewRow } from "./overview.ts";

/** One phase of the back-planned plan. */
export interface PlannedPhase {
  /** Planned window, `YYYY-MM-DD`; the end is the next phase's start, or the intake. */
  start: string;
  end: string;
  /** Steps still open, and all steps. */
  open: number;
  total: number;
}

/** The earliest deadline the pre-application phases must finish by, from an application record. */
export interface ScheduleBound {
  date: string;
  school: string;
  /** Whether the applicant has checked the date against the official page (otherwise 待核对). */
  checked: boolean;
}

export interface ScheduledPhase {
  start: string;
  end: string;
  /** Unfinished, and its window is not the plan's. */
  moved: boolean;
  /** Unfinished, and in a group that is tight. */
  tight: boolean;
}

export interface Tight {
  /** `apply`: the phases before applying. `intake`: the phases after it. */
  group: "apply" | "intake";
  /** What the group must end by: the earliest deadline, the plan's end of applying, or the intake. */
  basis: "deadline" | "plan" | "intake";
  /** The deadline used, when the basis is one. */
  bound: ScheduleBound | null;
  /** Where the group's time starts (today, or where applying ends) and the date it must end by. */
  from: string;
  until: string;
  /** Days between them; zero or less when that date is already here. */
  days: number;
  /** Open steps in the group's phases, and the days the plan would give them. */
  open: number;
  planned: number;
  /** Indices of the group's unfinished phases. */
  phases: number[];
  /**
   * `date`: the group was given a day per open step and so runs past `until`. `intake`: the intake
   * cut even that short. Null when the group fits before `until`.
   */
  over: "date" | "intake" | null;
}

export interface Schedule {
  phases: ScheduledPhase[];
  /** Some phase was laid out again from today. */
  moved: boolean;
  /** The intake is today or past: nothing can be fitted before it. */
  expired: boolean;
  tight: Tight[];
}

const DAY = 86_400_000;
const dayOf = (iso: string) => Math.round(Date.parse(`${iso.slice(0, 10)}T00:00:00Z`) / DAY);
const isoOf = (day: number) => new Date(Math.round(day) * DAY).toISOString().slice(0, 10);

/** A group is tight below this share of the days the plan gives its open steps. */
export const TIGHT_SHARE = 0.5;
/** However little time is left, a group gets at least this many days per open step (on average). */
export const MIN_DAYS_PER_STEP = 1;

/**
 * The deadline the pre-application phases are fitted to: the earliest one on or after today among the
 * applications still open (not submitted). A date still 待核对 is used, and the page says so: leaving
 * it out would let the suggestion run past a date that is probably real.
 */
export function scheduleBound(rows: readonly OverviewRow[]): ScheduleBound | null {
  const next = rows
    .filter((row) => !row.sent && row.days !== null && row.days >= 0 && row.record.deadline)
    .sort((a, b) => a.days! - b.days! || (a.record.id < b.record.id ? -1 : 1))[0];
  return next ? { date: next.record.deadline!.slice(0, 10), school: next.record.school, checked: next.record.checkedAt !== null } : null;
}

/**
 * Lay out `plan` for `today` (`YYYY-MM-DD`, Beijing date). `applyLast` is the index of the last phase
 * before applying (the submission phase), or -1 when the plan has none: then every phase is fitted to
 * the intake alone.
 */
export function schedulePhases(plan: readonly PlannedPhase[], intake: string, today: string, bound: ScheduleBound | null, applyLast: number): Schedule {
  const unchanged = (expired: boolean): Schedule => ({
    phases: plan.map((phase) => ({ start: phase.start, end: phase.end, moved: false, tight: false })),
    moved: false,
    expired,
    tight: [],
  });
  const now = dayOf(today);
  const end = dayOf(intake);
  if (end <= now) return unchanged(true);

  const done = plan.map((phase) => phase.open === 0);
  const late = plan.map((phase, index) => !done[index] && dayOf(phase.end) <= now);
  const first = late.indexOf(true);
  if (first < 0) return unchanged(false);

  const plannedStart = plan.map((phase) => dayOf(phase.start));
  const plannedEnd = plan.map((phase) => dayOf(phase.end));
  const asks = plan.map((phase, index) => (phase.total === 0 ? 0 : ((plannedEnd[index] - plannedStart[index]) * phase.open) / phase.total));
  const starts = [...plannedStart];
  const ends = [...plannedEnd];
  const tight: Tight[] = [];
  const last = plan.length - 1;
  const applyEnd = Math.min(applyLast, last);

  /** Lay `from..to` out from `cursor`; they must end by `limit`. Returns where the group ends. */
  function lay(from: number, to: number, cursor: number, limit: number, group: Tight["group"], basis: Tight["basis"]): number {
    if (from > to) return cursor;
    let at = cursor;
    let rejoin = to + 1;
    for (let i = from; i <= to; i++) {
      if (!late[i] && plannedStart[i] >= at) {
        rejoin = i;
        break;
      }
      starts[i] = at;
      at += asks[i];
      ends[i] = at;
    }
    if (rejoin === from) {
      // Nothing here had to move. Time left over before it (applying ended early) is its own.
      if (cursor < starts[from]) starts[from] = cursor;
    } else if (rejoin <= to) {
      // The rest of the group keeps the plan; the phase before it takes the slack.
      ends[rejoin - 1] = plannedStart[rejoin];
    }
    if (ends[to] <= limit) {
      // Re-laid through the group's end with room to spare: applying may still take until the plan
      // ended it, but not past the deadline.
      if (rejoin > to && group === "apply" && to < last) ends[to] = Math.max(ends[to], Math.min(limit, plannedStart[to + 1]));
      return ends[to];
    }

    // It does not fit: the whole group from `from` is compressed into the time before `limit`.
    let open = 0;
    let wants = 0;
    for (let i = from; i <= to; i++) {
      open += plan[i].open;
      wants += asks[i];
    }
    const room = limit - cursor;
    const span = Math.max(0, Math.min(Math.max(room, open * MIN_DAYS_PER_STEP), end - cursor));
    let share = 0;
    for (let i = from; i <= to; i++) {
      starts[i] = cursor + (wants > 0 ? (span * share) / wants : 0);
      share += asks[i];
      ends[i] = cursor + (wants > 0 ? (span * share) / wants : 0);
    }
    if (room < wants * TIGHT_SHARE) {
      const phases: number[] = [];
      for (let i = from; i <= to; i++) if (!done[i]) phases.push(i);
      // Less than a day per open step can only be the intake's doing; more time than the room runs past the date.
      const over = span < open * MIN_DAYS_PER_STEP ? "intake" : span > room ? "date" : null;
      tight.push({ group, basis, bound: basis === "deadline" ? bound : null, from: isoOf(cursor), until: isoOf(limit), days: Math.round(room), open, planned: Math.round(wants), phases, over });
    }
    return ends[to];
  }

  let cursor = now;
  if (applyEnd >= first) {
    // The plan's own end of applying, unless a deadline comes first; once that end has passed, the
    // deadline alone; never past the intake.
    const planned = plannedEnd[applyEnd];
    const deadline = bound && dayOf(bound.date) >= now ? dayOf(bound.date) : null;
    const limit = Math.min(deadline ?? planned, planned > now ? planned : Infinity, end);
    const basis = deadline !== null && limit === deadline ? "deadline" : limit === planned ? "plan" : "intake";
    cursor = lay(first, applyEnd, now, limit, "apply", basis);
  }
  lay(Math.max(first, applyEnd + 1), last, cursor, end, "intake", "intake");

  const inTight = new Set(tight.flatMap((group) => group.phases));
  const phases = plan.map((phase, index): ScheduledPhase => {
    const start = isoOf(starts[index]);
    const finish = isoOf(ends[index]);
    return {
      start,
      end: finish,
      moved: !done[index] && (start !== phase.start || finish !== phase.end),
      tight: inTight.has(index),
    };
  });
  return { phases, moved: phases.some((phase) => phase.moved), expired: false, tight };
}
