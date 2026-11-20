import assert from "node:assert/strict";
import { test } from "node:test";

import {
  LEAD_LIMITS,
  type ReminderSettings,
  addLead,
  leadProblem,
  removeLead,
  resolveStaleSettings,
  saveReminderSettings,
  unsubscribe,
  unsubscribeToken,
  unsubscribedDay,
} from "./reminders.ts";
import { StaleVersionError } from "./sync-conflict.ts";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const base: ReminderSettings = { enabled: true, leadDays: [14, 7, 3, 1], unsubscribedAt: null, version: "1" };

test("a lead time is a whole number of days inside the limits, not already listed", () => {
  assert.equal(leadProblem("10", [14, 7]), null);
  assert.match(leadProblem("", [14])!, /天数/);
  assert.match(leadProblem("1.5", [14])!, /整数/);
  assert.match(leadProblem("0", [14])!, /1 到 90/);
  assert.match(leadProblem("91", [14])!, /1 到 90/);
  assert.match(leadProblem("7", [14, 7])!, /已经/);
  assert.match(leadProblem("2", [30, 14, 7, 5, 3, 1])!, new RegExp(`最多 ${LEAD_LIMITS.count} 个`));
  assert.match(leadProblem("abc", [14])!, /整数/);
});

test("lead times stay sorted longest first, and the last one cannot be removed", () => {
  assert.deepEqual(addLead([14, 3], 7), [14, 7, 3]);
  assert.deepEqual(removeLead([14, 7, 3], 7), [14, 3]);
  assert.deepEqual(removeLead([7], 7), [7]);
});

test("a save sends the base version and returns the stored settings", async () => {
  let sent: { url: string; init: RequestInit } | null = null;
  const stored = { ...base, leadDays: [7], version: "2" };
  const result = await saveReminderSettings({ leadDays: [7] }, "1", async (url, init) => {
    sent = { url: String(url), init: init! };
    return json(stored);
  });
  assert.deepEqual(result, stored);
  assert.equal(sent!.url, "/api/reminders/settings");
  assert.equal(sent!.init.method, "PUT");
  assert.deepEqual(JSON.parse(String(sent!.init.body)), { leadDays: [7], baseVersion: "1" });
});

test("a stale save throws with the settings the server holds", async () => {
  const current = { ...base, enabled: false, version: "5" };
  await assert.rejects(
    saveReminderSettings({ leadDays: [7] }, "1", async () =>
      json({ detail: "x", code: "stale_version", current }, 409),
    ),
    (error: unknown) => error instanceof StaleVersionError && (error.current as ReminderSettings).version === "5",
  );
  await assert.rejects(saveReminderSettings({ enabled: false }, "1", async () => json({}, 500)), /500/);
});

test("a stale change is adopted, sent again, or asked about", () => {
  // The other device made the same change.
  assert.equal(resolveStaleSettings(base, { enabled: false }, { ...base, enabled: false, version: "2" }), "adopt");
  // The other device changed something else: this change goes again on the new version.
  assert.equal(resolveStaleSettings(base, { enabled: false }, { ...base, leadDays: [7], version: "2" }), "retry");
  // Both changed the same thing differently: the applicant chooses.
  assert.equal(resolveStaleSettings(base, { leadDays: [10] }, { ...base, leadDays: [5], version: "2" }), "ask");
  assert.equal(resolveStaleSettings(base, { leadDays: [5] }, { ...base, leadDays: [5], version: "2" }), "adopt");
});

test("unsubscribing posts the token in the body and reports what the server said", async () => {
  let body = "";
  assert.equal(
    await unsubscribe("a.b", async (_url, init) => {
      body = String(init!.body);
      return json({ unsubscribed: true });
    }),
    "done",
  );
  assert.deepEqual(JSON.parse(body), { token: "a.b" });
  assert.equal(await unsubscribe("a.b", async () => json({ detail: "x" }, 400)), "invalid");
  assert.equal(await unsubscribe("", async () => json({ unsubscribed: true })), "invalid");
  assert.equal(await unsubscribe("a.b", async () => json({}, 502)), "failed");
  assert.equal(
    await unsubscribe("a.b", async () => {
      throw new TypeError("network");
    }),
    "failed",
  );
});

test("the token is read from the link's query, and a link without one has none", () => {
  assert.equal(unsubscribeToken("?token=a.b"), "a.b");
  assert.equal(unsubscribeToken("?utm=x&token=a.b%2Bc"), "a.b+c");
  assert.equal(unsubscribeToken(""), "");
  assert.equal(unsubscribeToken("?other=1"), "");
});

test("the day of an unsubscribe is shown as a Beijing date", () => {
  assert.equal(unsubscribedDay("2026-11-20T16:30:00+00:00"), "2026-11-21");
  assert.equal(unsubscribedDay("2026-11-20T01:07:00Z"), "2026-11-20");
  assert.equal(unsubscribedDay(null), null);
  assert.equal(unsubscribedDay("nonsense"), null);
});
