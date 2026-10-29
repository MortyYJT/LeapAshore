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
