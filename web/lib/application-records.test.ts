import { test } from "node:test";
import assert from "node:assert/strict";
import {
  attentionRecords,
  deadlineLabel,
  type ApplicationRecord,
} from "./application-records.ts";
const base: ApplicationRecord = {
  id: "a",
  programId: null,
  school: "Example",
  name: "MSc",
  round: null,
  status: "applying",
  deadline: null,
  sourceUrl: null,
  checkedAt: null,
  deadlineOrigin: null,
  materialsReady: false,
  materialNotes: "",
};
test("attention separates unknown dates and excludes submitted applications", () => {
  const view = attentionRecords([
    { ...base, id: "late", deadline: "2027-02-01" },
    { ...base, id: "unknown" },
    { ...base, id: "earlier", deadline: "2027-01-01" },
    { ...base, id: "submitted", status: "submitted", deadline: "2026-01-01" },
  ]);
  assert.deepEqual(
    view.dated.map((r) => r.id),
    ["earlier", "late"],
  );
  assert.deepEqual(
    view.undated.map((r) => r.id),
    ["unknown"],
  );
});
test("deadline labels preserve unknown and use calendar-day comparisons", () => {
  assert.equal(deadlineLabel(base, "2027-01-01"), "截止日期待确认");
  assert.equal(
    deadlineLabel({ ...base, deadline: "2027-01-01" }, "2027-01-01"),
    "2027-01-01 · 今天截止",
  );
  assert.equal(
    deadlineLabel({ ...base, deadline: "2027-01-02" }, "2027-01-01"),
    "2027-01-02 · 还有 1 天",
  );
  assert.equal(
    deadlineLabel({ ...base, deadline: "2026-12-31" }, "2027-01-01"),
    "2026-12-31 · 已截止",
  );
});
