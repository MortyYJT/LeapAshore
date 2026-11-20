import assert from "node:assert/strict";
import { test } from "node:test";

import { advisorRefusal, confirmBody, targetKey } from "./advisor.ts";

test("a rate or quota refusal shows the server's Chinese message and counts as limited", () => {
  const refusal = advisorRefusal(429, { detail: { code: "rate_limited", message: "发送太频繁了，请 12 秒后再试。", retryAfter: 12 } });
  assert.deepEqual(refusal, { outcome: "limited", message: "发送太频繁了，请 12 秒后再试。", code: "rate_limited" });
  const site = advisorRefusal(429, { detail: { code: "daily_tokens_site", message: "今天全站的顾问额度已用完，北京时间明天 0 点恢复。" } });
  assert.equal(site.message, "今天全站的顾问额度已用完，北京时间明天 0 点恢复。");
  assert.equal(site.code, "daily_tokens_site");
});

test("the limit store being down is a limited outcome with its own message", () => {
  const refusal = advisorRefusal(503, { detail: { code: "limits_unavailable", message: "顾问暂时不可用，请稍后再试。" } });
  assert.deepEqual(refusal, { outcome: "limited", message: "顾问暂时不可用，请稍后再试。", code: "limits_unavailable" });
});

test("a refusal without a readable body still says something", () => {
  assert.equal(advisorRefusal(429, null).outcome, "limited");
  assert.ok(advisorRefusal(429, null).message.includes("频繁"));
  assert.equal(advisorRefusal(429, null).code, "rate_limited");
  assert.deepEqual(advisorRefusal(500, null), { outcome: "failed", message: "顾问服务不可用（HTTP 500）", code: "http" });
  assert.equal(advisorRefusal(401, null).outcome, "unauthorized");
});

test("a confirm names the change it answers, so a late repeat cannot answer a newer one", () => {
  assert.deepEqual(confirmBody("c1", true, "a1b2"), { conversationId: "c1", approved: true, interruptId: "a1b2" });
  // A change shown before the id existed is answered without one, as before.
  assert.deepEqual(confirmBody("c1", false), { conversationId: "c1", approved: false });
});

test("a change is keyed by its application record, or by its catalogue program when it names only that", () => {
  assert.equal(targetKey({ applicationId: "catalog:hku-cs", programId: "hku-cs" }), "catalog:hku-cs");
  assert.equal(targetKey({ applicationId: "7f0c", programId: null }), "7f0c");
  // A portfolio change names the program; an application about to be added has no record yet.
  assert.equal(targetKey({ programId: "hku-cs" }), "hku-cs");
  assert.equal(targetKey({ applicationId: null, programId: null, school: "MIT", program: "EECS" }), undefined);
  assert.equal(targetKey(undefined), undefined);
});
