// Tests for the profile API layer: the merge rule that decides which copy of a field wins, and the
// rollback rule that decides what a failed save restores.
//
// `fetch` is stubbed here, so these run without the backend. The request path itself is covered end
// to end by scripts/e2e-walkthrough.cjs, which drives the real server through the real cookie.

import { test } from "node:test";
import assert from "node:assert/strict";

import { fetchProfile, mergeServerProfile, patchProfile } from "./api.ts";
import { EMPTY_PROFILE } from "./store.ts";
import type { Profile } from "./types.ts";

function withFetch<T>(handler: (url: string, init?: RequestInit) => Response, run: () => Promise<T>) {
  const original = globalThis.fetch;
  const calls: { url: string; init?: RequestInit }[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), init });
    return handler(String(input), init);
  }) as typeof fetch;
  return run()
    .then((value) => ({ value, calls }))
    .finally(() => {
      globalThis.fetch = original;
    });
}

test("a field the server holds wins over the local copy", () => {
  const merged = mergeServerProfile({ schoolName: "北京邮电大学", major: "软件工程" }, EMPTY_PROFILE);
  assert.equal(merged.schoolName, "北京邮电大学");
  assert.equal(merged.major, "软件工程");
});

test("a field the server has never been told does not erase the local answer", () => {
  // First contact answers with a row of nulls. Taking those at face value would wipe the answers the
  // applicant just gave on this device, which is the whole reason the merge is not a spread.
  const local: Profile = { ...EMPTY_PROFILE, schoolName: "北京邮电大学", gpaScore: 82, intake: "2027 S1" };
  const merged = mergeServerProfile(
    { schoolName: null, gpaScore: null, intake: null, major: null },
    local,
  );
  assert.deepEqual(merged, local);
});

test("an empty string on the server is treated as no answer, not as an answer", () => {
  // The column is nullable and the frontend's `englishScore` defaults to "", so "empty" cannot be
  // read as "the applicant cleared this": it is the shape of a row that was never filled in.
  const local: Profile = { ...EMPTY_PROFILE, schoolName: "北京邮电大学", englishScore: "IELTS 6.5" };
  assert.equal(mergeServerProfile({ schoolName: "" }, local).schoolName, "北京邮电大学");
  assert.equal(mergeServerProfile({ schoolName: "  " }, local).schoolName, "北京邮电大学");
  assert.equal(mergeServerProfile({ englishScore: "" }, local).englishScore, "IELTS 6.5");
});

test("a numeric zero from the server is a real answer and wins over the local value", () => {
  // 0 is a value, not an absent one: the applicant who reports a zero must not be silently reverted
  // to whatever this device still held.
  const local: Profile = { ...EMPTY_PROFILE, gpaScore: 82 };
  assert.equal(mergeServerProfile({ gpaScore: 0 }, local).gpaScore, 0);
});

test("fetchProfile returns the body the server sent", async () => {
  const { value, calls } = await withFetch(
    () => new Response(JSON.stringify({ schoolName: "北京邮电大学" }), { status: 200 }),
    () => fetchProfile(),
  );
  assert.deepEqual(value, { schoolName: "北京邮电大学" });
  assert.equal(calls[0].url, "/api/profile");
  assert.equal(calls[0].init?.credentials, "same-origin");
});

test("fetchProfile refuses to treat an error page as a profile", async () => {
  await assert.rejects(
    () => withFetch(() => new Response("nope", { status: 502 }), () => fetchProfile()),
    /读取档案失败：502/,
  );
});

test("patchProfile sends only the fields it was given, as PATCH", async () => {
  const { value, calls } = await withFetch(
    () => new Response(JSON.stringify({ major: "软件工程" }), { status: 200 }),
    () => patchProfile({ major: "软件工程" }),
  );
  assert.deepEqual(value, { major: "软件工程" });
  assert.equal(calls[0].init?.method, "PATCH");
  assert.equal(calls[0].init?.body, JSON.stringify({ major: "软件工程" }));
  assert.deepEqual(calls[0].init?.headers, { "Content-Type": "application/json" });
});

test("patchProfile raises on a rejected save so the caller can roll the edit back", async () => {
  await assert.rejects(
    () => withFetch(() => new Response("", { status: 422 }), () => patchProfile({ major: "x" })),
    /保存档案失败：422/,
  );
});
