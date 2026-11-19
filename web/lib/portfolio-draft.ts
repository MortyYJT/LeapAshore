// The portfolio draft (spec application-portfolio): what the applicant has added on the result page and
// edited on /portfolio but not yet confirmed. It lives in session storage, so it survives moving between
// those two pages and nothing reaches the server until the confirm action writes it whole. Leaving
// without confirming changes nothing on the server, which is the spec's own scenario.

import type { PortfolioProgram } from "./programs-source.ts";
import type { ApplicationStatus, PortfolioItem, PortfolioTier } from "./types.ts";

export const DRAFT_KEY = "leapashore-portfolio-draft";
/** The saved rows the stored draft was first made from; see `writeDraft`. */
export const DRAFT_BASE_KEY = "leapashore-portfolio-draft-base";

/** One saved portfolio row as it was read: what `PUT /api/applications` takes in `base`. */
export interface BaseRow {
  id: string;
  version: number;
}

/** The base a replacement built from these saved items states. Items the server never stored have none. */
export function baseOf(saved: PortfolioItem[]): BaseRow[] {
  return saved.flatMap((row) =>
    row.rowId !== undefined && row.version !== undefined ? [{ id: row.rowId, version: row.version }] : [],
  );
}

const TIERS: readonly PortfolioTier[] = ["冲", "稳", "保"];
const STATUSES: readonly ApplicationStatus[] = [
  "considering", "applying", "submitted", "offered", "rejected", "excluded",
];

export interface DraftAddition {
  programSlug: string;
  program: PortfolioProgram | null;
  tier: PortfolioTier;
  /** True when the system did not tier the program and the band is the applicant's own pick. */
  needsReview: boolean;
}

export function addToDraft(draft: PortfolioItem[], addition: DraftAddition): PortfolioItem[] {
  const existing = draft.find((row) => row.programSlug === addition.programSlug);
  if (existing) {
    return draft.map((row) =>
      row.programSlug === addition.programSlug
        ? { ...row, tier: addition.tier, needsReview: addition.needsReview }
        : row,
    );
  }
  return [
    ...draft,
    {
      programSlug: addition.programSlug,
      program: addition.program,
      tier: addition.tier,
      needsReview: addition.needsReview,
      confirmed: true,
      isPrimary: false,
      status: "considering",
    },
  ];
}

export function removeFromDraft(draft: PortfolioItem[], programSlug: string): PortfolioItem[] {
  return draft.filter((row) => row.programSlug !== programSlug);
}

/** Mark one program as the first choice, or none with `null`. At most one row is ever marked. */
export function setPrimary(draft: PortfolioItem[], programSlug: string | null): PortfolioItem[] {
  return draft.map((row) => ({ ...row, isPrimary: row.programSlug === programSlug }));
}

export function setStatus(draft: PortfolioItem[], programSlug: string, status: ApplicationStatus): PortfolioItem[] {
  return draft.map((row) => (row.programSlug === programSlug ? { ...row, status } : row));
}

function signature(rows: PortfolioItem[]): string {
  return JSON.stringify(
    rows
      .map((r) => [r.programSlug, r.tier, r.status ?? "considering", r.isPrimary ?? false, r.needsReview ?? false])
      .sort((a, b) => String(a[0]).localeCompare(String(b[0]))),
  );
}

/** Whether confirming the draft would change the saved portfolio. Row order is not a change. */
export function draftChanged(draft: PortfolioItem[], saved: PortfolioItem[]): boolean {
  return signature(draft) !== signature(saved);
}

function isItem(value: unknown): value is PortfolioItem {
  const row = value as Partial<PortfolioItem> | null;
  return (
    typeof row?.programSlug === "string" &&
    TIERS.includes(row.tier as PortfolioTier) &&
    (row.status === undefined || STATUSES.includes(row.status))
  );
}

/** The stored draft, or null when there is none or the stored copy cannot be read. */
export function readDraft(storage: Storage): PortfolioItem[] | null {
  const raw = storage.getItem(DRAFT_KEY);
  if (raw === null) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) && parsed.every(isItem) ? parsed : null;
  } catch {
    return null;
  }
}

/**
 * Store the draft, and with the first write the saved portfolio it was made from.
 *
 * The base is what the confirm action sends so the server can refuse a draft made from a portfolio
 * another device has since changed. It is recorded once per draft and kept until `clearDraft`: the
 * draft outlives a page load, and a page that read the newer portfolio and then stated it as the
 * base would overwrite the other device's change without either side being told.
 */
export function writeDraft(storage: Storage, draft: PortfolioItem[], saved?: PortfolioItem[] | null): void {
  if (saved && storage.getItem(DRAFT_BASE_KEY) === null) writeDraftBase(storage, baseOf(saved));
  storage.setItem(DRAFT_KEY, JSON.stringify(draft));
}

/** The saved rows the stored draft was made from, or null when that was never recorded. */
export function readDraftBase(storage: Storage): BaseRow[] | null {
  const raw = storage.getItem(DRAFT_BASE_KEY);
  if (raw === null) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    const valid =
      Array.isArray(parsed) &&
      parsed.every((row) => typeof row?.id === "string" && typeof row?.version === "number");
    return valid ? (parsed as BaseRow[]) : null;
  } catch {
    return null;
  }
}

/** Restate the base, after a refused confirm showed the applicant the portfolio the server holds. */
export function writeDraftBase(storage: Storage, base: BaseRow[]): void {
  storage.setItem(DRAFT_BASE_KEY, JSON.stringify(base));
}

export function clearDraft(storage: Storage): void {
  storage.removeItem(DRAFT_KEY);
  storage.removeItem(DRAFT_BASE_KEY);
}
