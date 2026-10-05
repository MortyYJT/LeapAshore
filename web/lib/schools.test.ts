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
// total, while commonly cited figures run from 112 to 116 depending on whether split campuses such as
// 中国矿业大学(北京) and 中国石油大学(华东) are counted as one institution or two. The list has NOT been
// checked against an authoritative source. Do not treat 76 as verified.
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
    matchedBy: "exact",
  });
});

test("returns null for institutions outside the public lists", () => {
  assert.equal(recognizeDomesticSchool("某某职业技术学院"), null);
});

test("returns null for input that is too short to match", () => {
  assert.equal(recognizeDomesticSchool(""), null);
  assert.equal(recognizeDomesticSchool("a"), null);
});

test("offers a manual tier and a QS band for every path that cannot be detected", () => {
  assert.equal(DOMESTIC_TIER_OPTIONS.length, 7);
  assert.equal(OVERSEAS_BAND_OPTIONS.length, 6);
  assert.ok(DOMESTIC_TIER_OPTIONS.some((o) => o.value === "其他"));
  assert.ok(OVERSEAS_BAND_OPTIONS.some((o) => o.value === "不确定"));
});
