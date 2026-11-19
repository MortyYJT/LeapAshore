import assert from "node:assert/strict";
import { test } from "node:test";

import { StaleVersionError, changedFields, resolveStaleField, staleOf } from "./sync-conflict.ts";

const json = (body: unknown, status: number) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

test("a 409 with the stale code becomes an error carrying the server's record", async () => {
  const current = { id: "a", version: 3, status: "completed" };
  const stale = await staleOf(json({ detail: "已在其他设备上更新", code: "stale_version", current }, 409));
  assert.ok(stale instanceof StaleVersionError);
  assert.deepEqual(stale.current, current);
  assert.equal(stale.message, "已在其他设备上更新");
});

test("another refusal is not a version conflict", async () => {
  assert.equal(await staleOf(json({ detail: "先给材料归档分类，才能送审。" }, 409)), null);
  assert.equal(await staleOf(json({ code: "stale_version", current: {} }, 200)), null);
  assert.equal(await staleOf(new Response("<html>", { status: 409 })), null);
});

test("reading a response for a conflict leaves its body readable", async () => {
  const response = json({ detail: "x" }, 409);
  await staleOf(response);
  assert.deepEqual(await response.json(), { detail: "x" });
});

test("an auto-saved field is adopted, restated or asked about by what the server holds", () => {
  // The other device made the same change: nothing to save.
  assert.equal(resolveStaleField("pending", "completed", "completed"), "adopt");
  // The row moved but not this field (a recomputed date, say): restate the edit on the new version.
  assert.equal(resolveStaleField("pending", "completed", "pending"), "retry");
  // The other device set a third value: only the applicant can choose.
  assert.equal(resolveStaleField("pending", "completed", "skipped"), "ask");
});

test("keeping a form's edit keeps only the fields the applicant changed", () => {
  // The form was opened on `base`; the applicant changed the round and nothing else. Sending only
  // that leaves a status another device set in the meantime as the server holds it.
  const base = { round: "R1", status: "considering", deadline: null, materialNotes: "", materialsReady: false };
  const form = { round: "R2", status: "considering", deadline: "", materialNotes: "", materialsReady: false };
  assert.deepEqual(changedFields(form, base), { round: "R2" });
  // Clearing a field is a change; an empty input over an empty value is not.
  assert.deepEqual(changedFields({ round: "", deadline: null }, { round: "R1", deadline: undefined }), { round: "" });
  assert.deepEqual(changedFields({ materialsReady: true, gpaScore: 85 }, { materialsReady: false, gpaScore: 85 }), {
    materialsReady: true,
  });
  // With no record to compare against (a new one), the whole form is the edit.
  assert.deepEqual(changedFields(form, null), form);
});
