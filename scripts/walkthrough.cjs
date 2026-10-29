// Browser walkthrough of the new routes (design D10). A fresh visitor goes / -> /assess -> /assess/result
// -> /portfolio (confirm) -> /roadmap (tick, upload) -> /me -> /advisor -> /schools -> /programs/<code>,
// then every page is opened again at 390px. Each step writes docs/screenshots/NN-*.png.
//
// The run fails on a console error, a page error, a page that scrolls sideways, a page without an h1,
// or a failed check. The subjects it creates are deleted from the database at the end, whatever happened.
//
// Usage: node scripts/walkthrough.cjs   (needs `make dev`: the web app on :3000 and the API on :8000)
// Set BASE_URL to drive another origin.

const path = require("path");
const fs = require("fs");
const { execFileSync } = require("child_process");

const { chromium } = require("./playwright.cjs");

const ROOT = path.resolve(__dirname, "..");
const OUT = path.join(ROOT, "docs/screenshots");
const BASE = process.env.BASE_URL || "http://localhost:3000";
const API_PYTHON = path.join(ROOT, "api/.venv/bin/python");
const API_APP = path.join(ROOT, "api/app");
const DESKTOP = { width: 1440, height: 900 };
const PHONE = { width: 390, height: 844 };

fs.mkdirSync(OUT, { recursive: true });

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok: Boolean(ok), detail });
  console.log(`${ok ? "通过" : "失败"}  ${name}${!ok && detail !== undefined ? `  ${JSON.stringify(detail)}` : ""}`);
}

/** One statement against the API's own database; a failure is returned as text, never thrown. */
function dbRun(sql) {
  const script = [
    "import sys",
    "from sqlalchemy import create_engine, text",
    "from app.config import settings",
    "engine = create_engine(settings.database_url)",
    "with engine.begin() as connection:",
    "    result = connection.execute(text(sys.argv[1]))",
    "    row = result.first() if result.returns_rows else None",
    "    print(row[0] if row is not None else result.rowcount)",
  ].join("\n");
  try {
    return execFileSync(API_PYTHON, ["-c", script, sql], { cwd: API_APP, encoding: "utf8" }).trim();
  } catch (error) {
    return "失败：" + String(error.stderr || error.message).trim().split("\n").slice(-1)[0];
  }
}

/** Watch a page: console errors and page errors fail the run; every subject id it is given is kept. */
function watch(page, label, errors, subjects, expected = []) {
  page.on("console", (msg) => {
    if (msg.type() !== "error") return;
    const text = msg.text();
    if (expected.some((pattern) => pattern.test(text))) return;
    errors.push(`${label} console: ${text}`);
  });
  page.on("pageerror", (error) => errors.push(`${label} pageerror: ${error.message}`));
  page.on("response", async (response) => {
    const header = (await response.allHeaders().catch(() => ({})))["set-cookie"] || "";
    for (const match of header.matchAll(/leapashore_client=([^;]+)/g)) subjects.add(decodeURIComponent(match[1]));
  });
}

/** The layout checks every page gets: an h1, and nothing wider than the viewport. */
async function layout(page, name) {
  const h1 = await page.locator("h1").count();
  const { scroll, width } = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    width: window.innerWidth,
  }));
  check(`${name}：有 h1`, h1 > 0);
  check(`${name}：不横向滚动`, scroll <= width, { scroll, width });
}

let shot = 0;
async function screenshot(page, name) {
  shot += 1;
  const file = path.join(OUT, `${String(shot).padStart(2, "0")}-${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
}

async function settle(page) {
  await page.waitForLoadState("networkidle").catch(() => {});
  // Let the entrance motion finish before a screenshot.
  await page.waitForTimeout(900);
}

(async () => {
  try {
    const response = await fetch(`${BASE}/api/health`);
    if (!response.ok) throw new Error(`GET /api/health responded ${response.status}`);
  } catch (error) {
    console.error(`后端不可达：${BASE}/api/health 失败（${error.message}）。先运行 make dev，再跑 make screenshots。`);
    process.exitCode = 1;
    return;
  }

  for (const file of fs.readdirSync(OUT)) if (/^\d\d-.*\.png$/.test(file)) fs.unlinkSync(path.join(OUT, file));

  const subjects = new Set();
  const errors = [];
  const browser = await chromium.launch();
  try {
    let kept = null;
    // ---------- desktop: the whole first visit ----------
    const context = await browser.newContext({ viewport: DESKTOP });
    const page = await context.newPage();
    watch(page, "desktop", errors, subjects, [/status of 404/]);

    await page.goto(`${BASE}/`);
    await settle(page);
    await layout(page, "首页");
    check("首页：有“开始测评”和“先看学校”", (await page.getByRole("link", { name: "开始测评" }).count()) > 0 && (await page.getByRole("link", { name: "先看学校" }).count()) > 0);
    check("首页：示例时间线标了“示例”", (await page.locator("figure .pill-sample").count()) === 1);
    await screenshot(page, "home");

    await page.getByRole("link", { name: "开始测评" }).first().click();
    await page.waitForURL("**/assess");
    await settle(page);
    await page.getByRole("button", { name: "保存并查看结果" }).click();
    check("测评：缺必填项时不提交，并标出原因", page.url().endsWith("/assess") && (await page.locator(".field .error").count()) >= 5);
    await page.locator(".choice", { hasText: "本科" }).first().click();
    await page.locator(".choice", { hasText: "中国大陆" }).click();
    await page.locator("#school").fill("北京邮电");
    await page.locator(".suggest button", { hasText: "北京邮电大学" }).first().click();
    check("测评：选中名单里的学校后标出 211", (await page.locator(".field .hint", { hasText: "211" }).count()) > 0);
    await page.locator("#major").fill("软件工程");
    await page.locator("#gpa").fill("85");
    await page.getByLabel("分制").selectOption("100");
    await page.locator("#degree").selectOption("授课型硕士");
    await page.locator("#field").selectOption("计算机与数据");
    await page.locator("#english-test").selectOption("IELTS");
    await page.locator("#score").fill("6.5");
    await page.getByRole("button", { name: "保存并查看结果" }).click();
    check("测评：没填入学时间时标出该项", (await page.locator("#intake-error").count()) === 1 && page.url().endsWith("/assess"));
    await page.locator("#intake").selectOption("2027 S2");
    await layout(page, "测评");
    await screenshot(page, "assess");
    await page.getByRole("button", { name: "保存并查看结果" }).click();
    await page.waitForURL("**/assess/result");

    const saved = await page.evaluate(async () => (await fetch("/api/profile")).json());
    check("测评：提交后服务器档案就是填的值", saved.major === "软件工程" && saved.intake === "2027 S2" && saved.domesticTier === "211", saved);

    await page.locator("#t-保底, #t-稳妥, #t-冲刺").first().waitFor({ timeout: 30000 });
    await page.locator("#not-collected").waitFor({ timeout: 30000 });
    await settle(page);
    check("结果：说明分档不是录取概率", (await page.getByText("不是录取概率").count()) > 0);
    check("结果：没有“信息不足”这一档", (await page.getByText("信息不足").count()) === 0);
    await layout(page, "测评结果");
    await screenshot(page, "result");
    const addButtons = page.getByRole("button", { name: "加入组合" });
    const tieredCount = Math.min(3, await addButtons.count());
    for (let i = 0; i < tieredCount; i++) await addButtons.first().click();
    await page.locator("#not-collected").locator("xpath=../..").getByRole("button", { name: "加入，自选档位" }).first().click();
    await page.getByRole("group", { name: "选择档位" }).getByRole("button", { name: "冲" }).click();
    const added = tieredCount + 1;
    check("结果：加入后按钮显示“已加入”", (await page.getByRole("button", { name: /已加入|未分档/ }).count()) === added, { added });

    await page.getByRole("link", { name: /去选校/ }).click();
    await page.waitForURL("**/portfolio");
    await settle(page);
    check("组合：列出草稿里的全部项目", (await page.locator("tbody tr").count()) === added, { added });
    check("组合：自选档位的项目标“未经系统分档”", (await page.locator(".pill", { hasText: "未经系统分档" }).count()) === 1);
    await page.locator("tbody tr").first().locator("select").selectOption("offered");
    await page.locator("tbody tr").nth(1).getByText("设为首选").click();
    const before = await page.evaluate(async () => (await (await fetch("/api/applications")).json()).length);
    check("组合：没确认之前服务器上的组合不变", before === 0, { before });
    await layout(page, "选校组合");
    await screenshot(page, "portfolio");
    await page.getByRole("button", { name: `确认 ${added} 个项目` }).click();
    await page.getByText(`已保存 ${added} 个项目`).waitFor({ timeout: 15000 });
    const stored = await page.evaluate(async () => (await fetch("/api/applications")).json());
    check("组合：确认后服务器保存了全部项目", stored.length === added, stored.length);
    check("组合：状态和首选按草稿保存", stored.some((r) => r.status === "offered") && stored.filter((r) => r.isPrimary).length === 1);
    check("组合：自选档位的项目保存为 needsReview", stored.filter((r) => r.needsReview).length === 1);

    await page.getByRole("link", { name: "路线图" }).first().click();
    await page.waitForURL("**/roadmap");
    await page.locator("svg.timeline-svg").waitFor({ timeout: 20000 });
    await page.locator(".task input[type=checkbox]").first().waitFor();
    await settle(page);
    check("路线图：图例写明系统建议不是官方日期", (await page.getByText("系统建议 · 非官方日期").count()) > 0);
    check("路线图：没收录的截止显示为未收录", (await page.locator(".legend", { hasText: "未收录" }).count()) === 1);
    const firstOpen = page.locator(".task:not(.done) input[type=checkbox]").first();
    const taskId = await firstOpen.getAttribute("id");
    // A first visit writes the task rows; the box is enabled once its row is back.
    await page.locator(".task:not(.done) input[type=checkbox]:not([disabled])").first().waitFor({ timeout: 15000 });
    await page.locator(`[id="${taskId}"]`).check();
    await page.waitForResponse((r) => r.url().includes("/api/roadmap/tasks/") && r.request().method() === "PATCH", { timeout: 15000 });
    await page.reload();
    await page.locator(".task input[type=checkbox]").first().waitFor();
    await settle(page);
    // The phase may have moved on after the tick, so the box is found by id in whichever phase holds it.
    const stillTicked = await page.evaluate(async (key) => {
      const body = await (await fetch("/api/roadmap")).json();
      return body.tasks.some((t) => `t-${t.materialKey}` === key && t.status === "completed");
    }, taskId);
    check("路线图：勾选在刷新后仍保存着", stillTicked, taskId);
    const upload = page.locator(".task input[type=file]").first();
    // The library sniffs the type from the bytes and takes PDFs and images, so the file is a minimal PDF.
    const pdf = Buffer.from("%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n");
    await upload.setInputFiles({ name: "walkthrough-transcript.pdf", mimeType: "application/pdf", buffer: pdf });
    await page.getByText(/已上传 walkthrough-transcript\.pdf/).waitFor({ timeout: 15000 });
    check("路线图：任务行上传了文件", true);
    await layout(page, "路线图");
    await screenshot(page, "roadmap");

    await page.goto(`${BASE}/me`);
    await page.getByText("walkthrough-transcript.pdf").first().waitFor({ timeout: 15000 });
    await settle(page);
    check("我的背景：材料库列出上传的文件", true);
    await layout(page, "我的背景");
    await screenshot(page, "me");

    await page.goto(`${BASE}/advisor`);
    await settle(page);
    check("顾问：页面里没有 emoji", !/[\u{1F300}-\u{1FAFF}]/u.test(await page.locator("main").innerText()));
    await layout(page, "顾问");
    await screenshot(page, "advisor");

    await page.goto(`${BASE}/schools`);
    await settle(page);
    check("学校库：没有咨询按钮", (await page.getByText(/在线咨询|联系顾问/).count()) === 0);
    await layout(page, "学校库");
    await screenshot(page, "schools");
    await page.goto(`${BASE}/schools/00008C`);
    await settle(page);
    check("学校详情：学校库链接标为当前页", (await page.locator('nav[aria-label="主导航"] a[aria-current="page"]').allInnerTexts()).join() === "学校库");
    check("学校详情：列出这所学校的项目", (await page.locator("tbody tr a.l1").count()) > 0);
    await layout(page, "学校详情");
    await screenshot(page, "school");

    await page.goto(`${BASE}/programs/0100139`);
    await settle(page);
    check("项目详情：没收录的要求写“未收录”", (await page.locator(".req-table").getByText("未收录").count()) >= 2);
    check("项目详情：引用 CRICOS 数据集", (await page.getByText("CRICOS（澳大利亚教育部").count()) > 0);
    await layout(page, "项目详情");
    await screenshot(page, "program");

    await page.goto(`${BASE}/programs`);
    await settle(page);
    await layout(page, "项目库");

    await page.evaluate(() => {
      localStorage.clear();
      sessionStorage.clear();
    });
    await page.goto(`${BASE}/`);
    check("回访：清空浏览器存储后仍从首页进入路线图", page.url().endsWith("/roadmap"), page.url());
    const gone = await page.goto(`${BASE}/prototype/schools`);
    check("旧的原型路由已移除", gone.status() === 404, gone.status());
    const admin = await page.goto(`${BASE}/admin`);
    check("顾问后台不提供", admin.status() === 404, admin.status());
    // The phone pass shows the same applicant, so it takes the cookie the browser actually kept.
    kept = (await context.cookies(BASE)).find((c) => c.name === "leapashore_client") ?? null;
    if (kept) subjects.add(kept.value);
    await context.close();

    // ---------- phone ----------
    const fresh = await browser.newContext({ viewport: PHONE });
    const intro = await fresh.newPage();
    watch(intro, "phone-intro", errors, subjects);
    await intro.goto(`${BASE}/`);
    await settle(intro);
    await layout(intro, "首页 390");
    check("390：导航收进菜单", !(await intro.locator("#main-nav").isVisible()) && (await intro.getByRole("button", { name: "菜单" }).isVisible()));
    await intro.getByRole("button", { name: "菜单" }).click();
    check("390：按菜单后出现五个链接", await intro.locator("#main-nav").getByRole("link", { name: "学校库" }).isVisible());
    await screenshot(intro, "home-390");
    await fresh.close();

    const phone = await browser.newContext({ viewport: PHONE });
    if (kept) await phone.addCookies([{ name: "leapashore_client", value: kept.value, url: BASE }]);
    const p = await phone.newPage();
    watch(p, "phone", errors, subjects);
    for (const [route, name] of [
      ["/assess", "assess-390"],
      ["/assess/result", "result-390"],
      ["/portfolio", "portfolio-390"],
      ["/roadmap", "roadmap-390"],
      ["/me", "me-390"],
      ["/advisor", "advisor-390"],
      ["/schools", "schools-390"],
      ["/programs/cricos-0100139", "program-390"],
    ]) {
      await p.goto(`${BASE}${route}`);
      await settle(p);
      if (route === "/assess/result") await p.locator("#not-collected").waitFor({ timeout: 30000 }).catch(() => {});
      if (route === "/roadmap") await p.locator("svg.timeline-svg").waitFor({ timeout: 20000 }).catch(() => {});
      await layout(p, `${route} 390`);
      await screenshot(p, name);
    }
    await phone.close();
  } catch (error) {
    check("走查顺利跑完", false, String(error && error.message ? error.message : error).split("\n")[0]);
  } finally {
    await browser.close();
    if (subjects.size > 0) {
      const quoted = [...subjects].map((id) => `'${id.replace(/'/g, "''")}'`).join(",");
      dbRun(`DELETE FROM clients WHERE id IN (${quoted})`);
      const left = dbRun(`SELECT count(*) FROM clients WHERE id IN (${quoted})`);
      check(`走查结束时清理了本次创建的 ${subjects.size} 个主体`, left === "0", left);
    }
  }

  check("没有控制台错误或页面错误", errors.length === 0, errors.slice(0, 5));
  const failed = results.filter((r) => !r.ok);
  console.log(`\n${results.length - failed.length}/${results.length} 项通过，截图在 docs/screenshots/`);
  if (failed.length) process.exitCode = 1;
})();
