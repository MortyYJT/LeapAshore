/**
 * Tiering a program by how far its collected official requirements are met (spec: program-tiering).
 *
 * A tier describes requirements met, never an admission chance. Only two requirements are compared:
 * the academic threshold (a percentage) and the IELTS overall. Everything else, and any requirement that
 * is stored only as text or is missing on either side, is neither met nor unmet: it is listed as
 * `去官网确认` with the program's official page. A program with nothing comparable is not tiered at all
 * and is counted under `要求未收录`.
 */
import type { Program, StudyArea } from './types.ts';

export const SAFETY_AVERAGE_MARGIN = 5;
export const REACH_AVERAGE_SHORTFALL = 3;
export const REACH_IELTS_SHORTFALL = 0.5;

export type Tier = '保底' | '稳妥' | '冲刺' | '不满足';
export const TIERS: Tier[] = ['保底', '稳妥', '冲刺', '不满足'];

/** The applicant's institution as the thresholds see it. `other` is a mainland school outside 985/211. */
export type Institution = '985' | '211' | 'other' | 'overseas' | 'unknown';

export interface Applicant {
  /** Undergraduate average on a 100 scale, or null when not given. */
  average: number | null;
  ielts: number | null;
  institution: Institution;
}

export type CheckKind = 'academic' | 'english';

export interface Check {
  kind: CheckKind;
  required: number;
  actual: number;
  /** Positive when the applicant is short of the requirement. */
  shortfall: number;
}

export interface Confirm {
  kind: CheckKind;
  label: string;
  url: string;
}

export interface TierResult {
  program: Program;
  /** null: nothing could be compared, so the program is not tiered. */
  tier: Tier | null;
  checks: Check[];
  confirm: Confirm[];
}

/**
 * The IELTS overall from the stored English line, but only in its minimum form (`IELTS 6.5…`).
 * A recommended score is stored as `建议雅思 …` precisely so that it is never read as a threshold.
 */
export function parseIeltsOverall(requirement: string | null): number | null {
  if (!requirement) return null;
  const match = /(?:^|；)\s*IELTS\s*(\d(?:\.\d)?)/.exec(requirement);
  return match ? Number(match[1]) : null;
}

/** The academic threshold that applies to this applicant, or null when it must be confirmed. */
function academicThreshold(applicant: Applicant, program: Program): number | null {
  switch (applicant.institution) {
    case '985':
    case '211':
      return program.minimumMark;
    case 'other':
      // The 985/211 threshold is never applied to a school outside those lists.
      return program.non211MinimumMark;
    default:
      return null; // overseas or unknown: no uniform baseline
  }
}

export function tierProgram(applicant: Applicant, program: Program): TierResult {
  const checks: Check[] = [];
  const confirm: Confirm[] = [];
  const url = program.source.url;

  const hasAcademic = program.minimumMark !== null || program.non211MinimumMark !== null;
  const threshold = academicThreshold(applicant, program);
  if (threshold !== null && applicant.average !== null) {
    checks.push({ kind: 'academic', required: threshold, actual: applicant.average, shortfall: threshold - applicant.average });
  } else if (hasAcademic) {
    confirm.push({ kind: 'academic', label: '学术要求', url });
  }

  const ielts = parseIeltsOverall(program.englishRequirement);
  if (ielts !== null && applicant.ielts !== null) {
    checks.push({ kind: 'english', required: ielts, actual: applicant.ielts, shortfall: ielts - applicant.ielts });
  } else if (program.englishRequirement) {
    confirm.push({ kind: 'english', label: '语言要求', url });
  }

  return { program, tier: decideTier(checks), checks, confirm };
}

function decideTier(checks: Check[]): Tier | null {
  if (checks.length === 0) return null;
  const unmet = checks.filter(c => c.shortfall > 0);
  if (unmet.length === 0) {
    const academic = checks.find(c => c.kind === 'academic');
    return academic && -academic.shortfall >= SAFETY_AVERAGE_MARGIN ? '保底' : '稳妥';
  }
  if (unmet.length === 1) {
    const [only] = unmet;
    const limit = only.kind === 'academic' ? REACH_AVERAGE_SHORTFALL : REACH_IELTS_SHORTFALL;
    if (only.shortfall <= limit) return '冲刺';
  }
  return '不满足';
}

export interface TieredPrograms {
  tiers: Record<Tier, TierResult[]>;
  /** Programs in the target field with no comparable requirement collected. */
  notCollected: Program[];
  notCollectedCount: number;
}

export function tierPrograms(applicant: Applicant, programs: Program[], targetField: StudyArea | null): TieredPrograms {
  const tiers = Object.fromEntries(TIERS.map(t => [t, [] as TierResult[]])) as Record<Tier, TierResult[]>;
  const notCollected: Program[] = [];
  for (const program of programs) {
    const result = tierProgram(applicant, program);
    if (result.tier) tiers[result.tier].push(result);
    else if (!targetField || program.field === targetField) notCollected.push(program);
  }
  return { tiers, notCollected, notCollectedCount: notCollected.length };
}
