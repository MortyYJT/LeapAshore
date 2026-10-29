// The background assessment's rules (spec background-assessment), as pure functions the assessment page,
// the result page and the return-visit redirect share.
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

export type RequiredField =
  | "educationLevel"
  | "schoolOrigin"
  | "major"
  | "gpaScore"
  | "targetDegree"
  | "targetField"
  | "englishScore"
  | "intake";

/** The required fields in form order, each with the reason the form shows beside it when it is missing. */
export const REQUIRED_FIELDS: { field: RequiredField; label: string; reason: string }[] = [
  { field: "educationLevel", label: "现在的学历", reason: "决定申请哪一级学位" },
  { field: "schoolOrigin", label: "学校在哪里", reason: "决定按哪一类院校比较均分" },
  { field: "major", label: "专业", reason: "用来对照专业背景要求" },
  { field: "gpaScore", label: "加权均分和分制", reason: "分档要和均分门槛比较" },
  { field: "targetDegree", label: "申请学位", reason: "决定看哪一类项目" },
  { field: "targetField", label: "申请方向", reason: "测评结果按方向列出项目" },
  { field: "englishScore", label: "英语成绩", reason: "分档要和语言要求比较；还没考也请选上" },
  { field: "intake", label: "入学时间", reason: "路线图从入学时间往前倒推，不填就不排日期" },
];

function answered(profile: Profile, field: RequiredField): boolean {
  switch (field) {
    case "gpaScore":
      // A mark means nothing without its scale.
      return profile.gpaScore !== null && profile.gpaScale !== null;
    case "major":
    case "englishScore":
    case "intake":
      return profile[field].trim() !== "";
    default:
      return profile[field] !== null;
  }
}

export function missingRequired(profile: Profile): typeof REQUIRED_FIELDS {
  return REQUIRED_FIELDS.filter(({ field }) => !answered(profile, field));
}

/** Complete exactly when the server profile holds every required field. */
export function isAssessmentComplete(profile: Profile): boolean {
  return missingRequired(profile).length === 0;
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
