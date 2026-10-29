// The profile rules (spec profile-basics), as pure functions the info step, the tiers page and the
// return-visit redirect share.
//
// Two rules decide what the system may compare, and both refuse to invent a value:
// - only a mark on a 100 scale is compared with a percentage threshold; a 4.0 or 5.0 mark has no official
//   conversion, so the academic requirement goes to 去官网确认 instead;
// - only an IELTS score is compared with an IELTS threshold; another test is left for the official page.

import type { Applicant, Institution } from "./tiers.ts";
import type { Profile } from "./types.ts";

/** A profile with nothing answered. No field is pre-filled: an unanswered intake stays unanswered. */
export const EMPTY_PROFILE: Profile = {
  educationLevel: null,
  schoolOrigin: null,
  schoolName: "",
  domesticTier: null,
  overseasBand: null,
  major: "",
  gpaScore: null,
  gpaScale: null,
  targetDegree: null,
  targetField: null,
  englishScore: "",
  annualBudgetCny: null,
  intake: "",
};

/**
 * The four facts the tiers compare (openspec account-login, spec profile-basics): the undergraduate
 * school, the average mark with its scale, the target field and the English score. They are asked for
 * once, after the first registration, and can be skipped; every other field is edited on 我的.
 */
export type BasicField = "school" | "gpa" | "targetField" | "englishScore";

export const BASIC_FIELDS: { field: BasicField; label: string }[] = [
  { field: "school", label: "本科院校" },
  { field: "gpa", label: "均分和分制" },
  { field: "targetField", label: "申请方向" },
  { field: "englishScore", label: "英语成绩" },
];

function answeredBasic(profile: Profile, field: BasicField): boolean {
  switch (field) {
    case "school":
      return profile.schoolOrigin !== null && profile.schoolName.trim() !== "";
    case "gpa":
      // A mark means nothing without its scale.
      return profile.gpaScore !== null && profile.gpaScale !== null;
    case "targetField":
      return profile.targetField !== null;
    case "englishScore":
      return profile.englishScore.trim() !== "";
  }
}

export function missingBasics(profile: Profile): typeof BASIC_FIELDS {
  return BASIC_FIELDS.filter(({ field }) => !answeredBasic(profile, field));
}

/** True when the tiers have everything they compare; otherwise the tiers page asks to 先补信息. */
export function hasBasics(profile: Profile): boolean {
  return missingBasics(profile).length === 0;
}

function institutionOf(profile: Profile): Institution {
  if (profile.schoolOrigin === "海外") return "overseas";
  // An undisclosed school has no tier, whatever a stale tier field says.
  if (profile.schoolOrigin !== "国内" || profile.schoolName.trim() === "") return "unknown";
  switch (profile.domesticTier) {
    case "985":
    case "211":
      return profile.domesticTier;
    case "双非":
    case "专科":
      return "other";
    default:
      return "unknown"; // a school the Ministry list does not hold
  }
}

/** The applicant as the tier rule compares them. */
export function toApplicant(profile: Profile): Applicant {
  const average = profile.gpaScale === 100 && profile.gpaScore !== null ? profile.gpaScore : null;
  const english = parseEnglishScore(profile.englishScore);
  const ielts = english.test === "IELTS" && english.score !== "" ? Number(english.score) : null;
  return {
    average,
    ielts: ielts !== null && Number.isFinite(ielts) ? ielts : null,
    institution: institutionOf(profile),
  };
}

export type EnglishTest = "IELTS" | "TOEFL" | "PTE" | "NONE" | "";

export const ENGLISH_TESTS: { value: Exclude<EnglishTest, "">; label: string }[] = [
  { value: "IELTS", label: "雅思" },
  { value: "TOEFL", label: "托福" },
  { value: "PTE", label: "PTE" },
  { value: "NONE", label: "还没考" },
];

const NOT_TAKEN = "还没考";

/** The stored English score, from the form's test and score. */
export function englishScoreOf(test: EnglishTest, score: string): string {
  if (test === "NONE") return NOT_TAKEN;
  if (test === "") return "";
  return `${test} ${score.trim()}`.trim();
}

/** The form's test and score, from a stored English score (including the older 雅思 / 托福 spellings). */
export function parseEnglishScore(stored: string): { test: EnglishTest; score: string } {
  const text = stored.trim();
  if (text === "") return { test: "", score: "" };
  if (text === NOT_TAKEN) return { test: "NONE", score: "" };
  const match = /^(IELTS|雅思|TOEFL|托福|PTE)\s*([\d.]*)/i.exec(text);
  if (!match) return { test: "", score: "" };
  const name = match[1].toUpperCase();
  const test: EnglishTest = name === "雅思" || name === "IELTS" ? "IELTS" : name === "托福" || name === "TOEFL" ? "TOEFL" : "PTE";
  return { test, score: match[2] };
}
