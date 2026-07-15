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

test("server-renders login as the mandatory first page", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>OfferPilot/);
  assert.match(html, /账户登录/);
  assert.match(html, /继续你的申请规划/);
  assert.match(html, /请先登录/);
  assert.doesNotMatch(html, /不只推荐学校/);
  assert.doesNotMatch(html, /codex-preview|Your site is taking shape/);
});

test("keeps authenticated navigation and logo home behavior explicit", async () => {
  const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");

  assert.match(page, /useState<View>\("login"\)/);
  assert.match(page, /aria-current=\{active \? "page"/);
  assert.doesNotMatch(page, /当前页面/);
  assert.match(page, /handleBrandClick/);
  assert.match(page, /navigateTo\("landing"\)/);
  assert.match(page, /RoadmapView/);
  assert.match(page, /PortfolioControls/);
});

test("connects application portfolio and roadmap product flows", async () => {
  const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  const client = await readFile(new URL("../app/api-client.ts", import.meta.url), "utf8");
  const roadmap = await readFile(new URL("../app/roadmap-view.tsx", import.meta.url), "utf8");
  const portfolio = await readFile(new URL("../app/portfolio-controls.tsx", import.meta.url), "utf8");

  for (const endpoint of ["/portfolio", "/roadmap"]) {
    assert.match(client, new RegExp(endpoint.replaceAll("/", "\\/")));
  }
  for (const label of ["待定", "确定申请", "不考虑", "首选项目"]) assert.match(page + roadmap + portfolio, new RegExp(label));
  assert.match(roadmap, /横向申请路线图/);
  assert.match(roadmap, /学校官方截止日期|官方期限/);
  assert.match(roadmap, /系统按入学季倒推建议/);
});

test("keeps program-level sources, agent tools, and disclaimers in source", async () => {
  const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  const programSlugs = ["unsw-master-it", "usyd-master-cs", "monash-master-ai", "monash-master-cs", "uq-master-data-science", "uwa-master-it"];
  const tools = ["normalize_gpa", "retrieve_programs", "check_hard_constraints", "rank_portfolio", "validate_citations"];

  for (const slug of programSlugs) assert.match(page, new RegExp(`slug: \\\"${slug}\\\"`));
  for (const tool of tools) assert.match(page, new RegExp(tool));
  assert.match(page, /匹配分/);
  assert.match(page, /不是录取概率/);
  assert.doesNotMatch(page, /FastAPI connected|Demo fallback|grounded agent report/);
  assert.match(page, /查看项目官方要求/);
});

test("supports all degree levels and exposes honest catalog fallbacks", async () => {
  const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  const levels = ["本科", "授课型硕士", "研究型硕士", "博士"];
  const areas = ["计算机与数据", "商科与金融", "工程", "医学与健康", "法律与犯罪学", "环境与农业"];

  for (const level of levels) assert.match(page, new RegExp(`\\"${level}\\"`));
  for (const area of areas) assert.match(page, new RegExp(`\\"${area}\\"`));
  assert.match(page, /目前还没有完成课程级要求核验/);
  assert.match(page, /programsandcourses\.anu\.edu\.au\/Search/);
  assert.match(page, /adelaideuni\.edu\.au\/study\/degrees/);
  assert.match(page, /filteredResults\.length === 0/);
});

test("exposes verified account, feedback, and admin product flows", async () => {
  const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  const client = await readFile(new URL("../app/api-client.ts", import.meta.url), "utf8");

  for (const label of ["注册账户", "忘记密码", "注册并验证邮箱", "退出登录", "产品反馈", "运营后台", "账户设置", "服务条款", "隐私说明"]) {
    assert.match(page, new RegExp(label));
  }
  for (const endpoint of ["/auth/register", "/auth/verify-email", "/auth/forgot-password", "/auth/reset-password", "/auth/logout", "/me/export", "/admin/stats", "/admin/users", "/admin/feedback"]) {
    assert.match(client, new RegExp(endpoint.replaceAll("/", "\\/")));
  }
  assert.match(page, /currentUser\?\.role === "admin"/);
});

test("exposes consented streaming DeepSeek advisor without a client key", async () => {
  const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  const client = await readFile(new URL("../app/api-client.ts", import.meta.url), "utf8");

  for (const endpoint of ["/me/advisor/consent", "/messages/stream"]) assert.match(client, new RegExp(endpoint.replaceAll("/", "\\/")));
  for (const event of ["status", "delta", "actions", "state", "done", "error"]) assert.match(client + page, new RegExp(`"${event}"`));
  assert.match(page, /是否使用 DeepSeek 顾问/);
  assert.match(page, /不会发送：姓名、邮箱、账户 ID/);
  assert.match(page, /规则顾问 · 快速降级/);
  assert.doesNotMatch(client, /DEEPSEEK_API_KEY/);
});
