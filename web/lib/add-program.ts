// Adding a school-library program to 我的申请 in one step (components/shell/AddProgram.tsx).
//
// The rules the control, the rail and the toast share, as pure functions: what a program's control
// shows, the record drawn while the add is on its way, where 去看看 leads, and what the toast says
// about the deadline the record took. The write itself is `addCatalogueProgram` in
// `application-records.ts`; the server is idempotent by program, so a second add answers with the
// record already held and nothing here has to guard against two rows.

import type { ApplicationRecord } from "./application-records.ts";
import { hasBasics, toApplicant } from "./assess.ts";
import { deadlineOf } from "./deadlines.ts";
import { tierProgram } from "./tiers.ts";
import type { PortfolioTier, Profile, Program } from "./types.ts";

/** The record a catalogue program is listed under in 我的申请 (the server's `catalog:` key). */
export function catalogueRecordId(slug: string): string {
  return `catalog:${slug}`;
}

/** Where 去看看 and 已加入 lead: the record on 我的申请, which scrolls to it and marks it. */
export function recordHref(id: string): string {
  return `/applications?record=${encodeURIComponent(id)}`;
}

/** The record 我的申请 was opened for (`?record=`), or null. */
export function arrivalOf(search: string): string | null {
  return new URLSearchParams(search).get("record");
}

/**
 * What one program's control shows.
 * - `add`: not among the applications (or they are not known yet);
 * - `adding`: the add is on its way; the control already reads as added, and does nothing;
 * - `added`: an application of this program exists; the control leads to it.
 */
export type AddState = "add" | "adding" | "added";

export function addState(records: readonly ApplicationRecord[] | null, adding: ReadonlySet<string>, slug: string): AddState {
  if (adding.has(slug)) return "adding";
  return records?.some((record) => record.programId === slug) ? "added" : "add";
}

const BAND: Record<string, PortfolioTier> = { 保底: "保", 稳妥: "稳", 冲刺: "冲" };

/** The band a program is stored with, and whether it is flagged 未经系统分档 (not the tiers' own). */
export interface Band {
  tier: PortfolioTier;
  needsReview: boolean;
}

/**
 * The band the program is stored with. When the tiers give one against the applicant's background
 * (the one the program page shows), that band. Otherwise it is flagged for review, as the portfolio
 * flags a band the applicant picked: 冲 when the tiers found the applicant short of the stated
 * requirement (不满足), and 稳 when they could not compare (the background lacks one of the four
 * basics, or the program states nothing comparable). No band is presented as the system's when it
 * is not.
 */
export function bandFor(profile: Profile | null | undefined, program: Program): Band {
  if (!profile || !hasBasics(profile)) return { tier: "稳", needsReview: true };
  const tier = tierProgram(toApplicant(profile), program).tier;
  if (tier === "不满足") return { tier: "冲", needsReview: true };
  return tier ? { tier: BAND[tier], needsReview: false } : { tier: "稳", needsReview: true };
}

/**
 * The record drawn in the rail, the overview and the roadmap while the add is on its way: what the
 * server will answer, from the program on screen. Its deadline is the catalogue's own, picked by the
 * same rule the server's read uses (the earliest one not yet passed, else the latest); a program with
 * none has none. The server's answer replaces it.
 */
export function provisionalRecord(program: Program, today: string): ApplicationRecord {
  const deadline = deadlineOf({ deadlines: program.deadlines }, today);
  return {
    id: catalogueRecordId(program.slug),
    programId: program.slug,
    school: program.university,
    name: program.name ?? "未知项目",
    round: null,
    status: "considering",
    deadline: deadline.date,
    sourceUrl: deadline.url,
    checkedAt: null,
    deadlineOrigin: deadline.origin,
    materials: [],
    materialsExtracted: false,
    materialsPageUrl: null,
    customMaterials: [],
    materialsDone: 0,
    materialsTotal: 0,
    materialsReady: false,
    materialNotes: "",
    version: "",
  };
}

/** The records with this one in place of the record of the same id, or added at the end. */
export function withRecord(records: readonly ApplicationRecord[], record: ApplicationRecord): ApplicationRecord[] {
  return records.some((r) => r.id === record.id)
    ? records.map((r) => (r.id === record.id ? record : r))
    : [...records, record];
}

export function withoutRecord(records: readonly ApplicationRecord[], id: string): ApplicationRecord[] {
  return records.filter((r) => r.id !== id);
}

/** The toast's line under the program: the deadline the record took, and where it came from. */
export function deadlineNote(record: ApplicationRecord): string {
  if (!record.deadline) return "截止日期待确认";
  if (record.checkedAt) return `截止 ${record.deadline}`;
  if (record.deadlineOrigin === "collected") return `截止 ${record.deadline} · 学校库采集，请复核`;
  return `截止 ${record.deadline} · 待自行核对`;
}
