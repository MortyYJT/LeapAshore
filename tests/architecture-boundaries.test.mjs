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
  for (const field of ["recommendations", "tool_trace", "missing_information", "citations", "verified_at", "profile_snapshot"]) {
    assert.match(apiClientSource, new RegExp(`\\b${field}\\b`));
  }
  assert.match(apiClientSource, /fetchAgentRun/);
});

test("historical runs restore the profile snapshot used for that decision", () => {
  assert.match(pageSource, /run\.profile_snapshot/);
  assert.match(pageSource, /setProfile\(profileFromApi\(run\.profile_snapshot\)\)/);
});

test("the Agent progress view renders backend trace instead of a fake timer", () => {
  assert.match(pageSource, /agentRun\.tool_trace\.map/);
  assert.match(pageSource, /trace\.summary/);
  assert.match(pageSource, /trace\.status/);
  assert.doesNotMatch(pageSource, /setInterval\(/);
  assert.doesNotMatch(pageSource, /completedSteps/);
});

test("the RAG product surface exposes only source-backed official knowledge", () => {
  for (const marker of ["官方知识库 · RAG", "检索已核验要求", "hit.source.url", "hit.source.verified_at"]) {
    assert.match(pageSource, new RegExp(marker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
  assert.match(apiClientSource, /\/me\/knowledge\/search/);
  assert.match(apiClientSource, /relevance_score/);
});

test("the streaming advisor cannot shadow the HttpOnly session with a fake cookie bearer", () => {
  const start = apiClientSource.indexOf("export async function streamAdvisorMessage");
  const end = apiClientSource.indexOf("export async function analyzeTranscript", start);
  const streamSource = apiClientSource.slice(start, end);
  assert.match(streamSource, /token !== "cookie"/);
  assert.match(streamSource, /credentials: "include"/);
  assert.doesNotMatch(streamSource, /headers: \{[^}]*Authorization:/s);
});

test("login restores persisted profile data and the advisor cannot overwrite it with demo defaults", () => {
  assert.match(pageSource, /hydrateWorkspace\("cookie"\)/);
  assert.match(pageSource, /fetchProfile\(sessionToken\)/);
  assert.match(pageSource, /profileFromApi/);
  assert.doesNotMatch(pageSource, /saveProfile\(token, profileToApi\(profile\)\)\s*\.then\(\(\) => createAdvisorThread/);
  assert.doesNotMatch(pageSource, /school: "广东工业大学"/);
});
