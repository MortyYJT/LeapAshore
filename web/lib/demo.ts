// The demo a signed-out visitor sees on the overview: a handful of real catalogue programs drawn as
// if they were somebody's applications.
//
// Two halves, kept apart. What the catalogue knows (the school, the program's name, its deadlines and
// the page each date was read from) is read from the public `GET /api/programs` when the page loads
// and is shown as served; no date is written in this file. What an applicant would add (the status,
// whether the materials are ready) is made up here, the same way every time, and the page says so.
//
// The programs are picked by a rule rather than listed with their dates, so the demo keeps working as
// deadlines pass: a program drops out once its last collected date is behind us, and the next one on
// the list takes its place.

import type { ApplicationRecord } from "./application-records.ts";
import { deadlineOf, type CollectedDeadline } from "./deadlines.ts";
import { SOON_DAYS, daysUntil } from "./overview.ts";

/**
 * Well-known computing programs, most preferred first, by their catalogue id.
 *
 * An id that the catalogue no longer has is skipped; one whose deadlines have all passed is left out
 * until new ones are collected. The first five are what the demo shows while each has a date ahead
 * (the fifth has no collected date and is drawn as unknown); the rest take over as dates pass.
 */
export const DEMO_PROGRAM_IDS: readonly string[] = [
  "university-of-hong-kong-master-of-data-science-e60565",
  "imperial-college-london-msc-computing-f38aa7",
  "national-university-of-s-master-of-computing-computer-sci-96b220",
  "ucl-computer-science-msc-9d29ee",
  "university-of-edinburgh-computer-science-msc-b52f8b",
  "hong-kong-university-of-master-of-science-program-in-inf-529f49",
  "university-of-glasgow-computing-science-msc-03844f",
  "chinese-university-of-ho-msc-in-computer-science-402b13",
  "carnegie-mellon-universi-master-of-computational-data-sci-d9f649",
  "university-of-manchester-artificial-intelligence-msc-404945",
  "king-s-college-london-artificial-intelligence-msc-f8d855",
  "cricos-111671D",
];

/** The schools of the list above. Their other computing programs fill in when the list comes up short. */
export const DEMO_SCHOOL_IDS: readonly string[] = [
  "university-of-hong-kong",
  "imperial-college-london",
  "national-university-of-singapore",
  "ucl",
  "university-of-edinburgh",
  "hong-kong-university-of-science-and-technology",
  "university-of-glasgow",
  "chinese-university-of-hong-kong",
  "carnegie-mellon-university",
  "university-of-manchester",
  "king-s-college-london",
];

/** How many programs with a date ahead the demo draws. With the one unknown date that makes five lines. */
export const DEMO_DATED = 4;
/** Fewer dated programs than this is not worth calling a demo; the page shows its plain sign-in block. */
const DEMO_MIN_DATED = 2;
/** What the top-up asks the catalogue for: programs whose name says computing, at the schools above. */
const TOP_UP_TERM = "Comput";
const TOP_UP_LIMIT = 100;

/** The fields of a served program the demo reads (`ServedProgram` in programs-source.ts has them all). */
export interface DemoProgram {
  slug: string;
  name: string;
  nameEn: string | null;
  university: string;
  universityId?: string | null;
  deadlines?: readonly CollectedDeadline[] | null;
}

/** A filter of `GET /api/programs`; the same names as `ProgramQuery` in api.ts. */
export interface DemoQuery {
  ids?: string[];
  provider?: string[];
  q?: string;
  hasRequirements?: boolean;
  limit?: number;
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}/;

/** The program's earliest deadline on or after today, or null when it has none ahead. */
function upcoming(program: DemoProgram, today: string): { date: string; url: string } | null {
  const readable = (program.deadlines ?? []).filter((d) => ISO_DATE.test(d.date) && Number.isFinite(daysUntil(d.date, today)));
  const view = deadlineOf({ deadlines: readable }, today);
  return view.state === "upcoming" && view.date && view.url ? { date: view.date, url: view.url } : null;
}

/** The catalogue has this program and no date for it at all. A list the server did not send is not that. */
function undated(program: DemoProgram): boolean {
  return Array.isArray(program.deadlines) && program.deadlines.length === 0;
}

function school(program: DemoProgram): string {
  return program.universityId || program.university;
}

/**
 * The preferred programs in the list's order and, when fewer than `DEMO_DATED` of them have a date
 * ahead, computing programs at the same schools after them, nearest date first.
 *
 * `read` is one `GET /api/programs` with the given filters. A failed top-up is not a failed demo: the
 * list's own programs are returned. A failed first read throws.
 */
export async function loadDemoPrograms(
  today: string,
  read: (query: DemoQuery) => Promise<DemoProgram[]>,
): Promise<DemoProgram[]> {
  const place = new Map(DEMO_PROGRAM_IDS.map((id, index) => [id, index]));
  const listed = (await read({ ids: [...DEMO_PROGRAM_IDS] }))
    .filter((program) => place.has(program.slug))
    .sort((a, b) => place.get(a.slug)! - place.get(b.slug)!);
  if (listed.filter((program) => upcoming(program, today)).length >= DEMO_DATED) return listed;

  const pool = await read({ provider: [...DEMO_SCHOOL_IDS], q: TOP_UP_TERM, hasRequirements: true, limit: TOP_UP_LIMIT }).catch(
    () => [] as DemoProgram[],
  );
  const rank = (program: DemoProgram) => upcoming(program, today)?.date ?? "9999";
  const more = pool
    .filter((program) => !place.has(program.slug))
    .sort((a, b) => (rank(a) < rank(b) ? -1 : rank(a) > rank(b) ? 1 : a.slug < b.slug ? -1 : a.slug > b.slug ? 1 : 0));
  return [...listed, ...more];
}

/** The applicant's side of each dated line, nearest date first. Illustrative, and labelled so on the page. */
const STATES: readonly { status: string; materialsReady: boolean }[] = [
  { status: "applying", materialsReady: false },
  { status: "submitted", materialsReady: true },
  { status: "applying", materialsReady: true },
  { status: "considering", materialsReady: false },
];

/**
 * The demo's records, in the shape the overview draws, or null when the catalogue gives too few.
 *
 * From `programs` in the order given, one program per school: up to `DEMO_DATED` with a deadline
 * ahead (the nearest one due within two weeks first, when there is one, so the urgent colour is on
 * the page), and one the catalogue has no date for. A program whose dates have all passed is not
 * drawn: it is neither upcoming nor unknown.
 */
export function demoRecords(programs: readonly DemoProgram[], today: string): ApplicationRecord[] | null {
  const dated = programs.flatMap((program) => {
    const next = upcoming(program, today);
    return next ? [{ program, ...next }] : [];
  });
  const soon = dated
    .filter((entry) => daysUntil(entry.date, today) <= SOON_DAYS)
    .reduce<(typeof dated)[number] | null>((best, entry) => (best && best.date <= entry.date ? best : entry), null);

  const schools = new Set<string>();
  const chosen: typeof dated = [];
  for (const entry of soon ? [soon, ...dated] : dated) {
    if (chosen.length >= DEMO_DATED) break;
    if (schools.has(school(entry.program))) continue;
    schools.add(school(entry.program));
    chosen.push(entry);
  }
  if (chosen.length < DEMO_MIN_DATED) return null;
  // Array.prototype.sort is stable: programs due on the same day keep the list's order.
  chosen.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  const unknown = programs.find((program) => undated(program) && !schools.has(school(program)));

  const record = (program: DemoProgram, fields: Pick<ApplicationRecord, "status" | "materialsReady" | "deadline" | "sourceUrl">): ApplicationRecord => ({
    id: `demo:${program.slug}`,
    programId: program.slug,
    school: program.university,
    name: program.nameEn || program.name,
    round: null,
    checkedAt: null,
    deadlineOrigin: fields.deadline ? "collected" : null,
    materialNotes: "",
    version: "demo",
    ...fields,
  });
  return [
    ...chosen.map((entry, index) => record(entry.program, { ...STATES[index], deadline: entry.date, sourceUrl: entry.url })),
    ...(unknown ? [record(unknown, { status: "considering", materialsReady: false, deadline: null, sourceUrl: null })] : []),
  ];
}

/** The public page of a demo row's program, where its dates are listed with the pages they came from. */
export function demoProgramHref(record: Pick<ApplicationRecord, "programId">): string {
  return `/programs/${encodeURIComponent(record.programId ?? "")}`;
}
