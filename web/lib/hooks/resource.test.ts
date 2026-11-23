import assert from "node:assert/strict";
import { test } from "node:test";

import { INITIAL, settle } from "./resource.ts";

test("a first read that fails has no data and says why", async () => {
  const state = await settle(() => Promise.reject(new Error("读取档案失败：500")), INITIAL);
  assert.deepEqual(state, { data: null, error: "读取档案失败：500", loading: false });
});

test("a reload that fails keeps what is on screen and adds the error", async () => {
  const shown = await settle(() => Promise.resolve({ major: "软件工程" }), INITIAL);
  const failed = await settle(() => Promise.reject(new Error("网络错误")), shown);
  assert.deepEqual(failed, { data: { major: "软件工程" }, error: "网络错误", loading: false });
});

test("a read that succeeds clears an earlier error", async () => {
  const failed = await settle(() => Promise.reject(new Error("x")), INITIAL);
  const ok = await settle(() => Promise.resolve(1), failed);
  assert.deepEqual(ok, { data: 1, error: null, loading: false });
});

test("a thrown value that is not an Error still produces a sentence", async () => {
  const state = await settle(() => Promise.reject("boom"), INITIAL);
  assert.equal(state.error, "读取失败，请稍后再试。");
});

// ---------- with the visit's cache ----------

import { beginRead, clearResourceCache, invalidateResource, peekResource, putResource } from "../resource-cache.ts";
import { initialState, readThrough } from "./resource.ts";

test("first read of a key starts from the placeholder state", () => {
  clearResourceCache();
  assert.deepEqual(initialState("profile"), INITIAL);
  assert.deepEqual(initialState(), INITIAL);
});

test("a key read earlier in the visit starts with its data and is not loading", async () => {
  clearResourceCache();
  await readThrough("profile", () => Promise.resolve({ major: "软件工程" }), INITIAL);
  assert.deepEqual(initialState("profile"), { data: { major: "软件工程" }, error: null, loading: false });
});

test("a background read that fails keeps the data on screen and in the cache", async () => {
  clearResourceCache();
  putResource("profile", { major: "软件工程" });
  const shown = initialState<{ major: string }>("profile");
  const failed = await readThrough("profile", () => Promise.reject(new Error("网络错误")), shown);
  assert.deepEqual(failed, { data: { major: "软件工程" }, error: "网络错误", loading: false });
  assert.deepEqual(peekResource("profile"), { major: "软件工程" });
});

test("a background read with a different answer replaces the data", async () => {
  clearResourceCache();
  putResource("documents", [{ id: "a" }]);
  const next = await readThrough("documents", () => Promise.resolve([{ id: "a" }, { id: "b" }]), initialState("documents"));
  assert.deepEqual(next?.data, [{ id: "a" }, { id: "b" }]);
  assert.deepEqual(peekResource("documents"), [{ id: "a" }, { id: "b" }]);
});

test("a background read with an equal answer hands back the same object", async () => {
  clearResourceCache();
  const stored = [{ id: "a" }];
  putResource("documents", stored);
  const next = await readThrough("documents", () => Promise.resolve([{ id: "a" }]), initialState("documents"));
  assert.equal(next?.data, stored);
});

test("a save that lands while a background read is in flight is what stays", async () => {
  clearResourceCache();
  putResource("profile", { intake: "2027 S1", version: 1 });
  let answer: (value: { intake: string; version: number }) => void = () => undefined;
  const reading = readThrough("profile", () => new Promise((resolve) => (answer = resolve)), initialState("profile"));
  putResource("profile", { intake: "2027 S2", version: 2 });
  answer({ intake: "2027 S1", version: 1 });
  assert.deepEqual((await reading)?.data, { intake: "2027 S2", version: 2 });
  assert.deepEqual(peekResource("profile"), { intake: "2027 S2", version: 2 });
});

test("a read that left before a write invalidated the key is not stored", async () => {
  clearResourceCache();
  putResource("portfolio", [{ programSlug: "a" }]);
  const shown = initialState<{ programSlug: string }[]>("portfolio");
  let answer: (value: { programSlug: string }[]) => void = () => undefined;
  const reading = readThrough("portfolio", () => new Promise((resolve) => (answer = resolve)), shown);
  invalidateResource("portfolio");
  answer([{ programSlug: "a" }]);
  // The page keeps what it shows until the read made after the write answers; the cache holds nothing to hand out.
  assert.deepEqual((await reading)?.data, [{ programSlug: "a" }]);
  assert.equal(peekResource("portfolio"), undefined);
});

test("a read that answers after the account changed is not shown and not stored", async () => {
  clearResourceCache();
  const ticket = beginRead("profile");
  let answer: (value: { email: string }) => void = () => undefined;
  const reading = readThrough("profile", () => new Promise((resolve) => (answer = resolve)), INITIAL, ticket);
  clearResourceCache();
  answer({ email: "previous@example.test" });
  assert.equal(await reading, null);
  assert.equal(peekResource("profile"), undefined);
});

import { saysSignedOut } from "./resource.ts";

test("a 401 from a reader is recognised as the session having ended; other failures are not", () => {
  assert.equal(saysSignedOut("读取档案失败：401"), true);
  assert.equal(saysSignedOut("读取材料库失败：401 "), true);
  assert.equal(saysSignedOut("读取档案失败：500"), false);
  assert.equal(saysSignedOut("读取档案失败：4010"), false);
  assert.equal(saysSignedOut("网络错误"), false);
  assert.equal(saysSignedOut(null), false);
});

test("after the account changed, a failed first read for the new one shows nothing of the previous", async () => {
  clearResourceCache();
  putResource("profile", { email: "previous@example.test" });
  clearResourceCache();
  // useResource starts this read from INITIAL, not from what the page showed before the change.
  const next = await readThrough("profile", () => Promise.reject(new Error("读取档案失败：500")), INITIAL);
  assert.deepEqual(next, { data: null, error: "读取档案失败：500", loading: false });
});
