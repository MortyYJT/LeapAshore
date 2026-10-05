// Characterisation tests for the deterministic eligibility rules.
//
// The rules shipped in T2 before any test existed, so these lock in current behaviour. Several
// documented gaps are asserted explicitly rather than papered over; see note/stage-1-MVP.md.

import { test } from "node:test";
import assert from "node:assert/strict";

import { assessAll, assessProgram, isCognate, normalizeGpa, parseIelts } from "./eligibility.ts";
import { PROGRAMS } from "./programs.ts";
import type { Profile } from "./types.ts";

const BASE: Profile = {
  educationLevel: "本科",
  schoolOrigin: "国内",
  schoolName: "北京邮电大学",
  domesticTier: "211",
  overseasBand: null,
  major: "软件工程",
  gpaScore: 82,
  gpaScale: 100,
  targetDegree: "授课型硕士",
  targetField: "计算机与数据",
  englishScore: "IELTS 6.5",
  annualBudgetCny: 300000,
  intake: "2027 S1",
};

const program = (slug: string) => {
  const found = PROGRAMS.find((p) => p.slug === slug);
  assert.ok(found, `seed program ${slug} is missing`);
  return found;
};

test("normalises scores from any scale onto a 0-100 range", () => {
  assert.equal(normalizeGpa(82, 100), 82);
  assert.equal(normalizeGpa(3.4, 4), 85);
  assert.equal(normalizeGpa(5, 7), 71);
  assert.equal(normalizeGpa(100, 100), 100);
});

test("never returns a normalised score above 100", () => {
  assert.equal(normalizeGpa(110, 100), 100);
});

test("returns zero for a missing or invalid scale instead of dividing by zero", () => {
  assert.equal(normalizeGpa(82, 0), 0);
});

test("flags a major as cognate when it names a computing field", () => {
  assert.equal(isCognate("软件工程"), true);
  assert.equal(isCognate("Computer Science"), true);
  assert.equal(isCognate("市场营销"), false);
  assert.equal(isCognate("English"), false);
});

test("extracts an IELTS band and ignores free text", () => {
  assert.equal(parseIelts("IELTS 6.5"), 6.5);
  assert.equal(parseIelts("雅思 7"), 7);
  assert.equal(parseIelts("还没考"), null);
});

test("asks for the score when the profile has no average", () => {
  const result = assessProgram(program("unsw-master-it"), { ...BASE, gpaScore: null });
  assert.equal(result.suggestedTier, null);
  assert.equal(result.gapStatus, "需要人工核验");
  assert.deepEqual(result.reasons, ["尚未提供本科均分，无法进行门槛比较。"]);
});

test("tiers a 211 applicant against the program baseline", () => {
  const result = assessProgram(program("unsw-master-it"), BASE);
  assert.equal(result.suggestedTier, "保");
  assert.equal(result.gapStatus, "需要人工核验");
});

test("tiers a non-211 applicant against the non-211 baseline when one is recorded", () => {
  const solid = assessProgram(program("unsw-master-it"), { ...BASE, domesticTier: "一本" });
  assert.equal(solid.suggestedTier, "保");

  const borderline = assessProgram(program("unsw-master-it"), {
    ...BASE,
    domesticTier: "一本",
    gpaScore: 70,
  });
  assert.equal(borderline.suggestedTier, "冲");

  const short = assessProgram(program("unsw-master-it"), {
    ...BASE,
    domesticTier: "一本",
    gpaScore: 68,
  });
  assert.equal(short.suggestedTier, null);
  assert.equal(short.gapStatus, "存在门槛缺口");
});

test("refuses to tier when no baseline matches the applicant tier", () => {
  // usyd records no non-211 baseline, so a non-211 applicant cannot be compared.
  const result = assessProgram(program("usyd-master-cs"), { ...BASE, domesticTier: "一本" });
  assert.equal(result.suggestedTier, null);
  assert.equal(result.gapStatus, "需要人工核验");
});

// A 双一流 institution that is not also 985 or 211 is a non-211 institution, so the recorded
// non-211 baseline applies. Treating it as unknowable left those applicants with an empty portfolio.
test("applies the non-211 baseline to a 双一流 applicant", () => {
  const result = assessProgram(program("unsw-master-it"), { ...BASE, domesticTier: "双一流" });
  assert.equal(result.suggestedTier, "保");
  assert.ok(result.reasons.some((r) => r.includes("非 211")));
});

test("still gives no tier when the applicant declines to state a tier", () => {
  const result = assessProgram(program("unsw-master-it"), { ...BASE, domesticTier: "其他" });
  assert.equal(result.suggestedTier, null);
  assert.equal(result.gapStatus, "需要人工核验");
});

test("refuses to convert an overseas degree automatically", () => {
  const result = assessProgram(program("unsw-master-it"), {
    ...BASE,
    schoolOrigin: "海外",
    domesticTier: null,
    overseasBand: "QS 1-50",
  });
  assert.equal(result.suggestedTier, null);
  assert.equal(result.gapStatus, "需要人工核验");
  assert.ok(result.risks.some((r) => r.includes("等值换算")));
});

test("treats a cognate requirement as a hard gap for an unrelated major", () => {
  const result = assessProgram(program("monash-master-cs"), { ...BASE, major: "市场营销" });
  assert.equal(result.suggestedTier, null);
  assert.equal(result.gapStatus, "存在门槛缺口");
  assert.ok(result.risks.some((r) => r.includes("相关专业背景")));
});

test("marks every seed program as resting on unverified data", () => {
  for (const p of PROGRAMS) {
    assert.equal(p.dataStatus, "待核验", `${p.slug} should not claim verification`);
    assert.equal(p.source.verifiedAt, null, `${p.slug} must not carry a hardcoded verification date`);
    const result = assessProgram(p, BASE);
    assert.equal(result.basedOnUnverifiedData, true);
    assert.ok(result.risks.some((r) => r.includes("待核验")));
  }
});

// Known gap: no seed program combines a parseable IELTS requirement with an empty prerequisite list,
// so "满足基础门槛" is unreachable today. A 985 applicant with a strong score still lands on
// "需要人工核验". Asserted so the dead state is visible rather than assumed.
test("never reaches 满足基础门槛 with the current seed data", () => {
  const outcomes = new Set<string>();
  for (const p of PROGRAMS) {
    for (const domesticTier of ["985", "211", "一本", "双一流"] as const) {
      for (const englishScore of ["IELTS 8.0", "IELTS 6.5", ""]) {
        const result = assessProgram(p, { ...BASE, domesticTier, englishScore, gpaScore: 95 });
        outcomes.add(result.gapStatus);
      }
    }
  }
  assert.ok(!outcomes.has("满足基础门槛"), `unreachable state became reachable: ${[...outcomes]}`);
});

test("filters by degree level and study area before tiering", () => {
  const mismatched = assessAll(PROGRAMS, { ...BASE, targetField: "医学与健康" });
  assert.equal(mismatched.length, 0);
});

test("orders the portfolio from safest to most ambitious", () => {
  const order = assessAll(PROGRAMS, BASE).map((a) => a.suggestedTier);
  const rank: Record<string, number> = { 保: 0, 稳: 1, 冲: 2 };
  const ranks = order.filter((t): t is "保" | "稳" | "冲" => t !== null).map((t) => rank[t]);
  assert.deepEqual(ranks, [...ranks].sort((a, b) => a - b));
});
