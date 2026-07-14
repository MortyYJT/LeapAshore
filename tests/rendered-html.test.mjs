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
  assert.match(html, /不只推荐学校/);
  assert.match(html, /运行申请 Agent/);
  assert.match(html, /可验证 RAG/);
  assert.match(html, /官方来源引用/);
  assert.doesNotMatch(html, /codex-preview|Your site is taking shape/);
});

test("keeps program-level sources, agent tools, and disclaimers in source", async () => {
  const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  const programSlugs = ["unsw-master-it", "usyd-master-cs", "monash-master-ai", "monash-master-cs", "uq-master-data-science", "uwa-master-it"];
  const tools = ["normalize_gpa", "retrieve_programs", "check_hard_constraints", "rank_portfolio", "validate_citations"];

  for (const slug of programSlugs) assert.match(page, new RegExp(`slug: \\\"${slug}\\\"`));
  for (const tool of tools) assert.match(page, new RegExp(tool));
  assert.match(page, /匹配分/);
  assert.match(page, /不是录取概率/);
  assert.match(page, /Demo fallback/);
  assert.match(page, /官方项目页/);
});
