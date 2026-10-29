import assert from "node:assert/strict";
import { test } from "node:test";

import { landingFor } from "./landing.ts";

const complete = {
  educationLevel: "本科", schoolOrigin: "国内", schoolName: "北京邮电大学", domesticTier: "211", major: "软件工程",
  gpaScore: 85, gpaScale: 100, targetDegree: "授课型硕士", targetField: "计算机与数据", englishScore: "IELTS 6.5",
  intake: "2027 S2",
};

test("an applicant whose assessment is complete lands on the roadmap", async () => {
  assert.equal(await landingFor(async () => complete), "/roadmap");
});

test("an incomplete assessment sees the introduction", async () => {
  assert.equal(await landingFor(async () => ({ ...complete, intake: null })), null);
  assert.equal(await landingFor(async () => ({})), null);
});

test("an API that fails or does not answer in time shows the introduction", async () => {
  assert.equal(await landingFor(async () => { throw new Error("down"); }), null);
  const never = () => new Promise<Record<string, unknown>>(() => {});
  assert.equal(await landingFor(never, 20), null);
});
