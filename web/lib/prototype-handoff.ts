/**
 * The hand-off from the onboarding questionnaire to the prototype.
 *
 * A first visit runs the onboarding on `/`; when it finishes, the applicant lands in `/prototype`
 * with the answers already filled in as the prototype's assessment background. A cookie marks the
 * visit as done, and `proxy.ts` sends a returning visitor straight to `/prototype`.
 */

import type { Background, InstitutionTier } from "../prototype-fixtures/data";
import type { Profile } from "./types";

export const ONBOARDED_COOKIE = "leapashore_onboarded";
const ONE_YEAR_SECONDS = 60 * 60 * 24 * 365;

/** Mark onboarding as done. Readable by the proxy, so it is a plain (not httpOnly) cookie. */
export function markOnboarded(): void {
  document.cookie = `${ONBOARDED_COOKIE}=1; path=/; max-age=${ONE_YEAR_SECONDS}; samesite=lax`;
}

/** Forget the mark, so the next visit to `/` runs the onboarding again. */
export function clearOnboarded(): void {
  document.cookie = `${ONBOARDED_COOKIE}=; path=/; max-age=0; samesite=lax`;
}

const TIER: Record<string, InstitutionTier> = { "985": "985", "211": "211", 双非: "其他", 专科: "其他" };

// The prototype's three example fields, matched from the free-text major the onboarding collects.
const FIELD_KEYWORDS: [string, string[]][] = [
  ["计算机与信息技术", ["计算机", "软件", "信息", "数据", "人工智能", "网络", "电子", "通信", "computer", "software"]],
  ["商科", ["商", "金融", "会计", "经济", "管理", "市场", "财务", "business", "finance"]],
  ["教育", ["教育", "education"]],
];

function fieldOf(major: string): string | null {
  const text = major.toLowerCase();
  for (const [field, words] of FIELD_KEYWORDS) {
    if (words.some((w) => text.includes(w))) return field;
  }
  return null;
}

/** An IELTS overall score from free text such as "IELTS 6.5" or "雅思7"; anything else is unknown. */
export function ieltsOf(englishScore: string): number | null {
  const match = /(?:ielts|雅思)\s*[:：]?\s*(\d(?:\.\d)?)/i.exec(englishScore);
  if (!match) return null;
  const score = Number(match[1]);
  return score >= 0 && score <= 9 ? score : null;
}

/** The average on a 100-point scale, or unknown when either half is missing. */
export function averageOf(score: number | null, scale: number | null): number | null {
  if (score === null || scale === null || scale <= 0) return null;
  return Math.round((score / scale) * 10000) / 100;
}

/** Translate onboarding answers into the prototype's background. Unknown stays null, never zero. */
export function toPrototypeBackground(profile: Profile): Background {
  return {
    institution: profile.schoolName.trim(),
    institutionTier: profile.domesticTier ? (TIER[profile.domesticTier] ?? null) : null,
    average: averageOf(profile.gpaScore, profile.gpaScale),
    major: fieldOf(profile.major),
    ielts: ieltsOf(profile.englishScore),
  };
}
