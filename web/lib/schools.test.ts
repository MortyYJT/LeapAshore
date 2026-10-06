// Characterisation tests for the school tier detector.
//
// These lock in current behaviour rather than driving new code: the detector shipped in T1 before any
// test existed, so there is no failing-first state to record. See note/stage-1-MVP.md.

import { test } from "node:test";
import assert from "node:assert/strict";

import { C211_ONLY, C985, DOMESTIC_TIER_OPTIONS, OVERSEAS_BAND_OPTIONS, recognizeDomesticSchool } from "./schools.ts";

test("the Project 985 list holds the 39 official institutions", () => {
  assert.equal(C985.length, 39);
});

// Known gap: this list holds 76 Project 211 institutions that are not Project 985, giving 115 in
// total. Different sources may count split campuses such as 中国矿业大学(北京) and 中国石油大学(华东) as
// one institution or as two. The list has NOT been checked against an authoritative source, so do not
// treat either 76 or 115 as verified.
test("the Project 211 list is present and plausibly sized", () => {
  assert.equal(C211_ONLY.length, 76);
  assert.ok(C211_ONLY.every((name) => name.length >= 2));
});

test("each entry in the lists is a non-empty distinct name", () => {
  const all = [...C985, ...C211_ONLY];
  assert.equal(new Set(all).size, all.length);
});

test("resolves a full institution name", () => {
  assert.deepEqual(recognizeDomesticSchool("北京邮电大学"), {
    name: "北京邮电大学",
    tier: "211",
    matchedBy: "exact",
  });
});

test("resolves a truncated name, because the suffix is stripped", () => {
  assert.deepEqual(recognizeDomesticSchool("北京邮电"), {
    name: "北京邮电大学",
    tier: "211",
    matchedBy: "exact",
  });
});

test("resolves a common abbreviation", () => {
  assert.deepEqual(recognizeDomesticSchool("北大"), {
    name: "北京大学",
    tier: "985",
    matchedBy: "alias",
  });
  assert.equal(recognizeDomesticSchool("西电")?.name, "西安电子科技大学");
  assert.equal(recognizeDomesticSchool("华科")?.tier, "985");
});

test("tolerates surrounding whitespace", () => {
  assert.equal(recognizeDomesticSchool("  北大  ")?.name, "北京大学");
});

test("resolves a name with a college suffix attached", () => {
  assert.deepEqual(recognizeDomesticSchool("清华大学计算机学院"), {
    name: "清华大学",
    tier: "985",
    matchedBy: "partial",
  });
});

test("returns null for institutions outside the public lists", () => {
  assert.equal(recognizeDomesticSchool("某某职业技术学院"), null);
});

test("returns null for input that is too short to match", () => {
  assert.equal(recognizeDomesticSchool(""), null);
  assert.equal(recognizeDomesticSchool("a"), null);
});

// Four tiers only. Splitting the non-211 group into 双一流 / 一本 / 二本 produced options that the
// baseline data cannot serve, which left applicants with an empty portfolio.
test("offers exactly the four supported domestic tiers", () => {
  assert.deepEqual(
    DOMESTIC_TIER_OPTIONS.map((o) => o.value),
    ["985", "211", "双非", "专科"],
  );
});

test("offers a QS band for overseas institutions, which are never detected automatically", () => {
  assert.equal(OVERSEAS_BAND_OPTIONS.length, 6);
  assert.ok(OVERSEAS_BAND_OPTIONS.some((o) => o.value === "不确定"));
});

// ── Bug fix: false-positive containment matching ────────────────────────────────────────────────
// A bare containment match resolved an unlisted institution onto a shorter listed name. 南昌航空大学
// came back as 南昌大学, which would hand a non-211 applicant a Project 211 baseline. The same pattern
// affects 南京邮电大学 → 南京大学, 天津工业大学 → 天津大学 and 北京信息科技大学 → 北京大学.

test("does not resolve an unlisted institution onto a shorter listed name", () => {
  const wrong = [
    "南昌航空大学",
    "南京邮电大学",
    "天津工业大学",
    "北京信息科技大学",
    "上海海事大学",
    "重庆邮电大学",
    "北京第二外国语学院",
  ];
  for (const name of wrong) {
    assert.equal(
      recognizeDomesticSchool(name),
      null,
      `${name} must not resolve onto a different institution`,
    );
  }
});

test("still resolves a listed institution that carries a faculty or campus suffix", () => {
  assert.equal(recognizeDomesticSchool("清华大学计算机学院")?.name, "清华大学");
  assert.equal(recognizeDomesticSchool("上海交通大学医学院")?.name, "上海交通大学");
  assert.equal(recognizeDomesticSchool("北京大学医学部")?.name, "北京大学");
});

test("reports a suffix match distinctly from a full-name or abbreviation match", () => {
  assert.equal(recognizeDomesticSchool("清华大学计算机学院")?.matchedBy, "partial");
});
