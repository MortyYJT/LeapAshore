// The roadmap line map's model and geometry.
//
// The preparation is one line along a linear time axis: every phase is a stretch of it over the
// phase's suggested window, and every task of the phase is a station on that stretch, filled once it
// is ticked. Each application is a line of its own colour that runs from today to a terminus on its
// deadline, as on the overview. The axis runs from the earlier of today and the first phase's start to
// the intake.
//
// Nothing here fills a gap. A task has no date of its own, so its station is spaced evenly inside its
// phase and carries no date; a phase's window is the system's suggestion and is labelled so on the
// page; an application without a deadline has no position; and with no intake there is no axis at
// all: the stretches are then laid out by how many stations each holds, in order, with no date on
// anything.
//
// Pure functions, so the rules are tested without a browser. A wide frame draws the map left to right
// from the fractions in `RoadmapMap`; a narrow one draws it top to bottom from `layoutTall`.

import { SOON_DAYS, dateLabel, daysUntil, sentenceDate, type OverviewRow } from "./overview.ts";
import type { Timeline, TimelinePhase } from "./roadmap-timeline.ts";

export interface MapStation {
  id: string;
  label: string;
  done: boolean;
  /** Along the axis, 0 to 1. */
  position: number;
}

export interface MapStretch {
  phase: TimelinePhase;
  /** Where the stretch starts and ends along the axis, 0 to 1. */
  start: number;
  end: number;
  /**
   * In the wide map: the name trails the stretch's end while there is room to its right, leads its
   * start once there is not, and sits above it when a long stretch leaves room on neither side.
   */
  label: "after" | "before" | "above";
  /**
   * In the wide map: how many of the stretch's first stations sit on the drop that leads into it
   * rather than on its level run. Zero unless a short window holds so many tasks that the stations
   * would crowd; a station carries no date of its own, so the drop, which stands on the stretch's
   * start, is as true a place for it as the run.
   */
  onDrop: number;
  stations: MapStation[];
  /** `complete`: every task ticked. `overdue`: its window has passed with a task left. */
  state: "complete" | "overdue" | "open";
}

export interface MapLane {
  row: OverviewRow;
  /**
   * `ahead`: the line stops at a terminus on its date. `beyond`: the date is past the end of the
   * axis, so the line runs off it. `unknown`: no date, a dotted run of no particular length.
   */
  kind: "ahead" | "beyond" | "unknown";
  /** Where the line stops along the axis, 0 to 1. */
  end: number;
  /**
   * In the wide map: the code and the date sit after the line's end while there is room; else on a
   * plate over the line, just before its end; and before today's bar when the line is too short for that.
   */
  label: "after" | "before" | "over";
}

export interface MapTick {
  /** The first day of a month, `YYYY-MM-DD`. */
  date: string;
  position: number;
  /** Null where a label would crowd the one before it or today's. */
  label: string | null;
}

export interface RoadmapMap {
  /** False without an intake: no axis, no today, no lanes; the stretches are in order only. */
  dated: boolean;
  /** Days the axis covers; without an intake, the number of station slots. */
  span: number;
  /** Today along the axis, or null without an intake. */
  today: number | null;
  /** Which side of today's line its label sits on. */
  todayLabel: "after" | "before";
  /** Where the two-week zone ends along the axis, or null without an intake. */
  soonEnd: number | null;
  ticks: MapTick[];
  stretches: MapStretch[];
  /** Applications drawn on the axis, nearest date first, then the ones without a date. */
  lanes: MapLane[];
  /** Applications the list under the map names and the axis does not draw: the date has passed. */
  listed: OverviewRow[];
}

/** A dotted run for an unknown date covers this share of the axis after today. */
const UNKNOWN_SHARE = 0.36;
/** A lane's label needs this share of the axis: after the line's end, or over the line itself. */
const LABEL_ROOM = 0.2;
/** A month label needs this share of the axis between it and the label before it. */
const TICK_GAP = 0.075;
/** Today's label occupies this share of the axis on its side of the line. */
const TODAY_LABEL = 0.11;

/** A stretch's name needs about this share of the axis beside the stretch. */
const NAME_ROOM = 0.3;

const iso = (date: string) => date.slice(0, 10);

/** A station needs this share of the axis on a level run; a stretch that gives less is crowded. */
const CROWDED = 0.0176;
/** The drop into a stretch holds two stations. */
const ON_DROP = 2;

function onDrop(index: number, start: number, end: number, count: number): number {
  return index > 0 && count > ON_DROP && (end - start) / count < CROWDED ? ON_DROP : 0;
}

function nameSide(start: number, end: number): MapStretch["label"] {
  return 1 - end >= NAME_ROOM ? "after" : start >= NAME_ROOM ? "before" : "above";
}

function stateOf(phase: TimelinePhase): MapStretch["state"] {
  return phase.complete ? "complete" : phase.overdue ? "overdue" : "open";
}

function stations(phase: TimelinePhase, start: number, end: number): MapStation[] {
  const tasks = phase.phase.tasks;
  return tasks.map((task, index) => ({
    id: task.materialId,
    label: task.label,
    done: task.done,
    position: start + ((end - start) * (index + 0.5)) / tasks.length,
  }));
}

function monthTicks(startDate: string, span: number, today: number, todayLabel: "after" | "before"): MapTick[] {
  const ticks: MapTick[] = [];
  let year = Number(startDate.slice(0, 4));
  let month = Number(startDate.slice(5, 7));
  let last = -1;
  const [from, to] = todayLabel === "after" ? [today - 0.02, today + TODAY_LABEL] : [today - TODAY_LABEL, today + 0.02];
  for (;;) {
    month += 1;
    if (month > 12) [year, month] = [year + 1, 1];
    const date = `${year}-${String(month).padStart(2, "0")}-01`;
    const offset = daysUntil(date, startDate);
    // Written so that anything that is not a day count inside the axis ends the loop.
    if (!(offset < span)) return ticks;
    const position = offset / span;
    let label: string | null = null;
    // A label is written to the right of its tick, so it also needs room before the axis ends.
    if (position - last >= TICK_GAP && (position < from || position > to) && position <= 1 - TICK_GAP * 0.6) {
      label = `${month === 1 ? `${String(year).slice(2)} 年 ` : ""}${month} 月`;
      last = position;
    }
    ticks.push({ date, position, label });
  }
}

/**
 * The map for a timeline and the applications the overview draws (`overviewOf(...).rows`), on `today`
 * (`YYYY-MM-DD`, the same day the timeline was built for).
 */
export function roadmapMap(timeline: Timeline, rows: readonly OverviewRow[], today: string): RoadmapMap {
  const dated = timeline.dated && timeline.anchor !== null && timeline.phases.every((phase) => phase.start && phase.end);
  if (!dated) {
    // In order only: every station takes one slot. A phase gets at least two, so that its name has
    // room beside it; that includes a phase without tasks.
    const slots = timeline.phases.map((phase) => Math.max(2, phase.total));
    const span = Math.max(1, slots.reduce((sum, value) => sum + value, 0));
    let at = 0;
    const stretches = timeline.phases.map((phase, index): MapStretch => {
      const start = at / span;
      at += slots[index];
      const end = at / span;
      return { phase, start, end, label: nameSide(start, end), onDrop: 0, stations: stations(phase, start, end), state: phase.complete ? "complete" : "open" };
    });
    return { dated: false, span, today: null, todayLabel: "after", soonEnd: null, ticks: [], stretches, lanes: [], listed: [...rows] };
  }

  const first = iso(timeline.phases[0]?.start ?? today);
  const startDate = first < today ? first : today;
  const anchor = iso(timeline.anchor!);
  const endDate = anchor > today ? anchor : today;
  const span = Math.max(1, daysUntil(endDate, startDate));
  const at = (date: string) => daysUntil(iso(date), startDate) / span;
  const todayAt = at(today);
  const todayLabel = todayAt > 1 - TODAY_LABEL ? "before" : "after";

  const stretches = timeline.phases.map((phase, index): MapStretch => {
    const start = at(phase.start!);
    const end = at(phase.end!);
    return {
      phase,
      start,
      end,
      label: nameSide(start, end),
      onDrop: onDrop(index, start, end, phase.total),
      stations: stations(phase, start, end),
      state: stateOf(phase),
    };
  });

  const ahead = rows
    .filter((row) => row.days !== null && row.days >= 0)
    .sort((a, b) => a.days! - b.days! || (a.record.id < b.record.id ? -1 : 1));
  const unknown = rows.filter((row) => row.days === null && !row.sent);
  const placed = (end: number): MapLane["label"] => (1 - end >= LABEL_ROOM ? "after" : end - todayAt >= LABEL_ROOM ? "over" : "before");
  const lanes: MapLane[] = [
    ...ahead.map((row): MapLane => {
      const position = at(row.record.deadline!);
      const end = Math.min(position, 1);
      return { row, kind: position > 1 ? "beyond" : "ahead", end, label: position > 1 ? "over" : placed(end) };
    }),
    ...unknown.map((row): MapLane => {
      const end = Math.min(1, todayAt + Math.max(0.08, (1 - todayAt) * UNKNOWN_SHARE));
      return { row, kind: "unknown", end, label: placed(end) };
    }),
  ];
  const drawn = new Set(lanes.map((lane) => lane.row.record.id));

  return {
    dated: true,
    span,
    today: todayAt,
    todayLabel,
    soonEnd: Math.min(1, todayAt + SOON_DAYS / span),
    ticks: monthTicks(startDate, span, todayAt, todayLabel),
    stretches,
    lanes,
    listed: rows.filter((row) => !drawn.has(row.record.id)),
  };
}

// ---------------------------------------------------------------------------------------------------
// Words
// ---------------------------------------------------------------------------------------------------

const month = (date: string) => sentenceDate(date, 0);

/** The one sentence under the title: the fact the applicant most needs today. */
export function headline(timeline: Timeline): string {
  if (!timeline.phases.length) return "路线图里还没有阶段。";
  const current = timeline.current;
  if (!timeline.dated) {
    return current ? `现在在「${current.title}」，还有 ${current.total - current.done} 项没做。` : "所有步骤都做完了。";
  }
  const late = timeline.phases.filter((phase) => phase.overdue);
  if (late.length > 0) {
    const left = late.reduce((sum, phase) => sum + (phase.total - phase.done), 0);
    return `「${late[0].title}」${late.length > 1 ? `等 ${late.length} 段` : ""}已过建议时间，还有 ${left} 项没做。`;
  }
  if (!current) return "所有步骤都做完了。";
  return `现在在「${current.title}」，还有 ${current.total - current.done} 项没做，建议 ${current.end ? month(current.end) : "入学"}前做完。`;
}

/** A stretch in words, for a reader who cannot see it. */
export function stretchLabel(stretch: MapStretch): string {
  const { phase } = stretch;
  const start = phase.start ? `建议 ${month(phase.start)}开始，` : "";
  return `${phase.title}，${start}${phase.done}/${phase.total} 项做完${phase.overdue ? "，已过建议时间" : ""}${phase.current ? "，当前这一段" : ""}`;
}

/** What a lane's label prints after the application's code. */
export function laneWhen(lane: MapLane, today: string): string {
  return lane.kind === "unknown" ? "待确认" : dateLabel(lane.row.record.deadline!, today);
}

// ---------------------------------------------------------------------------------------------------
// Top to bottom, for a narrow frame
// ---------------------------------------------------------------------------------------------------

export interface TallStretch {
  stretch: MapStretch;
  y0: number;
  y1: number;
  stations: { station: MapStation; y: number }[];
}

export interface TallLane {
  lane: MapLane;
  /** The lane's own x; lines run down it from today. */
  x: number;
  y0: number;
  /** Where the line stops: its terminus, or the foot of the axis for a date beyond it. */
  y1: number;
  /** The centre of its label, level with the terminus or pushed below it, never above. */
  labelY: number;
  /** From the terminus down the lane to the label's level, then across to the label. */
  leader: string;
}

export interface TallLayout {
  height: number;
  /** Pixels per day (per station slot without an intake). */
  scale: number;
  /** Where the labels of the applications end, right-aligned. */
  labelRight: number;
  journeyX: number;
  todayY: number | null;
  /** The x-range today's bar covers: the lanes and the journey. */
  todayX: [number, number];
  endY: number;
  stretches: TallStretch[];
  lanes: TallLane[];
}

/** The room a lane's label takes: the code's bullet and a date. */
export const TALL_LABEL = 88;
/** The room today's label takes when there is no lane to label. */
const TALL_TODAY = 66;
/** Labels of two applications are at least this far apart. */
export const TALL_LABEL_PITCH = 24;
/** A label is at least this far below today's bar. */
export const TALL_CLEAR = 22;
const TALL_TOP = 16;
const TALL_HEIGHT = 860;
const TALL_SCALE: [number, number] = [1.5, 2.6];
const TALL_SLOT = 24;
const TALL_LEADER_RUN = 12;
const TALL_CHAMFER = 6;

/**
 * Where everything goes when time runs down the page. The scale depends only on how long the axis is,
 * so the drawing needs no measured width: the applications are on the left at fixed positions and the
 * phases' names take whatever room is left on the right.
 *
 * The lanes keep the model's order, nearest date leftmost. A label sits level with its terminus, or
 * lower when the one above needs the room; its lane then runs on, thinner, to the label's level. A
 * label is never above its terminus, so the piece that crosses to it only passes lanes that have
 * already ended. Applications without a date have no lane here; the page names them under the map.
 */
export function layoutTall(map: RoadmapMap): TallLayout {
  const scale = map.dated ? Math.min(TALL_SCALE[1], Math.max(TALL_SCALE[0], TALL_HEIGHT / map.span)) : TALL_SLOT;
  const y = (position: number) => TALL_TOP + position * map.span * scale;
  const endY = y(1);
  const todayY = map.today === null ? null : y(map.today);

  const dated = map.lanes.filter((lane) => lane.kind !== "unknown");
  const pitch = dated.length > 8 ? 6 : 7;
  // The left column holds today's label and, under it, the applications' labels.
  const labelRight = dated.length ? TALL_LABEL : todayY === null ? 0 : TALL_TODAY;
  const lanesLeft = labelRight ? labelRight + 5 + TALL_LEADER_RUN : 6;
  const journeyX = lanesLeft + dated.length * pitch + (dated.length ? 12 : 4);

  // The first label starts clear of today's bar and its own label.
  let previous = (todayY ?? TALL_TOP) + TALL_CLEAR - TALL_LABEL_PITCH;
  const lanes = dated.map((lane, index): TallLane => {
    const x = lanesLeft + pitch * (index + 0.5);
    const y1 = y(lane.end);
    const labelY = Math.max(y1, previous + TALL_LABEL_PITCH);
    previous = labelY;
    const drop = labelY - y1;
    const to = labelRight + 5;
    const leader =
      drop < 0.5
        ? `M${x} ${y1}H${to}`
        : drop < TALL_CHAMFER
          ? `M${x} ${y1}L${x - drop} ${labelY}H${to}`
          : `M${x} ${y1}V${labelY - TALL_CHAMFER}L${x - TALL_CHAMFER} ${labelY}H${to}`;
    return { lane, x, y0: todayY ?? TALL_TOP, y1, labelY, leader };
  });

  const stretches = map.stretches.map((stretch): TallStretch => ({
    stretch,
    y0: y(stretch.start),
    y1: y(stretch.end),
    stations: stretch.stations.map((station) => ({ station, y: y(station.position) })),
  }));

  const lowest = Math.max(endY, ...lanes.map((lane) => lane.labelY));
  return {
    height: lowest + 30,
    scale,
    labelRight,
    journeyX,
    todayY,
    todayX: [dated.length ? lanesLeft - 4 : journeyX - 10, journeyX + 10],
    endY,
    stretches,
    lanes,
  };
}
