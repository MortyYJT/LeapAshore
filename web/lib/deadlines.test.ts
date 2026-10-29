import assert from "node:assert/strict";
import { test } from "node:test";

import { beijingToday, deadlineOf, isClosed, type CollectedDeadline } from "./deadlines.ts";

const round = (label: string, date: string): CollectedDeadline => ({ label, date, sourceUrl: `https://example.edu/${label}` });

test("today is the Beijing calendar date, not the UTC one", () => {
  // 2026-10-29 17:30 UTC is already 30 October in Beijing.
  assert.equal(beijingToday(new Date("2026-10-29T17:30:00Z")), "2026-10-30");
  assert.equal(beijingToday(new Date("2026-10-30T15:59:00Z")), "2026-10-30");
});

test("a deadline closes after its own day, not on it", () => {
  assert.equal(isClosed("2026-10-29", "2026-10-30"), true);
  assert.equal(isClosed("2026-10-30", "2026-10-30"), false);
  assert.equal(isClosed("2027-01-15", "2026-10-30"), false);
});

test("the date somebody entered on the portfolio row wins over the collected ones", () => {
  const mark = deadlineOf(
    { officialDeadline: "2027-01-02", deadlineSourceUrl: "https://example.edu/mine", deadlines: [round("Round 1", "2026-12-01")] },
    "2026-10-30",
  );
  assert.deepEqual(mark, { state: "upcoming", date: "2027-01-02", url: "https://example.edu/mine", label: null, origin: "entered" });
});

test("an entered date without its source is not shown as official; the collected one is used", () => {
  const mark = deadlineOf({ officialDeadline: "2027-01-02", deadlineSourceUrl: null, deadlines: [round("R1", "2026-12-01")] }, "2026-10-30");
  assert.equal(mark.origin, "collected");
  assert.equal(mark.date, "2026-12-01");
});

test("the next round on or after today is the one drawn", () => {
  const mark = deadlineOf(
    { deadlines: [round("Round 3", "2027-03-01"), round("Round 1", "2026-10-01"), round("Round 2", "2026-10-30")] },
    "2026-10-30",
  );
  assert.deepEqual(mark, { state: "upcoming", date: "2026-10-30", url: "https://example.edu/Round 2", label: "Round 2", origin: "collected" });
});

test("when every round has passed, the latest is labelled closed", () => {
  const mark = deadlineOf({ deadlines: [round("Round 1", "2026-01-15"), round("Round 2", "2026-03-01")] }, "2026-10-30");
  assert.deepEqual(mark, { state: "closed", date: "2026-03-01", url: "https://example.edu/Round 2", label: "Round 2", origin: "collected" });
});

test("a past entered date is closed too", () => {
  const mark = deadlineOf({ officialDeadline: "2026-09-01", deadlineSourceUrl: "https://example.edu/mine", deadlines: [] }, "2026-10-30");
  assert.equal(mark.state, "closed");
  assert.equal(mark.origin, "entered");
});

test("nothing collected and nothing entered is unknown, never a date", () => {
  assert.deepEqual(deadlineOf({ deadlines: [] }, "2026-10-30"), { state: "unknown", date: null, url: null, label: null, origin: null });
  assert.deepEqual(deadlineOf({}, "2026-10-30"), { state: "unknown", date: null, url: null, label: null, origin: null });
});
