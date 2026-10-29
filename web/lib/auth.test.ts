import assert from "node:assert/strict";
import { test } from "node:test";

import { AuthApiError, authErrorFrom, isPlausibleEmail, isSixDigits, normalizeEmail } from "./auth.ts";

test("an email is trimmed and lower-cased the way the server stores it", () => {
  assert.equal(normalizeEmail("  A@Example.COM "), "a@example.com");
});

test("only a plausible address is sent", () => {
  assert.equal(isPlausibleEmail("a@example.com"), true);
  for (const bad of ["", "a", "a@b", "a@@b.com", "a b@c.com"]) assert.equal(isPlausibleEmail(bad), false, bad);
});

test("a code is exactly six digits", () => {
  assert.equal(isSixDigits("012345"), true);
  for (const bad of ["12345", "1234567", "12a456", ""]) assert.equal(isSixDigits(bad), false, bad);
});

test("a refusal carries the server's code, message, wait and remaining guesses", () => {
  const error = authErrorFrom(429, { detail: { code: "too_soon", message: "请 42 秒后再试。", retryAfter: 42 } });
  assert.ok(error instanceof AuthApiError);
  assert.equal(error.code, "too_soon");
  assert.equal(error.message, "请 42 秒后再试。");
  assert.equal(error.retryAfter, 42);
  const wrong = authErrorFrom(400, { detail: { code: "wrong_code", message: "还可以再试 3 次。", remaining: 3 } });
  assert.equal(wrong.remaining, 3);
});

test("a refusal without a body still says something", () => {
  const error = authErrorFrom(502, null);
  assert.equal(error.code, "http_502");
  assert.ok(error.message.length > 0);
  assert.equal(authErrorFrom(422, { detail: [{ msg: "x" }] }).code, "http_422");
});
