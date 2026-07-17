import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const pageSource = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
const apiClientSource = await readFile(new URL("../app/api-client.ts", import.meta.url), "utf8");

test("the browser renders persisted backend recommendations instead of duplicating admission rules", () => {
  assert.match(pageSource, /const results = agentRun\?\.recommendations \?\? \[\]/);
  assert.match(pageSource, /setAgentRun\(run\)/);
  assert.match(pageSource, /fetchAgentRun\(token, item\.run_id\)/);
  assert.doesNotMatch(pageSource, /function getProgramRecommendation/);
  assert.doesNotMatch(pageSource, /function normalizeGpa/);
  assert.doesNotMatch(pageSource, /minimumMark:/);
});

test("the recommendation API client retains evidence needed by the product UI", () => {
  for (const field of ["recommendations", "tool_trace", "missing_information", "citations", "verified_at"]) {
    assert.match(apiClientSource, new RegExp(`\\b${field}\\b`));
  }
  assert.match(apiClientSource, /fetchAgentRun/);
});

test("the RAG product surface exposes only source-backed official knowledge", () => {
  for (const marker of ["官方知识库 · RAG", "检索已核验要求", "hit.source.url", "hit.source.verified_at"]) {
    assert.match(pageSource, new RegExp(marker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
  assert.match(apiClientSource, /\/me\/knowledge\/search/);
  assert.match(apiClientSource, /relevance_score/);
});
