// Maps the served program catalogue onto the shape the picker renders, and the served portfolio onto
// the items the interface passes around.
//
// The mapping is not decorative. `GET /api/programs` and `web/lib/types.ts` disagree about two things,
// both recorded in `api/app/schemas/program.py` and ruled on in
// `note/superpowers/specs/2026-10-06-stage-2-m2-design.md` §3.6, and neither disagreement is a type
// error on this side:
//
// - the frontend's `Program.name` is the **English** program name, while the route's `name` is the
//   Chinese one and its `nameEn` is the English one. A key-for-key adapter swaps the copy rendered in
//   `PortfolioPicker`, `HomeView` and `FlowView` — user-visible text, silently wrong;
// - `city`, `degreeLevel`, `field`, `duration` and `englishRequirement` are `string | null` on the
//   wire, where `null` means "this catalogue does not know yet". `api/app/schemas/program.py` states
//   why it stays null rather than becoming `""`: an unknown served as an empty string is a claim. The
//   view keeps that meaning and renders the marker below instead.
//
// The field names this file reads are the ones the route serves, copied from a live response and
// bound by `web/lib/programs-source.test.ts` against `web/lib/programs-response.fixture.json`, a
// captured body. That test exists because the same mistake has already happened once in this
// repository: `roadmap-source.ts` read `id`/`label` while the wire said `key`/`title`, and every test
// passed because the fixtures were typed out against the adapter's own declarations. A fixture that
// mirrors the adapter proves nothing; the capture is what makes the test able to fail.

/**
 * One program as the interface renders it is exactly `Program`: this adapter's output is the shared
 * domain type rather than a parallel one.
 *
 * An earlier version of this module declared a `ProgramView` that extended `Program` with the five
 * fields widened, to avoid touching the shared type. It could not compile — an interface cannot widen
 * a property of the one it extends — and the ruling is the other way round anyway: the frontend's
 * declarations were wrong about the wire, so `Program` is what carries the nullability and every
 * consumer of it now answers for the nulls it can see.
 */
import type { PortfolioItem, PortfolioTier, Program, SourceStatus } from "./types";

/**
 * What the interface shows where the catalogue does not know yet.
 *
 * A word rather than an empty string, which is the whole point: `null` on the wire means "nobody has
 * recorded this", and a blank renders as "this program has no city", which is a different and
 * stronger claim. It is a single constant so the marker is one string in one place, and
 * `programs-source.test.ts` pins its value so it cannot quietly become `""`.
 *
 * It belongs to the render sites, not to this module's mapping: `toProgramView` carries the `null`
 * through, so the value the assessment code reads still says "unknown" rather than "the string 未知".
 * The picker and the two portfolio lists are what turn it into a word.
 */
export const UNKNOWN = "未知";

/** One program as `GET /api/programs` serves it, in the camelCase the API serialises. */
export interface ServedProgram {
  /** The program id, which is this side's `slug`. */
  slug: string;
  /** The **Chinese** program name. The frontend's `name` is `nameEn`, not this. */
  name: string;
  /**
   * The English program name, which the frontend calls `name`.
   *
   * Nullable on the wire like the five fields below, and the zero-risk-looking fallback — show the
   * Chinese name rather than the unknown marker — is deliberately not taken: the frontend's `name`
   * is the English one, so putting the Chinese string there swaps the copy §3.6 says it must not.
   */
  nameEn: string | null;
  university: string;
  city: string | null;
  degreeLevel: string | null;
  field: string | null;
  duration: string | null;
  minimumMark: number | null;
  non211MinimumMark: number | null;
  requiresCognate: boolean;
  prerequisites: string[];
  englishRequirement: string | null;
  dataStatus: string;
  source: ServedSource;
}

/**
 * The citation the catalogue serves: where the values came from, what it is called, and whether a
 * human has checked it.
 *
 * Three fields of the frontend's `SourceCitation` are deliberately absent here — `id`, `excerpt` and
 * `verifiedAt` — because the route does not serve them (see `api/app/schemas/program.py`): the
 * excerpt is a manual summary the seed drops, and a verification date stays null until somebody
 * verifies the page. `toProgramView` writes `verifiedAt: null` for exactly that reason and must keep
 * doing so: a date this side supplied would be a verification claim, and the interface surfaces it.
 */
export interface ServedSource {
  url: string;
  title: string;
  status: string;
}

/**
 * The program as a portfolio item carries it: the institution and the English name, the two fields
 * both portfolio views read.
 *
 * Narrower than the wire reference on purpose, and the narrowing is a fix rather than a tidy-up. A
 * portfolio item is built in two places: `toPortfolioItems` projects a row the route served, and
 * `PortfolioPicker` builds the items it is about to confirm out of the catalogue it already holds. The
 * picker's items are what the screen renders when the post-confirmation re-read fails, and the picker
 * cannot answer for the wire's full reference — it holds `Program`s, where the English name lives on
 * `name` (§3.6) and the route's Chinese `name` does not exist at all — so with a full reference in this
 * position those items carried no program and both views printed `未知 · 未知` for programs the
 * catalogue knows. Two fields are exactly what the views print and both builders can fill them
 * truthfully; the route's own `ProgramRef` docstring says the same from the other side, and it serves
 * the other five fields because a read is not a render.
 *
 * `nameEn` is spelled as the wire spells it rather than as `name`: this is the served English name, and
 * a caller that read a `Program`'s own `name` into it is making §3.6's mapping rather than a naming
 * slip. `null` in either field means the catalogue does not know, and the view prints `UNKNOWN`.
 */
export interface PortfolioProgram {
  /** The institution that offers the program, or `null` when the served value is absent or empty. */
  university: string | null;
  /** The English program name, or `null` when the served value is absent or empty. */
  nameEn: string | null;
}

/**
 * The label the two portfolio views print for a portfolio item's program, or `null` when there is none.
 *
 * This is the replacement for `PROGRAMS.find(...)`: the source is the projection `GET /api/applications`
 * serves alongside every row, so a program outside `web/lib/programs.ts` renders as its name rather
 * than as a bare slug, and the two can no longer disagree.
 *
 * `nameEn` and nothing else. The served `name` is the Chinese one, so falling back to it would put a
 * name the server chose for another field onto the label §3.6 says is the English one — the same swap
 * `toProgramView` refuses. A `null` (or an absent key) is therefore answered with `null` rather than
 * with the Chinese name or an empty string, and the render sites turn that into `UNKNOWN`. An empty
 * string is answered the same way: `?? null` alone would let it through, and the card would then print
 * `大学 · ` with nothing after the dot, which is a claim that the program has no name.
 */
export function toProgramLabel(program: PortfolioProgram | null | undefined): string | null {
  const name = program?.nameEn;
  return isFilled(name) ? name : null;
}

/**
 * A served portfolio row's program reference as the two fields the item carries.
 *
 * A projection rather than a copy: the item travels through the application state and the render sites,
 * so what it carries is this module's decision rather than whatever the route happens to put in its
 * projection next. The other five fields the wire serves are dropped here because no view reads them
 * and because `toPortfolioProgram` — the picker's own builder, from a catalogue entry — could not
 * answer for them; see `PortfolioProgram`.
 *
 * An empty served string is projected to `null`: a field the route served as `""` is a field nobody
 * filled in, and `""` is not nullish, so `?? null` alone would carry it to the card as a blank half of
 * the label.
 */
export function toProgramRef(program: ServedProgramRef): PortfolioProgram {
  return {
    university: isFilled(program.university) ? program.university : null,
    nameEn: isFilled(program.nameEn) ? program.nameEn : null,
  };
}

/**
 * A catalogue entry, as the picker holds it, as the same two fields an item carries.
 *
 * This is the builder that closes the fallback path: `PortfolioPicker` draws the confirmed items out of
 * `GET /api/programs`, those items become the rendered portfolio if the re-read after the write fails,
 * and without a program on them the two views printed the unknown marker for the programs the applicant
 * had just chosen. `Program.name` is the served English name (`toProgramView` wrote it from `nameEn`,
 * §3.6), so it fills this side's `nameEn`, and `Program.university` is the served institution.
 */
export function toPortfolioProgram(program: Program): PortfolioProgram {
  return {
    university: isFilled(program.university) ? program.university : null,
    nameEn: isFilled(program.name) ? program.name : null,
  };
}

/**
 * One program the portfolio row names, as `GET /api/applications` serves it under `program`.
 *
 * The wire's own reference, seven fields wide, which is what `toProgramRef` narrows into the
 * `PortfolioProgram` an item carries. The two are deliberately different shapes: this one describes what
 * the route answered, and the item's describes what the views print.
 */
export interface ServedProgramRef {
  slug: string;
  name: string;
  nameEn: string | null;
  university: string;
  city: string | null;
  degreeLevel: string | null;
  dataStatus: string;
}

/** One portfolio row as `ApplicationOut` serves it: the columns, plus the program the row names. */
export interface ServedApplication {
  id: string;
  /** The program the row is a choice of, which is this side's `programSlug`. */
  programId: string;
  tier: string;
  status: string;
  isPrimary: boolean;
  officialDeadline: string | null;
  deadlineSourceUrl: string | null;
  needsReview: boolean;
  origin: string;
  /**
   * The program the row names, or `null` when the catalogue cannot answer for it.
   *
   * The route serves `null` rather than dropping the row or inventing copy. `toPortfolioItems` narrows
   * it through `toProgramRef` onto the item the interface passes around — `null` included, never
   * `undefined` — and the two portfolio views draw the institution and the name from it through
   * `toProgramLabel`, so the row no longer depends on `web/lib/programs.ts` to be renderable.
   */
  program: ServedProgramRef | null;
  createdAt: string;
  updatedAt: string;
}

/** One row of the `PUT /api/applications` payload, as `ApplicationIn` reads it. */
export interface ApplicationRow {
  programId: string;
  tier: PortfolioTier;
  isPrimary: boolean;
  needsReview: boolean;
}

/**
 * What one replacement did, as `ApplicationReplaceResult` serves it.
 *
 * Declared here with the other portfolio wire shapes rather than in `api.ts`, because all three are
 * one contract: what the route reads, what it returns and what it reports. `removed` counts the rows
 * the payload no longer names, so a caller checking its own work compares `created + updated + kept`
 * against the list it sent.
 */
export interface ApplicationReplaceResult {
  created: number;
  updated: number;
  kept: number;
  removed: number;
}

/** Whether the value the wire sent is a string with at least one character in it. */
function isFilled(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

/**
 * A string field the response must carry, or a refusal naming it.
 *
 * `slug`, `university` and the citation's url and title are the fields the interface cannot do its
 * job without: the slug is the key every portfolio row is resolved by, and the url is the link the
 * applicant follows to check the values against the official page. A missing one is a body this side
 * cannot render, and refusing it here is what turns "the catalogue read failed" into the page's own
 * answer instead of a link with `undefined` in its href.
 */
function requiredText(value: unknown, field: string): string {
  if (!isFilled(value)) throw new Error(`读取项目目录失败：条目缺少 ${field}`);
  return value;
}

/**
 * The served status as the union the domain type declares.
 *
 * An unknown status is reported as 待核验 rather than as 已核验, and that direction is the whole
 * rule: `eligibility.ts` treats `已核验` as grounds to stop warning the applicant that the conclusion
 * rests on unverified data, so a status this build has never heard of must not be read as verified.
 * The two known values pass through unchanged, so a genuinely verified catalogue row still says so.
 */
function toSourceStatus(value: unknown): SourceStatus {
  return value === "已核验" ? "已核验" : "待核验";
}

/**
 * One served program as the interface renders it.
 *
 * The five nullable fields stay `null` — they are not defaulted to `""` here, and no render site may
 * do it there: see `UNKNOWN` and this module's header. An empty string is read as the same unknown:
 * `""` is not nullish, so `?? null` would carry it through to a card that then prints `大学 · ` with
 * nothing after the dot, and a body may spell "nobody filled this in" either way. `minimumMark` and
 * `non211MinimumMark` are already nullable on this side, and `null` there is a value the assessment code
 * reads as "no threshold to compare against" rather than a missing answer to fill in.
 *
 * The citation's `id`, `excerpt` and `verifiedAt` are written here because the wire does not carry
 * them. `id` is the program slug, which is the one identifier this side has for the program and the
 * key the seed derives its source ids from; `excerpt` is `""` rather than a summary this side made
 * up, because the seed drops the frontend's manual excerpt and nothing renders it; `verifiedAt` is
 * `null`, which is the same "nobody has verified this page" the route's own model holds.
 */
export function toProgramView(program: ServedProgram): Program {
  return {
    slug: requiredText(program.slug, "slug"),
    university: requiredText(program.university, "university"),
    name: isFilled(program.nameEn) ? program.nameEn : null,
    city: isFilled(program.city) ? program.city : null,
    degreeLevel: isFilled(program.degreeLevel) ? program.degreeLevel : null,
    field: isFilled(program.field) ? program.field : null,
    duration: isFilled(program.duration) ? program.duration : null,
    minimumMark: program.minimumMark ?? null,
    non211MinimumMark: program.non211MinimumMark ?? null,
    requiresCognate: program.requiresCognate ?? false,
    prerequisites: program.prerequisites ?? [],
    englishRequirement: isFilled(program.englishRequirement) ? program.englishRequirement : null,
    source: {
      id: program.slug,
      title: requiredText(program.source?.title, "source.title"),
      url: requiredText(program.source?.url, "source.url"),
      excerpt: "",
      verifiedAt: null,
      status: toSourceStatus(program.source?.status),
    },
    dataStatus: toSourceStatus(program.dataStatus),
  };
}

/**
 * The served portfolio as the items the interface passes around.
 *
 * `programSlug` is the wire's `programId`: the route keys a portfolio row by the program it names, so
 * the program id is the identity the interface already uses for a choice.
 *
 * `confirmed` is written as `true` for every row rather than carried from the wire, and that is not a
 * guess: the stored portfolio *is* the set of choices the applicant confirmed. The route answers a
 * replacement with counts rather than rows, so a returned portfolio is a portfolio that was written,
 * and the one row state the field could otherwise describe — "selected on this screen, not yet sent" —
 * lives in the picker's own `picked` map and never reaches the server.
 *
 * `needsReview` and `isPrimary` are carried through, not dropped: the second is a fact the table
 * enforces (at most one row per applicant, `uq_applications_one_primary_per_client`) and the write
 * below restates it rather than guessing, so a replacement must not silently release a first choice
 * the applicant already has.
 *
 * `program` is the projection the route serves alongside the row, projected onto the item through
 * `toProgramRef` because the two portfolio views render it: they resolved the row through
 * `web/lib/programs.ts` until M2d, which turned a program the constants array does not carry into a bare
 * slug. It is written for every row, `null` included, so a view can tell "the catalogue did not answer
 * for this one" apart from a field this adapter forgot; `toProgramLabel` turns it into the label, and
 * `null` renders as `UNKNOWN`. What it carries is the narrower `PortfolioProgram` rather than the wire
 * reference: the picker's own items — the ones the views render when the post-confirmation re-read
 * fails — have to answer the same two fields, and the picker has no Chinese name to fill a full
 * reference with.
 */
export function toPortfolioItems(rows: ServedApplication[]): PortfolioItem[] {
  return (rows ?? []).map((row) => ({
    programSlug: row.programId,
    program: row.program ? toProgramRef(row.program) : null,
    tier: row.tier as PortfolioTier,
    confirmed: true,
    needsReview: row.needsReview,
    isPrimary: row.isPrimary,
  }));
}

/**
 * The items on screen as the payload `PUT /api/applications` reads.
 *
 * Only the four fields `ApplicationIn` carries, and only those: the schema sets `extra="forbid"`, so
 * a payload that sent `origin` — which the server writes itself — or `status` would be refused with a
 * 422 rather than silently ignored. `isPrimary` and `needsReview` are stated for every row because a
 * whole replacement is a statement about the whole list: an omitted `isPrimary` means `False` (a
 * controller ruling recorded in `api/app/services/applications.py`), and the `confirmed` field of an
 * item is not on the wire at all — everything in this payload is confirmed by construction.
 */
export function toApplicationRows(items: PortfolioItem[]): ApplicationRow[] {
  return (items ?? []).map((item) => ({
    programId: item.programSlug,
    tier: item.tier,
    isPrimary: item.isPrimary ?? false,
    needsReview: item.needsReview ?? false,
  }));
}
