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
  for (const marker of ["官方知识库 · RAG", "检索已核验要求", "hit.source.url", "hit.source.verified_at", "hit.source.version_id"]) {
    assert.match(pageSource, new RegExp(marker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
  assert.match(apiClientSource, /\/me\/knowledge\/search/);
  assert.match(apiClientSource, /relevance_score/);
  assert.match(apiClientSource, /content_hash/);
});

test("the streaming advisor cannot shadow the HttpOnly session with a fake cookie bearer", () => {
  const start = apiClientSource.indexOf("export async function streamAdvisorMessage");
  const end = apiClientSource.indexOf("export async function analyzeTranscript", start);
  const streamSource = apiClientSource.slice(start, end);
  assert.match(streamSource, /token !== "cookie"/);
  assert.match(streamSource, /credentials: "include"/);
  assert.doesNotMatch(streamSource, /headers: \{[^}]*Authorization:/s);
});

test("an uncommitted SSE transport failure restores the draft and removes optimistic messages", () => {
  for (const marker of [
    "committedStateReceived",
    "message.id !== temporaryUserId",
    "message.id !== temporaryAssistantId",
    "setAdvisorInput(content)",
  ]) {
    assert.match(pageSource, new RegExp(marker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
});

test("the advisor resumes the latest persisted thread instead of creating one on every visit", () => {
  assert.match(apiClientSource, /fetchAdvisorThreads/);
  assert.match(pageSource, /const sessionToken = token/);
  assert.match(pageSource, /fetchAdvisorThreads\(sessionToken\)/);
  assert.match(pageSource, /threads\[0\] \?\? await createAdvisorThread\(sessionToken\)/);
});

test("the SSE client rejects a stream that closes before the persisted state event", () => {
  const start = apiClientSource.indexOf("export async function streamAdvisorMessage");
  const end = apiClientSource.indexOf("export async function analyzeTranscript", start);
  const streamSource = apiClientSource.slice(start, end);
  assert.match(streamSource, /event === "state"/);
  assert.match(streamSource, /if \(!committedStateReceived\) throw new Error\("顾问连接在收到保存确认前中断"\)/);
});

test("advisor retries reuse one request-scoped idempotency key", () => {
  const start = apiClientSource.indexOf("export async function streamAdvisorMessage");
  const end = apiClientSource.indexOf("export async function analyzeTranscript", start);
  const streamSource = apiClientSource.slice(start, end);
  assert.match(streamSource, /"Idempotency-Key": requestId/);
  for (const marker of [
    "advisorRetryRef",
    "pendingRetry?.content === content",
    "pendingRetry.requestId",
    "crypto.randomUUID()",
    "streamAdvisorMessage(token, advisorThread.id, content, requestId",
  ]) {
    assert.match(pageSource, new RegExp(marker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
});

test("an ambiguous SSE disconnect reconciles the persisted thread before enabling a retry", () => {
  for (const marker of [
    "persistedMessageCount",
    "fetchAdvisorThreads(token)",
    "turnWasPersisted",
    "回答已保存，已恢复最新会话",
  ]) {
    assert.match(pageSource, new RegExp(marker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
});

test("the operations UI exposes the complete source review lifecycle", async () => {
  const panelSource = await readFile(new URL("../app/source-review-panel.tsx", import.meta.url), "utf8");
  for (const endpoint of ["/programs/", "/admin/program-sources/", "/versions", "/rollback"]) {
    assert.match(apiClientSource, new RegExp(endpoint.replaceAll("/", "\\/")));
  }
  for (const label of ["候选 Program JSON", "生成字段差异", "抓取官网并生成候选", "批准发布", "拒绝候选", "回滚到此版本"]) {
    assert.match(panelSource, new RegExp(label));
  }
  assert.match(panelSource, /currentVersion\.content_hash/);
  assert.match(panelSource, /version\.changes\.map/);
  assert.match(panelSource, /version\.source_snapshot/);
  assert.match(apiClientSource, /capture_snapshot: captureSnapshot/);
});

test("official source fetches pin public DNS and bound every response hop", async () => {
  const sourceFetch = await readFile(new URL("../api/app/source_fetch.py", import.meta.url), "utf8");
  for (const marker of [
    "parsed.is_global",
    "_PinnedHTTPSConnection",
    "MAX_SOURCE_REDIRECTS = 3",
    "MAX_SOURCE_BYTES = 512 * 1024",
    "ALLOWED_SOURCE_CONTENT_TYPES",
    "Accept-Encoding",
  ]) {
    assert.match(sourceFetch, new RegExp(marker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
});

test("the streaming state contract replaces every run-scoped client snapshot together", () => {
  for (const field of ["profile: ApiApplicantProfile", "recommendation_run: ApiAgentRun", "portfolio: ApplicationChoice", "roadmap: ApplicationRoadmap"]) {
    assert.match(apiClientSource, new RegExp(field.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
  for (const update of [
    "setProfile(profileFromApi(data.profile))",
    "setAgentRun(data.recommendation_run)",
    "setActiveRunId(data.recommendation_run.run_id)",
    "setRunSummary(data.recommendation_run.summary)",
  ]) {
    assert.match(pageSource, new RegExp(update.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
});

test("login restores persisted profile data and the advisor cannot overwrite it with demo defaults", () => {
  assert.match(pageSource, /hydrateWorkspace\("cookie"\)/);
  assert.match(pageSource, /fetchProfile\(sessionToken\)/);
  assert.match(pageSource, /profileFromApi/);
  assert.doesNotMatch(pageSource, /saveProfile\(token, profileToApi\(profile\)\)\s*\.then\(\(\) => createAdvisorThread/);
  assert.doesNotMatch(pageSource, /school: "广东工业大学"/);
});

test("revoked browser sessions clear stale workspace state and the cookie", () => {
  for (const marker of [
    "SESSION_EXPIRED_EVENT",
    "isSessionExpiredError",
    "scheduleSessionExpired",
    "resetAuthenticatedSession",
    "登录状态已失效，请重新登录。",
    'logoutAccount("cookie")',
  ]) {
    assert.match(`${apiClientSource}\n${pageSource}`, new RegExp(marker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
});

test("advisor action badges preserve completed, confirmation, and skipped semantics", () => {
  for (const marker of ["completed", "needs_confirmation", "skipped", "已完成", "待确认", "已跳过"]) {
    assert.match(pageSource, new RegExp(marker));
  }
  assert.match(pageSource, /advisorActionStatusMeta\[action\.status\]/);
  assert.match(pageSource, /tool-action-\$\{action\.status\.replace\("_", "-"\)\}/);
});
