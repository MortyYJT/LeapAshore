import assert from "node:assert/strict";
import { test } from "node:test";

import {
  APPLICATION_STATUSES,
  TIER_OF_BAND,
  applicationStatusLabel,
  verifiedMark,
} from "./taxonomy.ts";
import type { ApplicationStatus, SourceStatus } from "./types.ts";

// The stored values the API can hold. A value added on the server without a label here would reach
// the interface as a raw string, which is what PRD §7.7 rule 5 forbids.
const STORED_APPLICATION_STATUSES: ApplicationStatus[] = [
  "considering", "applying", "submitted", "offered", "rejected", "excluded",
];
const STORED_DATA_STATUSES: SourceStatus[] = ["待核验", "机器核对", "已核验"];

test("every stored application status has its interface label, in the spec's order", () => {
  assert.deepEqual(APPLICATION_STATUSES.map((s) => s.value), STORED_APPLICATION_STATUSES);
  assert.deepEqual(
    APPLICATION_STATUSES.map((s) => s.label),
    ["考虑中", "申请中", "已提交", "已获 offer", "被拒", "不考虑"],
  );
});

test("only a page a person checked carries a mark; the other stored statuses show nothing", () => {
  assert.deepEqual(STORED_DATA_STATUSES.map(verifiedMark), [null, null, "已核对"]);
});

test("an unknown stored value is never shown as checked", () => {
  assert.equal(verifiedMark("失效"), null);
  assert.equal(verifiedMark(undefined), null);
  assert.equal(applicationStatusLabel("waitlisted"), "考虑中");
});

test("the one-character bands name the full tiers", () => {
  assert.deepEqual(TIER_OF_BAND, { 保: "保底", 稳: "稳妥", 冲: "冲刺" });
});
