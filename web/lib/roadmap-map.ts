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
// A phase laid out again from today (lib/roadmap-schedule.ts) is drawn like any other open stretch,
// from its new start. When a finished phase ends before it, in the past, the line between the two
// runs on as a thin lead to today, where the planned window lay; nothing is painted as overdue.
//
// Pure functions, so the rules are tested without a browser. A wide frame draws the map left to right
// from the fractions in `RoadmapMap`; a narrow one draws it top to bottom from `layoutTall`.

import { SOON_DAYS, dateLabel, daysUntil, sentenceDate, type OverviewRow } from "./overview.ts";
import type { Tight } from "./roadmap-schedule.ts";
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
   * start once there is not, and sits above it when a long stretch leaves room on neither side. Above
   * is where the name of the stretch before ends up, so after the first a long stretch's name sits
   * below its start instead.
   */
  label: "after" | "before" | "above" | "below";
  /**
   * In the wide map: how many of the stretch's first stations sit on the drop that leads into it
   * rather than on its level run. Zero unless a short window holds so many tasks that the stations
   * would crowd; a station carries no date of its own, so the drop, which stands on the stretch's
   * start, is as true a place for it as the run.
   */
  onDrop: number;
  stations: MapStation[];
  /** `complete`: every task ticked. */
  state: "complete" | "open";
  /**
   * Where the line reaches this stretch when that is before `start`: the end of the stretch before,
   * in the past, when this one was laid out again from today. The run between is the thin lead.
   */
  lead: number | null;
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

function nameSide(start: number, end: number, index: number): MapStretch["label"] {
  return 1 - end >= NAME_ROOM ? "after" : start >= NAME_ROOM ? "before" : index === 0 ? "above" : "below";
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
      return { phase, start, end, label: nameSide(start, end, index), onDrop: 0, stations: stations(phase, start, end), state: phase.complete ? "complete" : "open", lead: null };
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
    const before = timeline.phases[index - 1];
    const lead = before && before.end! < phase.start! ? at(before.end!) : null;
    return {
      phase,
      start,
      end,
      label: nameSide(start, end, index),
      // With a lead the drop is where the lead begins, in the past: no station stands on it.
      onDrop: lead === null ? onDrop(index, start, end, phase.total) : 0,
      stations: stations(phase, start, end),
      state: phase.complete ? "complete" : "open",
      lead,
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
  if (timeline.expired) return "填的入学时间已经过了，这里的建议时间都不再适用。改一下入学时间，系统会重新倒推。";
  if (!current) return "所有步骤都做完了。";
  const left = current.total - current.done;
  const by = current.end ? month(current.end) : "入学";
  return current.moved
    ? `现在在「${current.title}」，还有 ${left} 项没做。按今天重新排，建议 ${by}前做完。`
    : `现在在「${current.title}」，还有 ${left} 项没做，建议 ${by}前做完。`;
}

/**
 * What follows 「时间很紧」 for one group of phases that has too little time left (lib/roadmap-schedule.ts):
 * the date it is measured against and where that date comes from, the days left, the open steps and
 * the days the plan would give them. A deadline still 待核对 is said to be.
 */
export function tightWords(tight: Tight, timeline: Timeline, today: string): string {
  const until = month(tight.until);
  const steps = `还有 ${tight.open} 项没做`;
  const plan = `，原计划给这些步骤留了 ${tight.planned} 天`;
  if (tight.group === "intake") {
    const first = timeline.phases[tight.phases[0]];
    const names = first ? `「${first.title}」${tight.phases.length > 1 ? "等" : ""}` : "";
    const span = tight.from === today ? "离入学" : `从 ${month(tight.from)}到入学`;
    return `${span}只有 ${Math.max(0, tight.days)} 天，${names}${steps}${plan}。`;
  }
  // However little time is left, the open steps keep a day each on average, so the suggestion then runs
  // past the date; only the intake can cut that short.
  const over = tight.over === "date" ? "下面按平均每项一天排，所以会排过这一天。" : tight.over === "intake" ? "到入学前已经排不下平均每项一天。" : "";
  if (tight.basis === "deadline" && tight.bound) {
    const which = `（${tight.bound.school}${tight.bound.checked ? "" : "，日期待核对"}）`;
    if (tight.days <= 0) return `最早的截止日期就是今天${which}，申请前${steps}。${over}`;
    return `离最早的截止日期 ${until}${which}只剩 ${tight.days} 天，申请前${steps}${plan}。${over}`;
  }
  if (tight.days <= 0) return `按入学时间倒推，申请最好在 ${until}前交完，已经没有余下的时间，申请前${steps}。${over}`;
  return `按入学时间倒推，申请最好在 ${until}前交完，只剩 ${tight.days} 天，申请前${steps}${plan}。${over}`;
}

/**
 * What is written beside a stretch's name: when it is suggested to start, and whether that was re-laid.
 * A finished phase that had to make way for re-laid ones says nothing: its new place is not a suggestion.
 */
export function stretchWhen(phase: TimelinePhase, today: string): string | null {
  if (!phase.start || displaced(phase)) return null;
  const from = phase.start === today ? "今天起" : `${dateLabel(phase.start, today)} 起`;
  return phase.moved ? `重排后 ${from}` : `建议 ${from}`;
}

/** A finished phase moved along by re-laid ones: it keeps its planned suggestion in words. */
function displaced(phase: TimelinePhase): boolean {
  return phase.complete && phase.planned !== null && (phase.start !== phase.planned.start || phase.end !== phase.planned.end);
}

/** A phase's window in a sentence, with the planned one beside it when it was laid out again. */
export function windowWords(phase: TimelinePhase): string | null {
  if (!phase.start || !phase.end) return null;
  const span = (start: string, end: string) => (start === end ? month(start) : `${month(start)}到 ${month(end)}`);
  if (displaced(phase)) return `原来建议 ${span(phase.planned!.start, phase.planned!.end)}。`;
  if (phase.moved && phase.planned) return `系统按今天重新排的建议：${span(phase.start, phase.end)}（原来建议 ${span(phase.planned.start, phase.planned.end)}）。`;
  return `建议 ${span(phase.start, phase.end)}。`;
}

/** A stretch in words, for a reader who cannot see it. */
export function stretchLabel(stretch: MapStretch): string {
  const { phase } = stretch;
  const start = phase.start ? `建议 ${month(phase.start)}开始，` : "";
  return `${phase.title}，${start}${phase.done}/${phase.total} 项做完${phase.moved ? "，系统按今天重新排过" : ""}${phase.tight ? "，时间很紧" : ""}${phase.current ? "，当前这一段" : ""}`;
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
  /** Where the thin lead into the stretch starts, or null without one (`MapStretch.lead`). */
  lead: number | null;
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
  /** Where the line ends: the intake. Above `endY` when the intake has passed and the axis runs on to today. */
  intakeY: number;
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
/** The same when a date is far enough away to be written with its year. */
const TALL_LABEL_YEAR = 116;
/** `dateLabel` writes the year for a date further away than this. */
const YEAR_AFTER = 330;
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
/** A stretch is at least this tall, so that its name and count fit beside it (two lines of text). */
export const TALL_MIN_STRETCH = 44;
/** ...and gives each of its stations this much, so that the rings do not overlap. */
const TALL_STATION = 11;

/**
 * Where a position along the axis lands, top to bottom: linear at `scale`, except that a stretch
 * shorter than `TALL_MIN_STRETCH` is opened up to it and everything below moves down with it. Order
 * is kept: a date inside an opened stretch lands proportionally inside it. Only a stretch squeezed
 * into a few days (lib/roadmap-schedule.ts) is opened; at an ordinary scale every phase is taller.
 */
function tallScale(map: RoadmapMap, scale: number) {
  const linear = (length: number) => length * map.span * scale;
  const points: [number, number][] = [[0, 0]];
  const spans = new Map<string, { y0: number; y1: number; lead: number | null }>();
  let at = 0;
  let height = 0;
  const to = (position: number, add: number) => {
    at = position;
    height += add;
    points.push([at, height]);
  };
  for (const stretch of map.stretches) {
    const from = stretch.lead ?? stretch.start;
    if (from > at) to(from, linear(from - at));
    const lead = stretch.lead === null ? null : height;
    if (stretch.start > at) to(stretch.start, linear(stretch.start - at));
    const y0 = height;
    to(Math.max(at, stretch.end), Math.max(linear(stretch.end - stretch.start), TALL_MIN_STRETCH, stretch.stations.length * TALL_STATION));
    spans.set(stretch.phase.id, { y0, y1: height, lead });
  }
  if (at < 1) to(1, linear(1 - at));
  const y = (position: number) => {
    for (let i = 1; i < points.length; i++) {
      const [p0, y0] = points[i - 1];
      const [p1, y1] = points[i];
      if (position <= p1) return p1 > p0 ? y0 + ((Math.max(position, p0) - p0) / (p1 - p0)) * (y1 - y0) : y0;
    }
    return height + linear(position - at);
  };
  return { y, spans };
}

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
  const axis = tallScale(map, scale);
  const y = (position: number) => TALL_TOP + axis.y(position);
  const endY = y(1);
  const todayY = map.today === null ? null : y(map.today);

  const dated = map.lanes.filter((lane) => lane.kind !== "unknown");
  const pitch = dated.length > 8 ? 6 : 7;
  // The left column holds today's label and, under it, the applications' labels.
  const withYear = dated.some((lane) => (lane.row.days ?? 0) > YEAR_AFTER);
  const labelRight = dated.length ? (withYear ? TALL_LABEL_YEAR : TALL_LABEL) : todayY === null ? 0 : TALL_TODAY;
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

  const stretches = map.stretches.map((stretch): TallStretch => {
    const { y0, y1, lead } = axis.spans.get(stretch.phase.id)!;
    const count = stretch.stations.length;
    return {
      stretch,
      y0: TALL_TOP + y0,
      y1: TALL_TOP + y1,
      lead: lead === null ? null : TALL_TOP + lead,
      // Evenly inside the stretch, as on the axis (`stations`), whatever height it was given.
      stations: stretch.stations.map((station, index) => ({ station, y: TALL_TOP + y0 + ((y1 - y0) * (index + 0.5)) / count })),
    };
  });

  const lowest = Math.max(endY, ...lanes.map((lane) => lane.labelY));
  return {
    height: lowest + 30,
    scale,
    labelRight,
    intakeY: stretches.length ? stretches[stretches.length - 1].y1 : endY,
    journeyX,
    todayY,
    todayX: [dated.length ? lanesLeft - 4 : journeyX - 10, journeyX + 10],
    endY,
    stretches,
    lanes,
  };
}
