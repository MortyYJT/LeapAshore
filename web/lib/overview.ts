// The overview's model: every application as one line on a shared, linear time axis that starts today.
//
// Pure functions over the records `GET /api/application-records` serves, so the rules can be tested
// without a browser. Nothing here fills a gap in the data: an application without a deadline has no
// position, one without a round has none, and "materials" is the single self-reported flag the record
// carries.

import { activeRecord, type ApplicationRecord } from "./application-records.ts";
import { ownLinesOnly, progressLabel } from "./materials.ts";

/** A deadline this many days away or nearer is drawn in the urgent colour. */
export const SOON_DAYS = 14;

/**
 * Line colours, in the order they are handed out. The first five are the design's original lines;
 * the last three exist so that a sixth, seventh and eighth application still get a colour of their own.
 * The names are CSS class suffixes (`line-green` and so on) defined in `app/globals.css`.
 */
export const LINE_COLOURS = ["green", "blue", "magenta", "orange", "teal", "violet", "brown", "olive"] as const;
export type LineColour = (typeof LINE_COLOURS)[number];

/** How many colours an application's own id may ask for; the rest are only used when these run out. */
const ORIGINAL_LINES = 5;

const DAY = 86400000;

function utc(date: string): number {
  return Date.parse(`${date.slice(0, 10)}T00:00:00Z`);
}

/** Calendar days from `today` to `deadline` (both `YYYY-MM-DD`); negative once the date has passed. */
export function daysUntil(deadline: string, today: string): number {
  return Math.round((utc(deadline) - utc(today)) / DAY);
}

/** A date further away than this is written with its year. */
const NEEDS_YEAR = 330;

/** `MM/DD` for the axis and the rows, with the year in front when the date is about a year away. */
export function dateLabel(date: string, today: string): string {
  const [year, month, day] = date.slice(0, 10).split("-");
  return Math.abs(daysUntil(date, today)) > NEEDS_YEAR ? `${year}/${month}/${day}` : `${month}/${day}`;
}

/** `M 月 D 日` for sentences, with the year in front when the date is `days` away and that is about a year. */
export function sentenceDate(date: string, days: number): string {
  const [year, month, day] = date.slice(0, 10).split("-").map(Number);
  return `${Math.abs(days) > NEEDS_YEAR ? `${year} 年 ` : ""}${month} 月 ${day} 日`;
}

const CJK = /[㐀-鿿]/;
const CJK_SUFFIX = /(大学|大學|学院|學院|学校|學校)+$/;
const STOP_WORDS = new Set(["the", "of", "and", "at", "in", "for", "de", "la", "du", "der", "di"]);

/**
 * The short code printed on an application's line bullet, read from the school name alone.
 *
 * The records carry no abbreviation, so none is made up: a Chinese name gives its stem without the
 * 大学 / 学院 ending, three characters at most; a Latin name gives the abbreviation it states itself
 * (in brackets or as an all-capitals word), otherwise its initials. Two schools can share a code; the
 * colour and the full name printed beside it tell them apart.
 */
export function lineCode(school: string): string {
  const bracketed = /[（(]\s*([A-Z]{2,5})\s*[)）]/.exec(school)?.[1];
  // An apostrophe belongs to its word: King's is one word, not two.
  const name = school.replace(/[（(][^）)]*[)）]/g, " ").replace(/['\u2019]/g, "").trim();
  if (CJK.test(name)) {
    const characters = Array.from(name).filter((c) => /[\p{L}\p{N}]/u.test(c)).join("");
    const stem = characters.replace(CJK_SUFFIX, "") || characters;
    return Array.from(stem).slice(0, 3).join("");
  }
  if (bracketed) return bracketed;
  const words = name.split(/[^\p{L}\p{N}]+/u).filter(Boolean);
  if (!words.length) return "?";
  const capitals = words.find((word) => /^\p{Lu}{2,5}$/u.test(word));
  if (capitals) return capitals;
  if (words.length === 1) return Array.from(words[0]).slice(0, 3).join("").toLocaleUpperCase("en");
  const initials = words.filter((word) => !STOP_WORDS.has(word.toLowerCase())).map((word) => Array.from(word)[0]);
  return (initials.length ? initials : words.map((word) => Array.from(word)[0])).slice(0, 4).join("").toLocaleUpperCase("en");
}

/** FNV-1a, 32 bit: small, and the same on every device. */
function hash(text: string): number {
  let value = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    value ^= text.charCodeAt(i);
    value = Math.imul(value, 0x01000193);
  }
  return value >>> 0;
}

/**
 * A line colour for each application id.
 *
 * The answer depends only on the set of ids, so every device and every reload draws the same
 * application in the same colour. Each id asks for one of the five original colours by its hash. The
 * ids are served in sorted order: one whose colour is among the least used so far gets it, and any
 * other gets the first least-used colour. So applications share a colour only when there are more of
 * them than colours, and then the colours are reused evenly.
 */
export function assignLines(ids: readonly string[]): Map<string, LineColour> {
  const counts = LINE_COLOURS.map(() => 0);
  const lines = new Map<string, LineColour>();
  for (const id of [...new Set(ids)].sort()) {
    const least = Math.min(...counts);
    const wanted = hash(id) % ORIGINAL_LINES;
    const slot = counts[wanted] === least ? wanted : counts.indexOf(least);
    counts[slot] += 1;
    lines.set(id, LINE_COLOURS[slot]);
  }
  return lines;
}

export interface OverviewRow {
  record: ApplicationRecord;
  code: string;
  line: LineColour;
  /** Days to the deadline: null when it is unknown, negative when it has passed. */
  days: number | null;
  /** Where the line ends on the axis, 0 to 1. Null without a date, and for a date that has passed. */
  position: number | null;
  /** The date is past the end of the axis: the line runs off it and has no stop to end on. */
  beyond: boolean;
  /** Submitted: the line is retired and no longer counted down. */
  sent: boolean;
  /** Still open and due within `SOON_DAYS`. */
  soon: boolean;
  /**
   * Another application on screen is at the same school, so the school's name alone does not say which
   * one this is: places that name a row by its school add the program (`whoOf`).
   */
  shared: boolean;
}

export interface AxisTick {
  /** The first day of a month, `YYYY-MM-DD`. */
  date: string;
  position: number;
  /** Null where a label would crowd the one before it. */
  label: string | null;
}

export interface NextAction {
  row: OverviewRow;
  /** `confirm`: no date yet. `passed`: the date is behind us. `materials`: not ready. `submit`: ready, not sent. */
  kind: "confirm" | "passed" | "materials" | "submit";
}

export interface Overview {
  /** Open applications (unknown dates first, then by date), then submitted ones. */
  rows: OverviewRow[];
  /** Every record, drawn or not. */
  total: number;
  sentCount: number;
  /** Applications with a result or given up; they are counted, not drawn. */
  closed: number;
  /** The open application with the nearest date that has not passed. */
  nearest: OverviewRow | null;
  /** Open applications without a date. */
  unknown: OverviewRow[];
  /** Days the axis covers, from today. */
  horizon: number;
  soonPosition: number;
  ticks: AxisTick[];
  next: NextAction[];
}

/** The axis never covers less than this, so two near deadlines do not stretch across the whole table. */
const MIN_HORIZON = 90;
/** Nor more than two years: one distant date must not squeeze every other line against today's bar. */
const MAX_HORIZON = 730;
const HORIZON_MARGIN = 5;
/** A month label needs this share of the axis between it and the label before it. */
const LABEL_GAP = 0.11;
/** On a scale long enough to name years, labels are wider and need more room. */
const LONG_LABEL_GAP = 0.15;
/** The "today" label occupies the start of the axis. */
const TODAY_LABEL = 0.14;
const NEXT_ACTIONS = 3;

function byId(a: OverviewRow, b: OverviewRow): number {
  return a.record.id < b.record.id ? -1 : a.record.id > b.record.id ? 1 : 0;
}

/** Unknown dates first: they are what the applicant has to settle before anything can be planned. */
function byDate(a: OverviewRow, b: OverviewRow): number {
  if (a.days === null || b.days === null) return a.days === b.days ? byId(a, b) : a.days === null ? -1 : 1;
  return a.days - b.days || byId(a, b);
}

/** Month starts inside the scale. A scale of about a year or more is ticked by quarter instead. */
function monthTicks(today: string, horizon: number): AxisTick[] {
  const long = horizon > NEEDS_YEAR;
  const ticks: AxisTick[] = [];
  let year = Number(today.slice(0, 4));
  let month = Number(today.slice(5, 7));
  let last = TODAY_LABEL;
  let labelledYear: number | null = null;
  for (;;) {
    month += 1;
    if (month > 12) [year, month] = [year + 1, 1];
    const date = `${year}-${String(month).padStart(2, "0")}-01`;
    const offset = daysUntil(date, today);
    // Written so that anything that is not a day count inside the scale ends the loop.
    if (!(offset < horizon)) return ticks;
    if (long && month % 3 !== 1) continue;
    const position = offset / horizon;
    let label: string | null = null;
    if (position - last > (long ? LONG_LABEL_GAP : LABEL_GAP)) {
      const withYear = long && labelledYear !== year;
      label = `${withYear ? `${String(year).slice(2)} 年 ` : ""}${month} 月`;
      last = position;
      labelledYear = year;
    }
    ticks.push({ date, position, label });
  }
}

/** What tells a shared row apart under its school: the program, and its round when it has one. */
export function programOf(record: Pick<ApplicationRecord, "name" | "round">): string {
  return record.round ? `${record.name} · ${record.round}` : record.name;
}

/** The row's name in a sentence: the school, and the program too when another application is at that school. */
export function whoOf(row: Pick<OverviewRow, "record" | "shared">): string {
  return row.shared ? `${row.record.school.trim()} ${programOf(row.record)}` : row.record.school.trim();
}

export function overviewOf(records: readonly ApplicationRecord[], today: string): Overview {
  const lines = assignLines(records.map((record) => record.id));
  const drawn = records.filter((record) => activeRecord(record) || record.status === "submitted");
  // A date that cannot be read is unknown, like a missing one.
  const days = new Map(
    drawn.map((record) => {
      const left = record.deadline ? daysUntil(record.deadline, today) : null;
      return [record.id, left !== null && Number.isFinite(left) ? left : null];
    }),
  );
  const furthest = Math.max(MIN_HORIZON, ...[...days.values()].filter((value): value is number => value !== null));
  const horizon = Math.min(furthest, MAX_HORIZON) + HORIZON_MARGIN;

  const schoolKey = (record: ApplicationRecord) => record.school.trim().toLowerCase().replace(/\s+/g, " ");
  const perSchool = new Map<string, number>();
  for (const record of drawn) perSchool.set(schoolKey(record), (perSchool.get(schoolKey(record)) ?? 0) + 1);

  const rows = drawn.map((record): OverviewRow => {
    const left = days.get(record.id) ?? null;
    const sent = record.status === "submitted";
    const ahead = left !== null && left >= 0;
    return {
      record,
      code: lineCode(record.school),
      line: lines.get(record.id)!,
      days: left,
      position: ahead ? Math.min(left / horizon, 1) : null,
      beyond: ahead && left > horizon,
      sent,
      soon: !sent && ahead && left <= SOON_DAYS,
      shared: (perSchool.get(schoolKey(record)) ?? 0) > 1,
    };
  });
  const open = rows.filter((row) => !row.sent).sort(byDate);
  // A submitted application without a date sorts last: nothing about it is waiting.
  const sent = rows.filter((row) => row.sent).sort((a, b) => (a.days === null || b.days === null ? -byDate(a, b) : byDate(a, b)));

  return {
    rows: [...open, ...sent],
    total: records.length,
    sentCount: sent.length,
    closed: records.length - drawn.length,
    nearest: open.find((row) => row.position !== null) ?? null,
    unknown: open.filter((row) => row.days === null),
    horizon,
    soonPosition: SOON_DAYS / horizon,
    ticks: monthTicks(today, horizon),
    next: open.slice(0, NEXT_ACTIONS).map((row) => ({
      row,
      kind: row.days === null ? "confirm" : row.days < 0 ? "passed" : row.record.materialsReady ? "submit" : "materials",
    })),
  };
}

/** What a "接下来" row says about its application. */
export function nextSentence({ row, kind }: NextAction): string {
  if (kind === "confirm") return "截止日期还没确认。";
  if (kind === "passed") return `${sentenceDate(row.record.deadline!, row.days!)}的截止日期已过。`;
  const left = row.days === 0 ? "今天截止" : `还有 ${row.days} 天`;
  if (kind === "materials") return `${left}，材料还没备齐。`;
  // Every line ticked on a program whose requirements the catalogue does not hold: the applicant's own lines.
  const own = progressLabel(row.record) !== null && ownLinesOnly(row.record);
  return `${left}，${own ? "自列材料已勾完" : "材料已就绪"}，还没提交。`;
}
