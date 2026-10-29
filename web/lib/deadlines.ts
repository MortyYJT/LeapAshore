// Which application deadline a program shows, and whether it has passed (openspec requirement-dates).
//
// The catalogue serves every deadline a program's page states, past ones included; nothing stores
// "closed", so it is decided here against today each time the page renders and cannot go stale. Today
// is the Beijing calendar date (D4), the same day on the server-rendered program page and in the
// browser. A deadline on today's date is still open.

/** One collected deadline as `GET /api/programs` and `GET /api/applications` serve it. */
export interface CollectedDeadline {
  label: string | null;
  /** ISO date, `YYYY-MM-DD`. */
  date: string;
  /** The official page the date was read from. */
  sourceUrl: string;
}

/**
 * What a portfolio row shows as its deadline.
 *
 * `upcoming` is drawn solid on the timeline with its source link; `closed` is listed as 已截止 and is
 * never drawn as a future milestone; `unknown` is 未收录. `origin` says where the date came from:
 * `entered` is the row's own date (the applicant's or the advisor's), which an import never writes.
 */
export interface DeadlineView {
  state: "upcoming" | "closed" | "unknown";
  date: string | null;
  url: string | null;
  label: string | null;
  origin: "entered" | "collected" | null;
}

/** The fields a row's deadline is read from: its own date and source, and the program's collected ones. */
export interface DeadlineFields {
  officialDeadline?: string | null;
  deadlineSourceUrl?: string | null;
  deadlines?: readonly CollectedDeadline[] | null;
}

const BEIJING = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" });

/** Today's date in Beijing as `YYYY-MM-DD`. */
export function beijingToday(now: Date = new Date()): string {
  return BEIJING.format(now);
}

/** Whether a deadline has passed: its day is before today (ISO strings compare as dates). */
export function isClosed(date: string, today: string): boolean {
  return date.slice(0, 10) < today;
}

const UNKNOWN: DeadlineView = { state: "unknown", date: null, url: null, label: null, origin: null };

/**
 * The row's deadline: its own date when it has one with a source; otherwise the program's earliest
 * deadline on or after today; otherwise, when every collected one has passed, the latest, closed.
 */
export function deadlineOf(row: DeadlineFields, today: string): DeadlineView {
  if (row.officialDeadline && row.deadlineSourceUrl) {
    const date = row.officialDeadline.slice(0, 10);
    return { state: isClosed(date, today) ? "closed" : "upcoming", date, url: row.deadlineSourceUrl, label: null, origin: "entered" };
  }
  const collected = [...(row.deadlines ?? [])].sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  if (collected.length === 0) return UNKNOWN;
  const next = collected.find((d) => !isClosed(d.date, today));
  const pick = next ?? collected[collected.length - 1];
  return { state: next ? "upcoming" : "closed", date: pick.date, url: pick.sourceUrl, label: pick.label, origin: "collected" };
}
