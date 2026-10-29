import assert from "node:assert/strict";
import { test } from "node:test";

import {
  EMPTY_PROFILE,
  englishScoreOf,
  isAssessmentComplete,
  missingRequired,
  parseEnglishScore,
  toApplicant,
} from "./assess.ts";
import type { Profile } from "./types.ts";

const complete: Profile = {
  ...EMPTY_PROFILE,
  educationLevel: "本科",
  schoolOrigin: "国内",
  schoolName: "北京邮电大学",
  domesticTier: "211",
  major: "软件工程",
  gpaScore: 85,
  gpaScale: 100,
  targetDegree: "授课型硕士",
  targetField: "计算机与数据",
  englishScore: "IELTS 6.5",
  intake: "2027 S2",
};

test("an assessment is complete exactly when every required field is held", () => {
  assert.equal(isAssessmentComplete(complete), true);
  assert.deepEqual(missingRequired(complete), []);
  // The school name and the budget may be left empty.
  assert.equal(isAssessmentComplete({ ...complete, schoolName: "", domesticTier: null, annualBudgetCny: null }), true);
});

test("a missing intake blocks completion and names the field", () => {
  const missing = missingRequired({ ...complete, intake: "" });
  assert.deepEqual(missing.map((m) => m.field), ["intake"]);
  assert.ok(missing[0].reason.length > 0);
  assert.equal(isAssessmentComplete({ ...complete, intake: "" }), false);
});

test("a mark without its scale is not a complete answer", () => {
  assert.deepEqual(missingRequired({ ...complete, gpaScale: null }).map((m) => m.field), ["gpaScore"]);
});

test("a listed 211 school on a 100 scale is compared on both requirements", () => {
  assert.deepEqual(toApplicant(complete), { average: 85, ielts: 6.5, institution: "211" });
});

test("an undisclosed or unlisted school has an unknown tier, never a guessed one", () => {
  assert.equal(toApplicant({ ...complete, schoolName: "" }).institution, "unknown");
  assert.equal(toApplicant({ ...complete, schoolName: "某某学院", domesticTier: null }).institution, "unknown");
  assert.equal(toApplicant({ ...complete, domesticTier: "双非" }).institution, "other");
  assert.equal(toApplicant({ ...complete, schoolOrigin: "海外", domesticTier: null }).institution, "overseas");
});

test("a mark on another scale is not converted into a percentage", () => {
  assert.equal(toApplicant({ ...complete, gpaScore: 3.6, gpaScale: 4 }).average, null);
});

test("only an IELTS score is compared; another test is left for the official page", () => {
  assert.equal(toApplicant({ ...complete, englishScore: "TOEFL 100" }).ielts, null);
  assert.equal(toApplicant({ ...complete, englishScore: "还没考" }).ielts, null);
  assert.equal(toApplicant({ ...complete, englishScore: "雅思 7" }).ielts, 7);
});

test("the English score round-trips between the form and the stored string", () => {
  assert.equal(englishScoreOf("IELTS", "6.5"), "IELTS 6.5");
  assert.equal(englishScoreOf("NONE", ""), "还没考");
  assert.deepEqual(parseEnglishScore("TOEFL 95"), { test: "TOEFL", score: "95" });
  assert.deepEqual(parseEnglishScore("还没考"), { test: "NONE", score: "" });
  assert.deepEqual(parseEnglishScore("雅思 7.0"), { test: "IELTS", score: "7.0" });
  assert.deepEqual(parseEnglishScore(""), { test: "", score: "" });
});
