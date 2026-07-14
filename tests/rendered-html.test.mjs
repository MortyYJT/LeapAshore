import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the OfferPilot landing page", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>OfferPilot/);
  assert.match(html, /选校不靠猜/);
  assert.match(html, /免费生成方案/);
  assert.match(html, /覆盖澳洲 Group of Eight/);
  assert.doesNotMatch(html, /codex-preview|Your site is taking shape/);
});

test("keeps all eight Go8 members and recommendation disclaimers in source", async () => {
  const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  const members = ["unimelb", "anu", "unsw", "usyd", "monash", "uq", "uwa", "adelaide"];

  for (const slug of members) assert.match(page, new RegExp(`slug: \\\"${slug}\\\"`));
  assert.match(page, /匹配分/);
  assert.match(page, /不构成录取承诺/);
  assert.match(page, /Demo 登录/);
});
