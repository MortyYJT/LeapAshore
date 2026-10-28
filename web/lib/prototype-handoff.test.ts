import assert from "node:assert/strict";
import { test } from "node:test";

import { averageOf, ieltsOf, toPrototypeBackground } from "./prototype-handoff.ts";
import type { Profile } from "./types.ts";

const base: Profile = {
  educationLevel: "本科",
  schoolOrigin: "国内",
  schoolName: "武汉大学",
  domesticTier: "985",
  overseasBand: null,
  major: "计算机科学与技术",
  gpaScore: 85,
  gpaScale: 100,
  targetDegree: null,
  targetField: null,
  englishScore: "IELTS 7.0",
  annualBudgetCny: null,
  intake: "",
} as Profile;

test("a complete onboarding becomes a complete background", () => {
  assert.deepEqual(toPrototypeBackground(base), {
    institution: "武汉大学",
    institutionTier: "985",
    average: 85,
    major: "计算机与信息技术",
    ielts: 7,
  });
});

test("双非 and 专科 map to the prototype's 其他 tier; an overseas school has none", () => {
  assert.equal(toPrototypeBackground({ ...base, domesticTier: "双非" }).institutionTier, "其他");
  assert.equal(toPrototypeBackground({ ...base, domesticTier: "专科" }).institutionTier, "其他");
  assert.equal(toPrototypeBackground({ ...base, domesticTier: null }).institutionTier, null);
});

test("an average is normalised to 100 and unknown when either half is missing", () => {
  assert.equal(averageOf(3.6, 4), 90);
  assert.equal(averageOf(null, 100), null);
  assert.equal(averageOf(85, null), null);
});

test("only an IELTS score is read; TOEFL and 还没考 stay unknown, never zero", () => {
  assert.equal(ieltsOf("雅思 6.5"), 6.5);
  assert.equal(ieltsOf("IELTS:7"), 7);
  assert.equal(ieltsOf("托福 90"), null);
  assert.equal(ieltsOf("还没考"), null);
});

test("a major outside the three example fields is unknown", () => {
  assert.equal(toPrototypeBackground({ ...base, major: "金融学" }).major, "商科");
  assert.equal(toPrototypeBackground({ ...base, major: "历史学" }).major, null);
});
