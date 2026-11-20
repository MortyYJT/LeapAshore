import assert from "node:assert/strict";
import test from "node:test";

import {
  KEY_HEADER,
  MODEL_KEY_STORAGE,
  PROVIDER_HEADER,
  PROVIDERS,
  keyCheckResult,
  keyProblem,
  maskKey,
  modelKeyHeaders,
  readModelKey,
  removeModelKey,
  saveModelKey,
} from "./model-key.ts";

const KEY = "sk-0123456789abcdefFEDCBA";

function store(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  return {
    data,
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => void data.set(key, value),
    removeItem: (key: string) => void data.delete(key),
  };
}

test("the provider ids are the two the server lists", () => {
  // api/app/agent/model_key.py PROVIDERS; api/tests/test_model_key.py pins the same ids and models.
  assert.deepEqual(PROVIDERS.map((p) => [p.id, p.model]), [
    ["deepseek", "deepseek-flash"],
    ["siliconflow", "deepseek-ai/DeepSeek-V4-Flash"],
  ]);
});

test("a key is saved trimmed under one storage entry and read back", () => {
  const s = store();
  saveModelKey(s, "siliconflow", `  ${KEY}\n`);
  assert.deepEqual([...s.data.keys()], [MODEL_KEY_STORAGE]);
  assert.deepEqual(readModelKey(s), { provider: "siliconflow", key: KEY });
});

test("removing the key leaves nothing behind", () => {
  const s = store();
  saveModelKey(s, "deepseek", KEY);
  removeModelKey(s);
  assert.equal(s.data.size, 0);
  assert.equal(readModelKey(s), null);
});

test("a stored entry that is damaged, or names a provider the server does not list, is no key", () => {
  assert.equal(readModelKey(store({ [MODEL_KEY_STORAGE]: "{not json" })), null);
  assert.equal(readModelKey(store({ [MODEL_KEY_STORAGE]: JSON.stringify({ provider: "openai", key: KEY }) })), null);
  assert.equal(readModelKey(store({ [MODEL_KEY_STORAGE]: JSON.stringify({ provider: "deepseek", key: "a b" }) })), null);
  assert.equal(readModelKey(store({ [MODEL_KEY_STORAGE]: JSON.stringify({ provider: "deepseek" }) })), null);
});

test("the key travels in two headers, and no key means no header", () => {
  assert.deepEqual(modelKeyHeaders({ provider: "deepseek", key: KEY }), { [KEY_HEADER]: KEY, [PROVIDER_HEADER]: "deepseek" });
  assert.deepEqual(modelKeyHeaders(null), {});
});

test("a saved key is shown by its ends only", () => {
  assert.equal(maskKey(KEY), "sk-…DCBA");
  assert.ok(!maskKey(KEY).includes(KEY.slice(3, -4)));
  assert.equal(maskKey("abcdefgh"), "…gh");
});

test("a key that the server would refuse is caught before it is saved", () => {
  assert.equal(keyProblem(KEY), null);
  assert.equal(keyProblem(`  ${KEY}  `), null);
  assert.match(keyProblem("") ?? "", /粘贴/);
  assert.match(keyProblem("sk-abc def-0123456789") ?? "", /空格/);
  assert.match(keyProblem("short") ?? "", /太短/);
  assert.match(keyProblem("sk-密钥密钥密钥密钥") ?? "", /不认识的字符/);
});

test("the result of trying a key is the server's sentence, or says why nothing was tried", () => {
  assert.deepEqual(keyCheckResult(200, { ok: true }, "DeepSeek"), {
    ok: true,
    message: "DeepSeek 接受了这把密钥。测试只查了模型列表，没有产生费用。",
  });
  assert.deepEqual(keyCheckResult(200, { ok: false, code: "own_key_rejected", message: "DeepSeek 没有接受这把密钥。" }, "DeepSeek"), {
    ok: false,
    message: "DeepSeek 没有接受这把密钥。",
  });
  assert.equal(keyCheckResult(429, { detail: { code: "rate_limited", message: "发送太频繁了，请 12 秒后再试。" } }, "DeepSeek").message, "发送太频繁了，请 12 秒后再试。");
  assert.match(keyCheckResult(401, { detail: "login required" }, "DeepSeek").message, /重新登录/);
  assert.match(keyCheckResult(502, null, "DeepSeek").message, /HTTP 502/);
});
