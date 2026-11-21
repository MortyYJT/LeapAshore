// Browser walkthrough in login mode (openspec account-login). A logged-out visitor types a question in the
// advisor and presses 发送 -> logs in with a mailed code -> fills the four basics -> the advisor sends the
// sentence that was typed (answered by a stub in the browser: the walkthrough never calls the paid model). Then /tiers -> /portfolio (confirm) -> 我的 (edit intake) -> /roadmap (tick,
// upload) -> 我的 (materials) -> the library pages -> logout. A second visitor presses 加入选校组合 on a
// program, registers, skips the info step, sees 先补信息 on /tiers, is refused /admin and deletes the account.
// A third registers, is refused /admin, is granted the admin role by the server command, reads one page on
// /admin, confirms it and withdraws it (openspec source-verification). Every page is then opened at 390px. Each step writes docs/screenshots/NN-*.png.
//
// The overview is checked in each state an account can be in: signed out (a labelled demo drawn from the
// catalogue, with the dates the catalogue serves, and the plain sign-in block when it cannot be read), a new
// account (the same, with the way to add the first application), an account with applications (one
// line each, the rail's list, stable colours), and a deadline within two weeks that is marked as
// submitted while another device has changed the record.
//
// The run fails on a console error, a page error, a page that scrolls sideways, a page without an h1,
// or a failed check. The accounts it creates are deleted from the database at the end, whatever happened.
//
// Usage: node scripts/walkthrough.cjs   (needs `make dev`: the web app on :3000 and the API on :8000 in
// login mode, which `make api-dev-bg` turns on; codes are read from api/var/mail.log)
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
const MAIL_LOG = path.join(ROOT, "api/var/mail.log");
const DESKTOP = { width: 1440, height: 900 };
const PHONE = { width: 390, height: 844 };

fs.mkdirSync(OUT, { recursive: true });

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok: Boolean(ok), detail });
  console.log(`${ok ? "通过" : "失败"}  ${name}${!ok && detail !== undefined ? `  ${JSON.stringify(detail)}` : ""}`);
}

// The account menu is in the rail on a desktop and in the top bar on a phone: the same button.
async function sidebarLogin(page) {
  if (!await page.locator("#user-menu").isVisible()) await page.getByRole("button", {name:"我的，打开用户菜单"}).click();
  await page.locator("#user-menu").getByRole("button", {name:"登录",exact:true}).click();
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

// A logged-out read of private data answers 401, and a refused code answers 400; the browser logs both.
const EXPECTED = [/status of 404/, /status of 401/];

// The sync-conflict steps make the server refuse a stale save on purpose; the browser logs that 409.
// Only those steps set this, so a 409 anywhere else still fails the run.
const conflictSteps = { running: false };
// The unsubscribe step opens a link the server refuses on purpose; the browser logs that 400.
const refusedLinkStep = { running: false };

/** Watch a page: console errors and page errors fail the run. */
function watch(page, label, errors, expected = EXPECTED) {
  page.on("console", (msg) => {
    if (msg.type() !== "error") return;
    const text = msg.text();
    if (expected.some((pattern) => pattern.test(text))) return;
    if (conflictSteps.running && /status of 409/.test(text)) return;
    if (refusedLinkStep.running && /status of 400/.test(text)) return;
    errors.push(`${label} console: ${text} (${new URL(page.url()).pathname})`);
  });
  page.on("pageerror", (error) => errors.push(`${label} pageerror: ${error.message}`));
}

/** The newest code the log mail backend wrote for `email`. */
async function codeFor(email, since) {
  for (let i = 0; i < 40; i++) {
    const lines = fs.existsSync(MAIL_LOG) ? fs.readFileSync(MAIL_LOG, "utf8").trim().split("\n") : [];
    const hit = lines.reverse().find((line) => line.split(" ")[1] === email && Date.parse(line.split(" ")[0]) >= since);
    if (hit) return hit.split(" ")[2];
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(`no code for ${email} in ${MAIL_LOG}`);
}

/** Log in through the dialog that is already open. Returns once the code is accepted. */
async function loginThroughDialog(page, email) {
  const dialog = page.locator("dialog.dialog:not(.workspace-search-dialog)");
  await dialog.locator("#login-email").fill(email);
  const since = Date.now() - 2000;
  await dialog.getByRole("button", { name: "发送验证码" }).click();
  await dialog.locator("#login-code").waitFor();
  await dialog.locator("#login-code").fill(await codeFor(email, since));
  await dialog.getByRole("button", { name: "登录", exact: true }).click();
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

/** A request to the API from outside the page, carrying the context's cookies (no console noise). */
async function apiAs(context, route, init = {}) {
  const cookie = (await context.cookies()).map((c) => `${c.name}=${c.value}`).join("; ");
  const response = await fetch(`${BASE}${route}`, { ...init, headers: { ...(init.headers || {}), cookie } });
  return { status: response.status, body: await response.json().catch(() => null) };
}

/** Grant the admin role the way production does: the server-side command, never an endpoint. */
function grantAdmin(email) {
  execFileSync(API_PYTHON, ["-m", "app.roles", "grant", email], { cwd: path.join(ROOT, "api"), encoding: "utf8" });
}

/**
 * The admin entry (openspec source-verification): 404 before the role, then the list, one page with its
 * quotes marked in the snapshot, the confirm button held until the read box is ticked, the confirmation
 * seen by the public catalogue, and the withdrawal. The page is always withdrawn before this returns.
 */
async function adminPass(browser, email, errors) {
  const context = await browser.newContext({ viewport: DESKTOP });
  const a = await context.newPage();
  watch(a, "admin", errors);
  let confirmed = null;
  try {
    await a.goto(`${BASE}/`);
    await settle(a);
    await sidebarLogin(a);
    await a.locator("dialog.dialog:not(.workspace-search-dialog)").waitFor();
    await loginThroughDialog(a, email);
    // A new account is offered the four-basics step; skipping it is what an admin would do.
    await a.locator("dialog.dialog:not(.workspace-search-dialog)").getByRole("button", { name: "跳过，以后再填" }).click({ timeout: 15000 }).catch(() => {});
    // A new account has no applications: the overview draws the axis and asks for the first one.
    await a.locator(".lt-empty").getByRole("link", { name: "添加申请项目" }).waitFor({ timeout: 15000 });
    await settle(a);
    check("总览（空账号）：只有时间轴和添加入口，没有申请行，也没有演示", (await a.locator(".lt-row").count()) === 0 && (await a.locator(".rail-legend").count()) === 0 && (await a.getByText("还没有申请。").count()) === 1
      && (await a.locator(".demo-note, .pill-sample").count()) === 0 && (await a.locator("#advisor-dock .composer-hint").innerText()).includes("只引用已收录的官方页面"));
    check("侧栏：登录后显示同步时间", /^已同步 \d\d:\d\d$/.test(await a.locator("button.rail-sync").innerText()), await a.locator("button.rail-sync").innerText());
    await screenshot(a, "overview-empty");
    const before = await a.goto(`${BASE}/admin`);
    check("管理页：授予管理员之前也是 404", before.status() === 404, before.status());
    grantAdmin(email);

    const page = await a.goto(`${BASE}/admin`);
    await settle(a);
    check("管理页：管理员打开是 200", page.status() === 200, page.status());
    await a.locator("tbody tr").first().waitFor({ timeout: 15000 });
    check("管理页：列出待核验的官方页面", (await a.locator("tbody tr").count()) > 0);
    check("管理页：同一页有知识缺口队列", (await a.getByRole("heading", { name: /知识缺口/ }).count()) === 1);
    await layout(a, "管理页");
    await screenshot(a, "admin");

    const link = a.locator("tbody tr").first().locator("a.l1");
    const sourceId = decodeURIComponent((await link.getAttribute("href")).split("/").pop());
    await link.click();
    await a.getByRole("heading", { name: "快照正文" }).waitFor({ timeout: 15000 });
    await settle(a);
    check("核验页：快照里标出了引文", (await a.locator(".snapshot mark").count()) > 0);
    const confirm = a.getByRole("button", { name: "确认核验" });
    check("核验页：没勾“已逐条对照”时确认按钮不可点", await confirm.isDisabled());
    await layout(a, "核验页");
    await screenshot(a, "admin-source");
    await a.getByLabel(/我已逐条对照/).check();
    await confirm.click();
    confirmed = sourceId;
    await a.getByRole("button", { name: "撤销核验" }).waitFor({ timeout: 15000 });
    check("核验页：确认后显示“已核验”和是谁确认的", (await a.getByText(email).count()) > 0);
    check("核验：库里这一页是“已核验”", dbRun(`SELECT status FROM sources WHERE id = '${sourceId}'`) === "已核验");
    const detail = await apiAs(context, `/api/admin/verification/${encodeURIComponent(sourceId)}`);
    const programId = detail.body.programs[0].id;
    const served = await (await fetch(`${BASE}/api/programs?ids=${encodeURIComponent(programId)}`)).json();
    check("核验：项目接口给申请人看到“已核验”", served[0] && served[0].source.status === "已核验", served[0] && served[0].source);

    await a.getByRole("button", { name: "撤销核验" }).click();
    await confirm.waitFor({ timeout: 15000 });
    confirmed = null;
    check("核验：撤销后库里回到“待核验”", dbRun(`SELECT status FROM sources WHERE id = '${sourceId}'`) === "待核验");

    await a.setViewportSize(PHONE);
    await a.goto(`${BASE}/admin/sources/${encodeURIComponent(sourceId)}`);
    await a.getByRole("heading", { name: "快照正文" }).waitFor({ timeout: 15000 });
    await settle(a);
    await layout(a, "核验页 390");
    await a.goto(`${BASE}/admin`);
    await a.locator("tbody tr").first().waitFor({ timeout: 15000 });
    await settle(a);
    await layout(a, "管理页 390");
  } finally {
    // A failed run must not leave a page verified in the developer's database.
    if (confirmed) await apiAs(context, `/api/admin/verification/${encodeURIComponent(confirmed)}/revoke`, { method: "POST" });
    await context.close();
  }
}

(async () => {
  try {
    const response = await fetch(`${BASE}/api/health`);
    if (!response.ok) throw new Error(`GET /api/health responded ${response.status}`);
    const auth = await (await fetch(`${BASE}/api/auth/me`)).json();
    if (!auth.authEnabled) throw new Error("login mode is off: start the API with AUTH_ENABLED=true (make api-dev-bg does)");
  } catch (error) {
    console.error(`后端不可达或没开登录模式：${error.message}。先运行 make dev，再跑 make screenshots。`);
    process.exitCode = 1;
    return;
  }

  for (const file of fs.readdirSync(OUT)) if (/^\d\d-.*\.png$/.test(file)) fs.unlinkSync(path.join(OUT, file));

  const stamp = Date.now().toString(36);
  const emails = [`walkthrough-${stamp}@example.test`, `walkthrough-${stamp}-b@example.test`, `walkthrough-${stamp}-admin@example.test`];
  const errors = [];
  let firstCodeAt = Date.now();
  const browser = await chromium.launch();
  try {
    let session = null;
    // ---------- desktop: logged out ----------
    const context = await browser.newContext({ viewport: DESKTOP });
    const page = await context.newPage();
    watch(page, "desktop", errors);
    // Nothing a signed-out visitor's overview does may write: every request until the demo checks end is a GET.
    const demoWrites = [];
    const noteWrite = (request) => {
      if (request.method() !== "GET") demoWrites.push(`${request.method()} ${new URL(request.url()).pathname}`);
    };
    page.on("request", noteWrite);

    await page.goto(`${BASE}/`);
    await settle(page);
    await layout(page, "首页");
    check("首页：标题是总览", await page.getByRole("heading", { level: 1, name: "总览", exact: true }).isVisible());
    // ---------- the signed-out demo ----------
    // What the rule gives for this catalogue today, worked out apart from the page. Once every collected
    // date has passed there is no demo to check, and the page must show the plain block instead.
    const demoRule = await import(path.join(ROOT, "web/lib/demo.ts"));
    const demoToday = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
    const readCatalogue = async (query) => {
      const params = new URLSearchParams();
      if (query.ids) params.set("ids", query.ids.join(","));
      if (query.provider) params.set("provider", query.provider.join(","));
      if (query.hasRequirements !== undefined) params.set("has_requirements", String(query.hasRequirements));
      if (query.q) params.set("q", query.q);
      if (query.limit !== undefined) params.set("limit", String(query.limit));
      return (await context.request.get(`${BASE}/api/programs?${params}`)).json();
    };
    const demoPrograms = await demoRule.loadDemoPrograms(demoToday, readCatalogue);
    const expectedDemo = demoRule.demoRecords(demoPrograms, demoToday);
    await page.locator(".lt-row, .lt-empty").first().waitFor({ timeout: 25000 });
    check("首页（未登录）：学校库给得出演示时画演示，给不出时不画", ((await page.locator(".lt-row").count()) > 0) === (expectedDemo !== null), { expected: expectedDemo && expectedDemo.length });
    if (!expectedDemo) {
      console.log("跳过  演示的各项检查：本地学校库里有未过期截止日期的项目不到两个");
      check("首页（未登录）：给出登录入口", await page.locator(".lt-empty").getByRole("button", { name: "登录", exact: true }).isVisible());
    } else {
    const demoRows = await page.locator(".lt-row").evaluateAll((rows) => rows.map((row) => ({
      href: row.querySelector(".school a").getAttribute("href"),
      school: row.querySelector(".school a").textContent.trim(),
      name: row.querySelector(".program").textContent.trim(),
      track: row.querySelector(".c-track").getAttribute("aria-label"),
      sent: row.classList.contains("is-sent"),
    })));
    check("首页（未登录）：画出演示，并在标题、说明和「接下来」标明", demoRows.length >= 2 && await page.locator(".lt .a-today").isVisible()
      && (await page.locator(".page-head .pill-sample", { hasText: "演示" }).count()) === 1
      && (await page.locator(".demo-note").innerText()).includes("这是演示：项目和截止日期来自学校库")
      && (await page.locator("#h-next + .pill-sample").count()) === 1, demoRows.length);
    check("首页（未登录）：给出登录入口", await page.locator(".demo-note").getByRole("button", { name: "登录", exact: true }).isVisible());
    // What the catalogue serves for the same programs, read apart from the page: the demo may show nothing else.
    const demoIds = demoRows.map((row) => decodeURIComponent((row.href || "").replace("/programs/", "")));
    const catalogued = await page.evaluate(async (ids) => (await fetch(`/api/programs?ids=${ids.map(encodeURIComponent).join(",")}`)).json(), demoIds);
    const mismatched = demoRows.filter((row, index) => {
      const program = catalogued.find((item) => item.slug === demoIds[index]);
      if (!program || !row.href.startsWith("/programs/")) return true;
      const ahead = program.deadlines.map((d) => d.date).filter((date) => date >= demoToday).sort();
      const expected = program.deadlines.length === 0 ? "截止日期待确认" : ahead.length ? `${ahead[0]} 截止` : null;
      return row.track !== expected || row.school !== program.university || row.name !== (program.nameEn || program.name);
    });
    check("演示：每一行的学校、项目和日期都是学校库接口给的，行名链接到公开的项目页", mismatched.length === 0, mismatched);
    check("演示：画的正是规则选出的那几个项目", JSON.stringify([...demoIds].sort()) === JSON.stringify(expectedDemo.map((record) => record.programId).sort()), demoIds);
    check("演示：状态有一个已提交，没日期的只在学校库确实没有日期时画成待确认", demoRows.filter((row) => row.sent).length === 1
      && demoRows.filter((row) => row.track === "截止日期待确认").length <= 1);
    check("演示：不显示要读账号的「准备任务」", (await page.locator("#h-tasks").count()) === 0);
    check("侧栏：未登录时列出演示并标明，同步状态是登录入口", (await page.locator(".rail-legend li").count()) === demoRows.length
      && (await page.locator(".rail-legend-title .pill-sample", { hasText: "演示" }).count()) === 1
      && await page.locator("button.rail-sync", { hasText: "登录后同步到账号" }).isVisible());
    await page.locator(".rail-legend button").first().click();
    check("演示：在侧栏选中一行，其余的线退后", (await page.locator(".lt.has-sel .lt-row.is-sel").count()) === 1);
    await page.locator(".rail-legend button").first().click();
    const gate = page.locator("dialog.dialog:not(.workspace-search-dialog)");
    const writing = page.locator(".next").getByRole("button", { name: /^(更新材料|标记为已提交)$/ });
    let gatedActions = (await writing.count()) > 0;
    for (let i = 0; i < await writing.count(); i++) {
      await writing.nth(i).click();
      gatedActions = gatedActions && await gate.getByRole("heading", { name: "登录" }).isVisible().catch(() => false);
      await page.keyboard.press("Escape");
      await gate.waitFor({ state: "hidden" });
    }
    check("演示：会写入的操作只打开登录", gatedActions);
    const demoAsk = page.locator(".next").getByRole("link", { name: "让顾问去查" });
    if (await demoAsk.count()) {
      await demoAsk.first().click();
      const put = await page.locator("#advisor-input").inputValue();
      check("演示：让顾问去查只把问题放进输入框，不发送", put.endsWith("的申请截止日期是哪天？") && (await page.locator(".turn").count()) === 0 && !await gate.isVisible(), put);
      await page.locator("#advisor-input").fill("");
    }
    check("停靠栏（未登录）：保留能力说明，输入区写明提问需要登录并给出登录入口", (await page.locator("#advisor-dock .how .step").count()) === 4
      && (await page.locator("#advisor-dock .composer-hint").innerText()).includes("提问需要登录")
      && await page.locator("#advisor-dock .composer-hint").getByRole("button", { name: "登录", exact: true }).isVisible()
      && (await page.locator("#advisor-input").getAttribute("placeholder")).includes("登录后发送"));
    await page.locator("#advisor-dock .composer-hint").getByRole("button", { name: "登录", exact: true }).click();
    check("停靠栏（未登录）：登录入口打开登录", await gate.getByRole("heading", { name: "登录" }).isVisible());
    await page.keyboard.press("Escape");
    await gate.waitFor({ state: "hidden" });
    }
    check("演示：从打开首页起没有发出任何写入请求", demoWrites.length === 0, demoWrites);
    page.off("request", noteWrite);
    // The catalogue has nothing to draw, or cannot be read: the plain block, with nothing labelled a demo.
    for (const [body, name] of [["[]", "学校库给不出项目"], ["{}", "读到的不是项目列表"]]) {
      await page.route("**/api/programs?**", (route) => route.fulfill({ status: 200, contentType: "application/json", body }));
      await page.goto(`${BASE}/`);
      await page.locator(".lt-empty").waitFor({ timeout: 15000 });
      check(`首页（未登录）：${name}时退回登录入口，不画演示`, (await page.locator(".lt-row").count()) === 0 && (await page.locator(".rail-legend").count()) === 0
        && (await page.getByText("演示").count()) === 0 && await page.locator(".lt-empty").getByRole("button", { name: "登录", exact: true }).isVisible());
      await page.unroute("**/api/programs?**");
    }
    await page.goto(`${BASE}/`);
    await page.locator(".lt-row, .lt-empty").first().waitFor({ timeout: 25000 });
    check("字体：不从其他主机加载", await page.evaluate(() => performance.getEntriesByType("resource").every((entry) => new URL(entry.name).origin === location.origin)));
    check("导航：侧栏有六个入口，材料在其中", await page.locator('nav[aria-label="主导航"] a').count() === 6
      && await page.locator('nav[aria-label="主导航"]').getByRole("link", { name: "材料", exact: true }).isVisible());
    // ---------- 材料, signed out: the catalogue's collected materials as a demo, or the plain block ----------
    // The same programs, in the same order, as the page works from (`ApplicationRecords.tsx`).
    const mapRule = await import(path.join(ROOT, "web/lib/materials-map.ts"));
    const demoDrawn = new Set((expectedDemo || []).map((record) => record.programId));
    const expectedMap = mapRule.demoMaterialRecords(demoPrograms.filter((program) => demoDrawn.has(program.slug))) || mapRule.demoMaterialRecords(demoPrograms);
    const mapWrites = [];
    const noteMapWrite = (request) => {
      if (request.method() !== "GET") mapWrites.push(`${request.method()} ${new URL(request.url()).pathname}`);
    };
    page.on("request", noteMapWrite);
    await page.goto(`${BASE}/materials`);
    await page.locator(".map svg, .map-empty").first().waitFor({ timeout: 25000 });
    await settle(page);
    await layout(page, "材料（未登录）");
    check("材料（未登录）：学校库提取过足够的项目才画演示，否则只给登录入口", ((await page.locator(".map svg").count()) > 0) === (expectedMap !== null), { expected: expectedMap && expectedMap.length });
    if (!expectedMap) {
      check("材料（未登录）：没有可画的要求时不画线路图，不标演示，给出登录入口", (await page.locator(".map .stn, .map .hub, .map .ln").count()) === 0
        && (await page.locator(".page-head .pill-sample").count()) === 0 && await page.locator(".map-empty").getByRole("button", { name: "登录", exact: true }).isVisible());
    } else {
      const stops = expectedMap.reduce((sum, record) => sum + record.materials.length, 0);
      const demoModel = mapRule.materialsModel(expectedMap);
      const sharedStops = demoModel.shared.reduce((sum, column) => sum + column.requirements.length, 0);
      // Every station is a collected requirement that is not on the shared trunk; none is drawn that the catalogue did not serve.
      check("材料（未登录）：演示里的每一站都是学校库给的要求，并标明是演示", (await page.locator(".map .stn").count()) === demoModel.differing.reduce((sum, column) => sum + column.requirements.length, 0)
        && (await page.locator(".map .hub").count()) === demoModel.shared.length && stops >= sharedStops
        && (await page.locator(".page-head .pill-sample", { hasText: "演示" }).count()) === 1
        && (await page.locator(".demo-note").innerText()).includes("项目和材料要求来自学校库"));
      check("材料（未登录）：演示里没有一项是勾上的", (await page.locator(".map .stn.is-ready, .map .hub.is-ready").count()) === 0 && (await page.locator(".bt input:checked").count()) === 0);
      const toggle = page.locator(".bt input").first();
      if (await toggle.count()) {
        await toggle.click({ force: true });
        const gate = page.locator("dialog.dialog:not(.workspace-search-dialog)");
        await gate.waitFor({ timeout: 10000 });
        check("材料（未登录）：勾选只打开登录", await gate.isVisible());
        await page.keyboard.press("Escape");
        await gate.waitFor({ state: "hidden" });
      }
    }
    check("材料（未登录）：没有发出任何写入请求", mapWrites.length === 0, mapWrites);
    page.off("request", noteMapWrite);
    await page.goto(`${BASE}/`);
    await page.locator(".lt-row, .lt-empty").first().waitFor({ timeout: 25000 });
    check("首页：不显示全局声明或隐私政策页脚", await page.locator("footer.site-foot, footer.foot, .source-note").count() === 0);
    check("导航：没有“项目库”", (await page.locator('nav[aria-label="主导航"]').getByRole("link", { name: "项目库" }).count()) === 0);
    check("布局：没有顶栏", await page.locator(".workspace-header").count() === 0);
    await page.getByRole("button", { name: "折叠侧边栏" }).click();
    check("侧栏：折叠为图标栏", await page.locator(".sidebar-collapsed").count() === 1 && await page.getByRole("link", {name:"学校库",exact:true}).isVisible());
    await page.reload();
    await page.getByRole("button", { name: "展开侧边栏" }).waitFor();
    check("侧栏：刷新保留折叠", true);
    const railBrand = page.getByRole("button", {name:"展开侧边栏"});
    await page.mouse.move(500, 400);
    check("折叠图标：默认显示产品标识", await railBrand.locator(".rail-mark").isVisible() && !await railBrand.locator(".rail-expand").isVisible());
    await railBrand.hover();
    check("折叠图标：悬停切换展开图标", !await railBrand.locator(".rail-mark").isVisible() && await railBrand.locator(".rail-expand").isVisible());
    await page.getByRole("button", { name: "展开侧边栏" }).click();
    await page.getByRole("button", { name: "搜索", exact:true }).click();
    await page.getByRole("textbox", { name: "搜索页面或学校" }).fill("Imperial");
    await page.getByRole("button", {name:"搜索学校",exact:true}).click();
    await page.waitForURL(/schools.*q=Imperial/);
    check("搜索：真实学校库返回帝国理工", await page.getByRole("link", {name:/帝国理工/}).count() > 0);
    await page.goto(`${BASE}/`);
    await page.getByRole("button", {name:"我的，打开用户菜单"}).click();
    check("头像菜单：包含登录和设置，外观收进设置", await page.locator("#user-menu").getByRole("button", {name:"登录",exact:true}).isVisible() && await page.locator("#user-menu").getByRole("button", {name:"设置",exact:true}).isVisible() && await page.locator("#user-menu").getByRole("button",{name:"深色",exact:true}).count() === 0);
    await page.keyboard.press("Escape");
    await screenshot(page, "home");

    await page.goto(`${BASE}/roadmap`);
    await settle(page);
    check("未登录：路线图是标了演示的示例，并请你登录", (await page.locator(".roadmap h1 + .pill-sample", { hasText: "演示" }).count()) === 1
      && (await page.locator(".roadmap .demo-note").getByRole("button", { name: "登录", exact: true }).count()) === 1
      && (await page.locator(".rm-wide .rm-step").count()) > 0 && (await page.locator(".rm-list .rm-tick").count()) > 0);
    // A tick in the sample saves nothing: it asks the visitor to sign in.
    await page.locator(".rm-list .rm-tick").first().click();
    check("未登录：示例里勾选不保存，弹出登录", (await page.getByRole("dialog").count()) === 1);
    await page.keyboard.press("Escape");
    await layout(page, "路线图（未登录）");
    // While the session is being read, the page keeps its title and shows loading bars, not a bare line.
    await page.route("**/api/auth/me", async (route) => {
      await new Promise((r) => setTimeout(r, 2500));
      await route.continue().catch(() => {});
    });
    await page.goto(`${BASE}/tiers`, { waitUntil: "domcontentloaded" });
    await page.locator(".skeleton").first().waitFor({ timeout: 5000 }).catch(() => {});
    check("读取登录状态时：分档页保留标题并显示占位", (await page.locator("main h1", { hasText: "分档结果" }).count()) === 1 && (await page.locator(".skeleton").count()) > 0);
    await page.unroute("**/api/auth/me");
    await page.goto(`${BASE}/me`);
    await settle(page);
    check("未登录：我的页请你登录", (await page.getByText("登录后查看你的背景和材料").count()) === 1);
    const anonymous = await page.evaluate(async () => (await fetch("/api/profile")).status);
    check("未登录：读档案返回 401", anonymous === 401, anonymous);
    const assess = await page.goto(`${BASE}/assess`);
    check("背景测评页已删除，跳到分档页", page.url().endsWith("/tiers") && assess.status() === 200, page.url());

    // ---------- 未登录点发送 -> 登录 -> 信息页 -> 回到顾问并发出原句 ----------
    // The advisor is never really asked: a reply costs a paid model call. The browser's request is
    // answered here with a one-line stub, and the request itself is checked for the sentence and session.
    await page.route("**/api/advisor/**", (route) => route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: 'data: {"type":"token","text":"走查不调用顾问。"}\n\ndata: {"type":"done"}\n\n',
    }));
    await page.goto(`${BASE}/advisor`);
    await settle(page);
    check("顾问：页面里没有 emoji", !/[\u{1F300}-\u{1FAFF}]/u.test(await page.locator("main").innerText()));
    const question = "我是北邮软件工程，均分 85，雅思 6.5，能申哪些计算机硕士？";
    await page.locator("#advisor-input").fill(question);
    check("顾问页（未登录）：输入区写明提问需要登录", (await page.locator(".advisor-page .composer-hint").innerText()).includes("提问需要登录"));
    await page.getByRole("button", { name: "登录后发送", exact: true }).click();
    const dialog = page.locator("dialog.dialog:not(.workspace-search-dialog)");
    await dialog.waitFor();
    check("顾问：未登录点发送弹出登录", await dialog.getByRole("heading", { name: "登录" }).isVisible());
    check("顾问：登录时原句还在输入框里", (await page.locator("#advisor-input").inputValue()) === question);
    await layout(page, "登录弹窗");
    await screenshot(page, "login");
    await dialog.locator("#login-email").fill("not-an-email");
    await dialog.getByRole("button", { name: "发送验证码" }).click();
    check("登录：邮箱格式不对时不发送", (await dialog.getByRole("alert").innerText()).includes("邮箱"));
    firstCodeAt = Date.now();
    await loginThroughDialog(page, emails[0]);
    await dialog.getByRole("heading", { name: "补充四项信息" }).waitFor({ timeout: 15000 });
    check("注册：首次登录后弹出信息页", true);
    const sentChat = page.waitForRequest((r) => r.url().endsWith("/api/advisor/chat") && r.method() === "POST", { timeout: 15000 });
    await dialog.getByRole("button", { name: "保存，继续" }).click();
    check("信息页：缺必填项时不提交", (await dialog.locator(".field .error").count()) >= 3 && (await dialog.isVisible()));
    await dialog.locator(".choice", { hasText: "中国大陆" }).click();
    await dialog.locator("#basics-school").fill("北京邮电");
    await dialog.locator(".suggest button", { hasText: "北京邮电大学" }).first().click();
    check("信息页：选中名单里的学校后标出 211", (await dialog.locator(".field .hint", { hasText: "211" }).count()) > 0);
    await dialog.locator("#basics-gpa").fill("85");
    await dialog.getByLabel("分制").selectOption("100");
    await dialog.locator("#basics-field").selectOption("计算机与数据");
    await dialog.locator("#basics-english-test").selectOption("IELTS");
    await dialog.locator("#basics-score").fill("6.5");
    await screenshot(page, "basics");
    await dialog.getByRole("button", { name: "保存，继续" }).click();
    const chat = await sentChat;
    const sentBody = JSON.parse(chat.postData() || "{}");
    check("顾问：登录后发出的就是原句", sentBody.message === question, sentBody);
    await page.locator(".msg-user", { hasText: question }).waitFor({ timeout: 15000 });
    check("顾问：对话里显示原句，输入框已清空", (await page.locator("#advisor-input").inputValue()) === "");
    // The stubbed request never reaches the network, so its cookie header is not a reliable witness. The
    // request is checked for where it went and what it carried, and the session is read from the server.
    check("顾问：发送请求打到 /api/advisor/chat（POST，带对话 id）", new URL(chat.url()).pathname === "/api/advisor/chat" && chat.method() === "POST" && typeof sentBody.conversationId === "string" && sentBody.conversationId.length > 0, { url: chat.url(), sentBody });
    const me = await page.evaluate(async () => (await fetch("/api/auth/me", { cache: "no-store" })).json());
    check("顾问：发送时浏览器处在登录会话里（/api/auth/me 返回这个账号）", me && me.account && me.account.email === emails[0], me && me.account);
    await settle(page);
    await layout(page, "顾问");
    await screenshot(page, "advisor");
    const basics = await page.evaluate(async () => (await fetch("/api/profile")).json());
    check("信息页：服务器档案就是填的四项", basics.schoolName === "北京邮电大学" && basics.domesticTier === "211" && Number(basics.gpaScore) === 85 && basics.targetField === "计算机与数据" && basics.englishScore === "IELTS 6.5", basics);
    check("登录后顶栏显示用户菜单", await page.getByRole("button", { name: "我的，打开用户菜单" }).isVisible());
    await page.getByRole("button", { name: "我的，打开用户菜单" }).click();
    await page.getByRole("button", { name: "设置", exact: true }).click();
    await page.getByRole("tab", { name: "外观", exact: true }).click();
    await page.getByRole("button", { name: "深色", exact: true }).click();
    check("设置：主题应用到全站", await page.locator("html").getAttribute("data-appearance") === "dark" && await page.locator("html").getAttribute("data-accent") === "graphite");
    await page.getByRole("button", { name: "关闭设置" }).click();
    await page.reload();
    await page.waitForFunction(() => document.documentElement.dataset.appearance === "dark");
    check("设置：刷新后保留外观", await page.locator("html").getAttribute("data-appearance") === "dark");
    await page.getByRole("button", { name: "我的，打开用户菜单" }).click();
    await page.getByRole("button", { name: "设置", exact: true }).click();
    await page.getByRole("tab", { name: "外观", exact: true }).click();
    await page.getByRole("button", { name: "恢复默认外观" }).click();
    await page.getByRole("button", { name: "关闭设置" }).click();

    // ---------- deadline reminders: settings and the unsubscribe page ----------
    await page.getByRole("button", { name: "我的，打开用户菜单" }).click();
    await page.getByRole("button", { name: "设置", exact: true }).click();
    await page.getByRole("tab", { name: "提醒", exact: true }).click();
    const reminderPanel = page.locator("#uc-panel-reminders");
    const reminderSwitch = reminderPanel.getByRole("group", { name: "邮件提醒" });
    await reminderSwitch.waitFor();
    check("提醒设置：默认开启，提前 14、7、3、1 天", await reminderSwitch.getByRole("button", { name: "开启", exact: true }).getAttribute("aria-pressed") === "true" && (await reminderPanel.locator(".uc-leads li .num").allTextContents()).join(",") === "14,7,3,1");
    await reminderPanel.getByLabel("要加的提前天数").fill("7");
    await reminderPanel.getByRole("button", { name: "添加", exact: true }).click();
    check("提醒设置：重复的天数不保存，原因写在输入框下", await reminderPanel.getByText("已经有提前 7 天的提醒了。").isVisible());
    await reminderPanel.getByLabel("要加的提前天数").fill("10");
    await reminderPanel.getByRole("button", { name: "添加", exact: true }).click();
    await page.getByText("提醒设置已保存。").waitFor();
    await reminderSwitch.getByRole("button", { name: "关闭", exact: true }).click();
    await page.waitForFunction(async () => (await (await fetch("/api/reminders/settings")).json()).enabled === false);
    const remindersOff = await apiAs(context, "/api/reminders/settings");
    check("提醒设置：改动存到服务器（关闭，天数 14、10、7、3、1）", remindersOff.body && remindersOff.body.enabled === false && remindersOff.body.leadDays.join(",") === "14,10,7,3,1", remindersOff.body);
    await reminderPanel.getByRole("button", { name: "删掉提前 10 天的提醒" }).click();
    await page.waitForFunction(async () => (await (await fetch("/api/reminders/settings")).json()).leadDays.length === 4);
    await reminderSwitch.getByRole("button", { name: "开启", exact: true }).click();
    await page.waitForFunction(async () => (await (await fetch("/api/reminders/settings")).json()).enabled === true);
    // ---------- settings: the applicant's own model key (PRD-multi-device 3.5) ----------
    const OWN_KEY = "sk-walkthrough0000000000000000beef";
    await page.getByRole("tab", { name: "模型密钥", exact: true }).click();
    const keyPanel = page.locator("#uc-panel-model");
    check("模型密钥：说明密钥存在哪里、会经过服务器、运营者读得到", await keyPanel.getByRole("heading", { name: "这把密钥会到哪里" }).isVisible() && /只存在这台设备的这个浏览器里/.test(await keyPanel.innerText()) && /运营者在技术上读得到/.test(await keyPanel.innerText()));
    await keyPanel.getByRole("textbox", { name: "密钥" }).fill("sk-abc def");
    await keyPanel.getByRole("button", { name: "保存", exact: true }).click();
    check("模型密钥：带空格的密钥不保存，原因写在输入框下", await keyPanel.getByRole("alert").filter({ hasText: "不应该有空格" }).isVisible() && await page.evaluate(() => localStorage.getItem("leapashore:model-key")) === null);
    await keyPanel.getByRole("group", { name: "服务商" }).getByRole("button", { name: "硅基流动", exact: true }).click();
    await keyPanel.getByRole("textbox", { name: "密钥" }).fill(OWN_KEY);
    await keyPanel.getByRole("button", { name: "保存", exact: true }).click();
    await keyPanel.getByText("sk-…beef").waitFor();
    const keyStored = await page.evaluate(() => JSON.parse(localStorage.getItem("leapashore:model-key") ?? "null"));
    check("模型密钥：保存在这个浏览器里，页面上只显示头尾", keyStored && keyStored.provider === "siliconflow" && keyStored.key === OWN_KEY && !(await page.locator("body").innerText()).includes(OWN_KEY) && await keyPanel.getByRole("textbox").count() === 0, keyStored && keyStored.provider);
    await keyPanel.getByRole("button", { name: "删除", exact: true }).click();
    await keyPanel.getByRole("textbox", { name: "密钥" }).waitFor();
    check("模型密钥：删除后浏览器里不再有它", await page.evaluate(() => localStorage.getItem("leapashore:model-key")) === null);
    await page.getByRole("button", { name: "关闭设置" }).click();
    // Opening the link sends nothing (a mail gateway opens every link); the button does.
    let unsubscribePosts = 0;
    const countUnsubscribe = (request) => {
      if (request.method() === "POST" && request.url().includes("/api/reminders/unsubscribe")) unsubscribePosts += 1;
    };
    page.on("request", countUnsubscribe);
    refusedLinkStep.running = true;
    await page.goto(`${BASE}/reminders/unsubscribe?token=bad.token`);
    await page.getByRole("heading", { level: 1, name: "退订截止提醒", exact: true }).waitFor();
    const confirmUnsubscribe = page.getByRole("button", { name: "确认退订", exact: true });
    await confirmUnsubscribe.waitFor();
    // The button is in the server's HTML; wait until the page's scripts have run before counting.
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(800);
    check("退订页：打开链接不发请求，页面上有「确认退订」", unsubscribePosts === 0, unsubscribePosts);
    await confirmUnsubscribe.click();
    await page.getByRole("heading", { level: 1, name: "这个退订链接无效" }).waitFor();
    refusedLinkStep.running = false;
    page.off("request", countUnsubscribe);
    check("退订页：点确认后才发出一次请求", unsubscribePosts === 1, unsubscribePosts);
    const remindersKept = await apiAs(context, "/api/reminders/settings");
    check("退订页：无效链接说明原因，提醒设置没有被改动", remindersKept.body && remindersKept.body.enabled === true && remindersKept.body.leadDays.join(",") === "14,7,3,1", remindersKept.body);
    await layout(page, "退订页");

    // ---------- tiers -> portfolio ----------
    await page.goto(`${BASE}/tiers`);
    await page.locator("#t-保底, #t-稳妥, #t-冲刺").first().waitFor({ timeout: 30000 });
    await page.locator("#not-collected").waitFor({ timeout: 30000 });
    await settle(page);
    check("分档：说明分档不是录取概率", (await page.getByText("不是录取概率").count()) > 0);
    check("分档：没有“信息不足”这一档", (await page.getByText("信息不足").count()) === 0);
    await layout(page, "分档结果");
    await screenshot(page, "tiers");
    const addButtons = page.getByRole("button", { name: "加入组合" });
    const tieredCount = Math.min(3, await addButtons.count());
    for (let i = 0; i < tieredCount; i++) await addButtons.first().click();
    await page.locator("#not-collected").locator("xpath=../..").getByRole("button", { name: "加入，自选档位" }).first().click();
    await page.getByRole("group", { name: "选择档位" }).getByRole("button", { name: "冲" }).click();
    const added = tieredCount + 1;
    check("分档：加入后按钮显示“已加入”", (await page.getByRole("button", { name: /已加入|未分档/ }).count()) === added, { added });

    await page.getByRole("link", { name: /去选校/ }).click();
    await page.waitForURL("**/portfolio");
    await settle(page);
    check("组合：列出草稿里的全部项目", (await page.locator("tbody tr").count()) === added, { added });
    check("组合：自选档位的项目标“未经系统分档”", (await page.locator(".pill", { hasText: "未经系统分档" }).count()) === 1);
    // One set of names for a status on every screen: the overview's.
    check("组合：申请状态用总览那一套叫法", (await page.locator("tbody tr").first().locator("select option").allInnerTexts()).join("|") === "考虑中|准备中|已提交|收到录取|未录取|已放弃");
    await page.locator("tbody tr").first().locator("select").selectOption("offered");
    await page.locator("tbody tr").nth(1).getByText("设为首选").click();
    const before = await page.evaluate(async () => (await (await fetch("/api/applications")).json()).length);
    check("组合：没确认之前服务器上的组合不变", before === 0, { before });
    await layout(page, "选校组合");
    await screenshot(page, "portfolio");
    await page.getByRole("button", { name: `确认 ${added} 个项目` }).click();
    await page.getByText(`已保存 ${added} 个项目`).waitFor({ timeout: 15000 });
    // The rail lists the applications that are being prepared or are submitted (one row here is 收到录取).
    const listed = await page.evaluate(async () => (await (await fetch("/api/application-records")).json()).filter((r) => ["considering", "applying", "submitted"].includes(r.status)).length);
    const inRail = await page.waitForFunction((n) => document.querySelectorAll(".rail-legend li").length === n, listed, { timeout: 15000 }).then(() => true, () => false);
    check("组合：确认后侧栏不用刷新就列出这些申请", inRail && listed > 0, { listed, shown: await page.locator(".rail-legend li").count() });
    const stored = await page.evaluate(async () => (await fetch("/api/applications")).json());
    check("组合：确认后服务器保存了全部项目", stored.length === added, stored.length);
    check("组合：状态和首选按草稿保存", stored.some((r) => r.status === "offered") && stored.filter((r) => r.isPrimary).length === 1);
    check("组合：自选档位的项目保存为 needsReview", stored.filter((r) => r.needsReview).length === 1);

    // Personal records use the real scoped API, alongside saved catalogue choices.
    await page.goto(`${BASE}/applications`);
    await page.getByRole("button", {name:"添加申请项目",exact:true}).click();
    const applicationForm=page.locator(".application-dialog");
    await applicationForm.getByLabel("学校名称", {exact:true}).fill("示例大学（演示账号）");
    await applicationForm.getByLabel("项目名称", {exact:true}).fill("硕士项目 · 申请管理演示");
    await applicationForm.getByLabel("申请轮次", {exact:true}).fill("第一轮");
    await applicationForm.getByLabel("截止日期", {exact:true}).fill("2027-01-15");
    await applicationForm.getByLabel("日期来源链接", {exact:true}).fill("https://example.edu/apply");
    await applicationForm.getByLabel("我已自行核对本轮截止日期与来源").check();
    await applicationForm.getByLabel("材料与准备备注").fill("演示记录：个人陈述初稿待完成，推荐人待确认。");
    // Material checklist (PRD-multi-device 3.7): a manual application has only the applicant's own lines.
    for (const line of ["个人陈述", "推荐信"]) {
      await applicationForm.getByLabel("加一项自己的材料").fill(line);
      await applicationForm.getByRole("button", {name:"添加",exact:true}).click();
    }
    await applicationForm.getByRole("checkbox", {name:"推荐信",exact:true}).check();
    await applicationForm.getByRole("button", {name:"保存申请",exact:true}).click();
    await page.reload();
    const manualCard=page.locator(".application-card").filter({hasText:"示例大学（演示账号）"});
    await manualCard.waitFor();
    check("我的申请：手动项目及轮次刷新后保留", await manualCard.getByText(/第一轮/).count()>0 && await manualCard.getByText(/已自行核对/).count()>0);
    check("材料清单：自己列的两项保存下来，勾了一项", (await manualCard.getByText("材料 1/2", {exact:true}).count()) === 1);
    await screenshot(page,"applications");
    await manualCard.getByRole("button",{name:"编辑申请"}).click();
    check("材料清单：表单写明勾选是自查，不是审核", (await applicationForm.getByText(/勾选是你自己的核对，不是审核/).count()) === 1);
    check("材料清单：再打开表单时勾选还在", (await applicationForm.getByRole("checkbox", {name:"推荐信",exact:true}).isChecked()) && !(await applicationForm.getByRole("checkbox", {name:"个人陈述",exact:true}).isChecked()));
    await applicationForm.getByRole("checkbox", {name:"个人陈述",exact:true}).check();
    await applicationForm.getByLabel("申请轮次",{exact:true}).fill("第二轮");
    await applicationForm.getByRole("button",{name:"保存申请",exact:true}).click();
    await page.locator(".application-dialog").waitFor({state:"hidden"});
    await page.reload();
    await manualCard.getByText(/待自行核对/).waitFor();
    check("我的申请：修改轮次后要求重新核对", await manualCard.getByText(/待自行核对/).count()>0);
    check("材料清单：两项都勾上后显示都勾了", (await manualCard.getByText("材料 2/2，都勾了", {exact:true}).count()) === 1);
    // A catalogue program whose page has not been read for materials says so, and offers the own list.
    // Which program that is comes from the records, not from the order of the cards: once materials
    // are extracted for some programs, the first catalogue card may be one that has them.
    const unread = await page.evaluate(async () => (await (await fetch("/api/application-records")).json()).find((r) => r.programId && !r.materialsExtracted));
    check("材料清单：这个账号有一个还没提取材料的学校库项目可走查", Boolean(unread));
    if (unread) {
      const catalogCard = page.locator(".application-card").filter({ has: page.locator(`a[href="/programs/${encodeURIComponent(unread.programId)}"]`) });
      check("材料清单：学校库项目没提取材料时写明还没提取", (await catalogCard.getByText("材料要求还没提取", {exact:true}).count()) === 1);
      await catalogCard.getByRole("button",{name:"编辑申请"}).click();
      check("材料清单：没提取的项目在表单里说明，并可以列自己的清单", (await applicationForm.getByText(/材料要求还没提取/).count()) === 1 && (await applicationForm.getByLabel("加一项自己的材料").count()) === 1);
      await applicationForm.getByRole("button",{name:"取消",exact:true}).click();
      await page.locator(".application-dialog").waitFor({state:"hidden"});
    }

    // Sync conflict (PRD-multi-device 3.3): another device edits the record while this form is open.
    const demoRecord = () => page.evaluate(async () => (await (await fetch("/api/application-records")).json()).find((r) => r.school === "示例大学（演示账号）"));
    conflictSteps.running = true;
    await manualCard.getByRole("button",{name:"编辑申请"}).click();
    const elsewhere = await page.evaluate(async (record) => (await fetch(`/api/application-records/${encodeURIComponent(record.id)}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ materialNotes: "另一台设备写的备注", baseVersion: record.version }),
    })).status, await demoRecord());
    check("同步冲突：另一台设备的修改已保存", elsewhere === 200, elsewhere);
    await applicationForm.getByLabel("申请轮次",{exact:true}).fill("第三轮");
    await applicationForm.getByRole("button",{name:"保存申请",exact:true}).click();
    await applicationForm.getByText("已在其他设备上修改").waitFor({ timeout: 15000 });
    check("同步冲突：过期的保存被拒绝，并显示服务器上的内容", (await applicationForm.getByText(/服务器上的内容：.*备注：另一台设备写的备注/).count()) === 1);
    const refused = await demoRecord();
    check("同步冲突：被拒绝的保存没有写入", refused.round === "第二轮" && refused.materialNotes === "另一台设备写的备注", refused);
    await applicationForm.getByRole("button",{name:"保留我的修改",exact:true}).click();
    await page.locator(".application-dialog").waitFor({state:"hidden"});
    const kept = await demoRecord();
    check("同步冲突：保留我的修改只写入改过的轮次，另一台设备写的备注还在", kept.round === "第三轮" && kept.materialNotes === "另一台设备写的备注", kept);
    await manualCard.getByText(/第三轮/).waitFor();
    // The same, taking the server's side: the stale edit is dropped and the list shows the server's record.
    await manualCard.getByRole("button",{name:"编辑申请"}).click();
    await page.evaluate(async (record) => fetch(`/api/application-records/${encodeURIComponent(record.id)}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ round: "第四轮", baseVersion: record.version }),
    }), await demoRecord());
    await applicationForm.getByLabel("申请轮次",{exact:true}).fill("我的第五轮");
    await applicationForm.getByRole("button",{name:"保存申请",exact:true}).click();
    await applicationForm.getByRole("button",{name:"使用服务器上的内容",exact:true}).click();
    await page.locator(".application-dialog").waitFor({state:"hidden"});
    await manualCard.getByText(/第四轮/).waitFor();
    check("同步冲突：使用服务器上的内容后保留另一台设备的轮次", (await demoRecord()).round === "第四轮");
    conflictSteps.running = false;

    // ---------- overview: the applicant's applications as lines on one time axis ----------
    await page.goto(`${BASE}/`);
    await page.locator(".lt-row").first().waitFor({ timeout: 15000 });
    await settle(page);
    const served = await page.evaluate(async () => (await fetch("/api/application-records")).json());
    const drawnRecords = served.filter((r) => ["considering", "applying", "submitted"].includes(r.status));
    check("总览：每个在准备或已提交的申请是一行", (await page.locator(".lt-row").count()) === drawnRecords.length, { rows: await page.locator(".lt-row").count(), drawn: drawnRecords.length });
    check("总览：侧栏列出同样的申请", (await page.locator(".rail-legend li").count()) === drawnRecords.length);
    const demoRow = page.locator(".lt-row", { hasText: "示例大学（演示账号）" });
    // The label reads "… 截止" while the date is ahead and "… 的截止日期已过" after it; either names the date.
    check("总览：有日期的申请按它的截止日期画，并写出轮次", (await demoRow.locator('.c-track[aria-label^="2027-01-15 "]').count()) === 1 && (await demoRow.locator(".round").innerText()) === "第四轮");
    check("总览：没核对过的日期标「待核对」", (await demoRow.locator(".c-due .unchecked").count()) === 1);
    check("总览：线路代号取自校名，不是编出来的缩写", (await demoRow.locator(".bullet").innerText()) === "示例");
    const unknownRows = drawnRecords.filter((r) => !r.deadline && r.status !== "submitted").length;
    check("总览：没有日期的申请画成虚线并写「待确认」", (await page.locator(".c-track.is-unknown").count()) === unknownRows, { unknownRows });
    check("总览：时间轴标出今天和两周内", await page.locator(".lt .a-today").isVisible() && await page.locator(".lt-under .zone", { hasText: "两周内" }).isVisible());
    const colours = await page.locator(".lt-row").evaluateAll((rows) => rows.map((row) => [...row.classList].find((name) => name.startsWith("line-"))));
    check("总览：八个以内的申请各用一种线路颜色", new Set(colours).size === Math.min(colours.length, 8), colours);
    await page.reload();
    await page.locator(".lt-row").first().waitFor({ timeout: 15000 });
    const coloursAgain = await page.locator(".lt-row").evaluateAll((rows) => rows.map((row) => [...row.classList].find((name) => name.startsWith("line-"))));
    check("总览：线路颜色刷新后不变", JSON.stringify(colours) === JSON.stringify(coloursAgain), { colours, coloursAgain });
    await page.locator(".rail-legend button", { hasText: "示例大学" }).click();
    check("总览：在侧栏选中一个申请，其余的线退后", (await page.locator(".lt.has-sel .lt-row.is-sel").count()) === 1 && (await demoRow.getAttribute("class")).includes("is-sel"));
    await page.locator(".rail-legend button", { hasText: "示例大学" }).click();
    check("总览：再点一次取消选中", (await page.locator(".lt.has-sel").count()) === 0);
    await layout(page, "总览");
    await screenshot(page, "overview");
    await demoRow.getByRole("link", { name: "示例大学（演示账号）" }).click();
    await page.waitForURL(/applications\?edit=/);
    await applicationForm.getByLabel("申请轮次", { exact: true }).waitFor();
    check("总览：点校名打开这条申请的表单", (await applicationForm.getByLabel("申请轮次", { exact: true }).inputValue()) === "第四轮");
    await page.goto(`${BASE}/advisor?q=${encodeURIComponent("帮我整理申请材料")}`);
    await page.locator("#advisor-input").waitFor();
    await page.waitForFunction(() => document.querySelector("#advisor-input")?.value !== "");
    check("顾问：问题从链接带入且不自动发送", await page.locator("#advisor-input").inputValue() === "帮我整理申请材料" && (await page.locator(".msg-user", { hasText: "帮我整理申请材料" }).count()) === 0);

    // ---------- 顾问停靠栏 ----------
    // The dock is driven with scripted streams in the shape `api/app/routers/advisor.py` sends (the
    // event sequences are the ones `api/tests/test_advisor_steps.py` asserts); no model is called.
    await page.unroute("**/api/advisor/**");
    const advisorCalls = [];
    const stream = (route, events) => route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: [...events, { type: "done" }].map((event) => `data: ${JSON.stringify(event)}\n\n`).join(""),
    });
    const intentStep = (result) => [
      { type: "step", id: "t-intent", status: "running", kind: "intent", name: "classify_intent", title: "判断问题类型" },
      { type: "step", id: "t-intent", status: "done", ms: 420, result },
    ];
    const SOURCE = "https://example.edu/walkthrough-source";
    // One of this account's own applications, for a card that changes it.
    const ownRecord = (await page.evaluate(() => fetch("/api/application-records").then((r) => r.json())))[0];
    await page.route("**/api/advisor/**", (route) => {
      const pathname = new URL(route.request().url()).pathname;
      const body = JSON.parse(route.request().postData() || "{}");
      advisorCalls.push({ pathname, body });
      if (pathname.endsWith("/stop")) return route.fulfill({ status: 200, contentType: "application/json", body: '{"stopping":true}' });
      if (pathname.endsWith("/confirm") && body.interruptId === "int-2") {
        // The record changed on another device while the card waited: the write is refused.
        return stream(route, [
          { type: "step", id: "call-3:write", status: "running", kind: "tool", name: "propose_application_status", title: "写入", write: true },
          { type: "step", id: "call-3", status: "done", result: "你已确认" },
          { type: "step", id: "call-3:write", status: "failed", ms: 20, result: "没有执行：别处改过了（轮次：未填 → 第三批），这次没有写入，也没有覆盖别处的改动。" },
          { type: "token", text: "这次没有写入：这条申请刚在别处改过轮次。" },
        ]);
      }
      if (pathname.endsWith("/confirm")) {
        return stream(route, [
          { type: "step", id: "call-1:write", status: "running", kind: "tool", name: "propose_portfolio_change", title: "写入", write: true },
          { type: "step", id: "call-1", status: "done", result: "你已确认" },
          { type: "step", id: "call-1:write", status: "done", ms: 180, result: "已保存", write: true },
          { type: "token", text: "已经写入。" },
        ]);
      }
      const message = body.message || "";
      // Never answered: the turn stays running until the walkthrough stops it.
      if (message.includes("慢")) return;
      if (message.includes("加入")) {
        return stream(route, [
          ...intentStep("归为「修改申请」，交给顾问处理"),
          { type: "step", id: "call-1", status: "running", kind: "tool", name: "propose_portfolio_change", title: "提议改组合", args: [{ label: "项目", value: "走查大学 走查项目" }, { label: "操作", value: "加入组合" }] },
          { type: "step", id: "call-1", status: "waiting", ms: 12, result: "等你确认" },
          { type: "confirm", id: "int-1", stepId: "call-1", kind: "confirm_portfolio", summary: "把「走查大学 走查项目」加入选校组合，档位：稳",
            target: { programId: "walkthrough-none", school: "走查大学", program: "走查项目" },
            changes: [{ label: "选校组合", before: "不在组合里", after: "加入" }, { label: "档位", before: null, after: "稳" }] },
        ]);
      }
      if (message.includes("标成已提交")) {
        return stream(route, [
          ...intentStep("归为「修改申请」，交给顾问处理"),
          { type: "step", id: "call-2", status: "running", kind: "tool", name: "get_my_applications", title: "读取申请" },
          { type: "step", id: "call-2", status: "done", ms: 30, result: "读到 1 个申请" },
          { type: "step", id: "call-3", status: "running", kind: "tool", name: "propose_application_status", title: "提议改状态", args: [{ label: "申请", value: `${ownRecord.school} ${ownRecord.name}` }, { label: "状态", value: "已提交" }] },
          { type: "step", id: "call-3", status: "waiting", ms: 12, result: "等你确认" },
          { type: "confirm", id: "int-2", stepId: "call-3", kind: "confirm_application", tool: "propose_application_status", summary: "把这条申请的申请状态改为已提交",
            target: { applicationId: ownRecord.id, programId: ownRecord.programId, school: ownRecord.school, program: ownRecord.name },
            changes: [{ label: "申请状态", before: "准备中", after: "已提交" }] },
        ]);
      }
      if (message.includes("填一个")) {
        return stream(route, [
          ...intentStep("归为「修改申请」，交给顾问处理"),
          { type: "step", id: "call-4", status: "running", kind: "tool", name: "propose_application_deadline", title: "提议改日期", args: [{ label: "申请", value: `${ownRecord.school} ${ownRecord.name}` }, { label: "日期", value: "2099-01-15" }] },
          { type: "step", id: "call-4", status: "failed", ms: 9, result: "没有执行：对话里没有写出 2099-01-15 这个日期，顾问不能自己定日期。" },
          { type: "token", text: "学校库里没有这条申请的截止日期，我不能自己定一个。请在官网查到后把日期写给我。" },
        ]);
      }
      if (message.includes("麻省")) {
        return stream(route, [
          ...intentStep("归为「官方要求」，先查学校库再回答"),
          { type: "step", id: "t-retrieval", status: "running", kind: "retrieval", name: "retrieve_requirements", title: "检索学校库" },
          { type: "step", id: "t-retrieval", status: "empty", ms: 90, result: "没有可引用的官方来源" },
          { type: "citations", gate: "refuse", citations: [] },
          { type: "token", text: "这所学校还没有收录这个方向的项目，我不能凭印象回答。" },
        ]);
      }
      if (message.includes("坏了")) {
        return stream(route, [...intentStep("归为「一般问题」，交给顾问处理"), { type: "error", code: "model_unavailable", message: "顾问暂时不可用，请稍后再试。" }]);
      }
      return stream(route, [
        ...intentStep("归为「官方要求」，先查学校库再回答"),
        { type: "step", id: "t-retrieval", status: "running", kind: "retrieval", name: "retrieve_requirements", title: "检索学校库" },
        { type: "step", id: "t-retrieval", status: "done", ms: 310, result: "找到 1 个有官方来源的项目", items: ["走查大学 走查项目"] },
        { type: "citations", gate: "pass", citations: [{
          n: 1, programId: "walkthrough-none", program: "走查大学 走查项目", title: "Walkthrough source page", url: SOURCE, status: "待核验",
          fields: [{ label: "语言", value: "走查用的占位值" }, { label: "申请截止", value: "Round 1 2099-01-15", quote: "Walkthrough placeholder sentence, not an official page." }],
        }] },
        { type: "token", text: "走查用的占位回答，见来源 [1]。\n\n- 第一项\n- 第二项" },
      ]);
    });
    const dock = page.locator("#advisor-dock");
    const input = page.locator("#advisor-input");
    const lastTurn = page.locator(".turn").last();
    const ended = () => page.waitForFunction(() => {
      const turn = [...document.querySelectorAll(".turn")].at(-1);
      return turn && turn.dataset.state !== "running";
    });
    await page.locator('.rail-nav a[href="/"]').click();
    await page.locator(".lt-row").first().waitFor();
    check("停靠栏：1440 宽时默认在工作区右侧", await dock.isVisible() && (await dock.boundingBox()).x >= 1000);
    check("停靠栏：从顾问页换到总览，没发的问题还在输入框里", (await input.inputValue()) === "帮我整理申请材料");
    check("停靠栏：侧栏入口是开关，标明已展开", (await page.locator("#advisor-toggle").getAttribute("aria-expanded")) === "true");
    check("停靠栏：这个账号之前在顾问页的对话也在这里", (await page.locator(".turn .msg-user").first().innerText()) === question);
    await page.getByRole("button", { name: "新对话" }).click();
    const mine = await page.evaluate(async () => (await fetch("/api/application-records")).json());
    const starters = await page.locator(".asks button").allInnerTexts();
    check("停靠栏：开场问题用的是这个账号自己的申请", starters.length >= 2 && starters.some((text) => mine.some((r) => text.includes(`${r.school} ${r.name}`))), starters);
    const workspaceRight = () => page.evaluate(() => parseFloat(getComputedStyle(document.querySelector(".workspace-content")).marginRight));
    check("停靠栏：打开时工作区让出位置", (await workspaceRight()) >= 380, await workspaceRight());
    await page.keyboard.press("Control+j");
    await dock.waitFor({ state: "hidden" });
    check("停靠栏：Ctrl J 收起，工作区收回位置", (await workspaceRight()) === 0 && (await page.locator("#advisor-toggle").getAttribute("aria-expanded")) === "false");
    await page.reload();
    await page.locator(".lt-row").first().waitFor();
    check("停靠栏：收起的状态刷新后还在", await dock.isHidden());
    await page.getByRole("link", { name: "让顾问去查" }).first().click();
    await dock.waitFor();
    const asked = await input.inputValue();
    const undated = mine.filter((r) => !r.deadline && ["considering", "applying"].includes(r.status)).map((r) => `${r.school} ${r.name} 的申请截止日期是哪天？`);
    check("总览：让顾问去查在停靠栏里填好问题，不自动发送，也不换页", undated.includes(asked) && (await page.locator(".turn").count()) === 0 && new URL(page.url()).pathname === "/", { asked, url: page.url() });
    check("停靠栏：打开后焦点在输入框", await input.evaluate((element) => element === document.activeElement));

    await input.press("Enter");
    await ended();
    const sent = advisorCalls.at(-1);
    check("停靠栏：Enter 发出填好的问题", sent.pathname === "/api/advisor/chat" && sent.body.message === asked, sent);
    check("顾问：一轮画成一条线，每一步一个站，做完的是实心", (await lastTurn.locator(".run .step.is-done").count()) === 2 && (await lastTurn.locator(".step .label").allInnerTexts()).join("|") === "判断问题类型|检索学校库");
    check("顾问：每一步有一行结果和用时", (await lastTurn.locator(".step .out").nth(1).innerText()) === "找到 1 个有官方来源的项目" && (await lastTurn.locator(".step .time").first().innerText()) === "0.4s");
    const detail = lastTurn.locator(".step").nth(1).locator(".detail");
    check("顾问：步骤默认收起", await detail.isHidden());
    await lastTurn.locator("button.call").click();
    check("顾问：点开一步能看到它找到的项目", (await detail.innerText()).includes("走查大学 走查项目"));
    const card = lastTurn.locator(".cite");
    const link = card.locator("a.cite-link");
    check("顾问：来源卡片有项目、字段、原文和官方链接", (await card.locator(".cite-program").innerText()) === "走查大学 走查项目" && (await card.locator(".cite-record dt").allInnerTexts()).join("|") === "语言|申请截止" && (await card.locator(".cite-quote").innerText()).includes("Walkthrough placeholder sentence") && (await link.getAttribute("href")) === SOURCE && (await link.getAttribute("target")) === "_blank");
    check("顾问：没核对过的来源不标「已核对」", (await card.getByText("已核对").count()) === 0);
    await lastTurn.locator(".cite-ref").click();
    check("顾问：回答里的编号跳到对应的来源卡片", await card.evaluate((element) => element === document.activeElement));
    check("顾问：回答里的列表按列表显示", (await lastTurn.locator(".answer li").count()) === 2);
    await screenshot(page, "advisor-dock");
    await page.locator('.rail-nav a[href="/applications"]').click();
    await page.waitForURL(/\/applications$/);
    check("停靠栏：换页面后对话还在", (await page.locator(".turn").count()) === 1 && await dock.isVisible());
    await page.waitForTimeout(600);
    await page.reload();
    await page.locator(".turn").first().waitFor({ timeout: 15000 });
    check("停靠栏：刷新后对话还在", (await lastTurn.locator(".msg-user").innerText()) === asked && (await lastTurn.locator(".step.is-done").count()) === 2);

    await input.fill("把走查项目加入选校");
    await input.press("Enter");
    await ended();
    const proposal = lastTurn.locator(".confirm");
    check("顾问：要写入的改动先列出旧值和新值，等确认", (await proposal.locator(".confirm-head").innerText()) === "写入前请你确认" && (await proposal.locator(".changes del").first().innerText()) === "不在组合里" && (await proposal.locator(".changes ins").allInnerTexts()).join("|") === "加入|稳" && (await lastTurn.getAttribute("data-state")) === "waiting");
    check("顾问：等确认的那一步是空心站", (await lastTurn.locator(".step.is-waiting .out").innerText()) === "等你确认");
    await screenshot(page, "advisor-confirm");
    await proposal.getByRole("button", { name: "确认写入" }).click();
    await ended();
    const confirmed = advisorCalls.at(-1);
    check("顾问：确认发到 /api/advisor/confirm，带上这个改动的 id", confirmed.pathname === "/api/advisor/confirm" && confirmed.body.approved === true && confirmed.body.interruptId === "int-1" && confirmed.body.conversationId === sent.body.conversationId, confirmed);
    check("顾问：确认后卡片留在对话里，写入是单独一步", (await proposal.locator(".confirm-head").innerText()) === "你已确认" && (await proposal.getByRole("button").count()) === 0 && (await lastTurn.locator(".step").last().locator(".label").innerText()) === "写入" && (await lastTurn.locator(".step").last().locator(".out").innerText()) === "已保存");

    await input.fill("麻省理工的雅思要求");
    await input.press("Enter");
    await ended();
    check("顾问：查不到来源时显示为拒答，不像一条回答", (await lastTurn.locator(".answer.is-refusal .refusal-label").innerText()).startsWith("没有回答") && (await lastTurn.locator(".step.is-empty").count()) === 1 && (await lastTurn.locator(".cite").count()) === 0);

    await input.fill("写慢一点");
    await input.press("Enter");
    await page.locator('.turn[data-state="running"]').waitFor();
    check("顾问：运行时发送键变成停止", await page.getByRole("button", { name: "停止", exact: true }).isVisible());
    await page.keyboard.press("Escape");
    await page.locator('.turn[data-state="stopped"]').waitFor();
    const stopped = advisorCalls.at(-1);
    check("顾问：Esc 停止这一轮，并告诉服务器停下", (await lastTurn.locator(".run-note").innerText()).startsWith("已停止") && stopped.pathname === "/api/advisor/stop" && stopped.body.conversationId === sent.body.conversationId, stopped);
    check("顾问：停止后可以重试", await lastTurn.getByRole("button", { name: "重试" }).isVisible());

    await input.fill("模型坏了");
    await input.press("Enter");
    await ended();
    check("顾问：模型连不上时有自己的提示", (await lastTurn.locator(".problem").innerText()).includes("模型现在连不上") && (await lastTurn.getAttribute("data-state")) === "failed");
    await layout(page, "停靠栏打开的我的申请");

    await page.setViewportSize({ width: 1024, height: 768 });
    await page.waitForTimeout(400);
    check("1024：停靠栏打开时侧栏自动收成图标", (await page.locator(".shell.sidebar-collapsed").count()) === 1 && await dock.isVisible());
    await layout(page, "1024 停靠栏");
    await screenshot(page, "advisor-dock-1024");
    await page.getByRole("button", { name: "收起顾问" }).click();
    await dock.waitFor({ state: "hidden" });
    check("1024：收起停靠栏后侧栏回到原来的宽度", (await page.locator(".shell.sidebar-collapsed").count()) === 0 && await page.locator("#advisor-toggle").evaluate((element) => element === document.activeElement));
    await page.setViewportSize(DESKTOP);
    await page.locator("#advisor-toggle").click();
    await dock.waitFor();
    await page.getByRole("button", { name: "新对话" }).click();
    check("顾问：新对话清空对话，回到开场", (await page.locator(".turn").count()) === 0 && await page.locator(".hello").isVisible());
    await input.fill("新的一轮");
    await input.press("Enter");
    await ended();
    check("顾问：新对话用新的对话 id", advisorCalls.at(-1).body.conversationId !== sent.body.conversationId);

    // A change to one application (the tools of api/app/agent/application_tools.py), in the event
    // shapes api/tests/test_advisor_application_tools.py asserts.
    await input.fill("把这条申请标成已提交");
    await input.press("Enter");
    await ended();
    const statusCard = lastTurn.locator(".confirm");
    check("顾问：改一条申请的卡片带这条申请的线路代号，列出旧状态和新状态", (await statusCard.locator(".confirm-what .bullet").count()) === 1
      && (await statusCard.locator(".changes del").innerText()) === "准备中" && (await statusCard.locator(".changes ins").innerText()) === "已提交"
      && (await lastTurn.locator(".step.is-waiting .label").innerText()) === "提议改状态");
    await screenshot(page, "advisor-application-confirm");
    await statusCard.getByRole("button", { name: "确认写入" }).click();
    await ended();
    check("顾问：确认时记录已在别处改过，卡片写明没有写入，写入那一步说出改了什么", (await statusCard.locator(".confirm-head").innerText()) === "你已确认，但没有写入"
      && (await lastTurn.locator(".step.is-failed .out").innerText()).includes("别处改过了（轮次：未填 → 第三批）") && advisorCalls.at(-1).body.interruptId === "int-2");
    await input.fill("截止日期你帮我填一个");
    await input.press("Enter");
    await ended();
    check("顾问：没人说过的日期不出确认卡片，那一步写明原因", (await lastTurn.locator(".confirm").count()) === 0
      && (await lastTurn.locator(".step.is-failed .out").innerText()) === "没有执行：对话里没有写出 2099-01-15 这个日期，顾问不能自己定日期。");
    await page.getByRole("button", { name: "新对话" }).click();
    await page.unroute("**/api/advisor/**");

    // ---------- 我的: the rest of the profile ----------
    await page.goto(`${BASE}/me`);
    await settle(page);
    await page.getByRole("button", { name: "修改背景" }).click();
    await page.locator(".choice", { hasText: "本科" }).first().click();
    await page.locator("#me-major").fill("软件工程");
    await page.locator("#me-degree").selectOption("授课型硕士");
    await page.locator("#me-intake").selectOption("2027 S2");
    await layout(page, "我的：编辑背景");
    await screenshot(page, "me-edit");
    await page.getByRole("button", { name: "保存" }).click();
    await page.locator(".kv2").waitFor({ timeout: 15000 });
    const full = await page.evaluate(async () => (await fetch("/api/profile")).json());
    check("我的：入学时间等字段在“我的”里保存", full.intake === "2027 S2" && full.major === "软件工程" && full.schoolName === "北京邮电大学", full);

    // ---------- roadmap ----------
    await page.getByRole("link", { name: "路线图" }).first().click();
    await page.waitForURL("**/roadmap");
    await page.locator(".rm-wide .rm-step").first().waitFor({ timeout: 20000 });
    await page.locator(".rm-list .rm-tick").first().waitFor();
    await settle(page);
    check("路线图：写明各段时间是系统建议，不是官方日期", (await page.locator(".map-note", { hasText: "系统建议，不是官方日期" }).count()) === 1);
    check("路线图：画成一条线，没有旧的时间轴、进度条和卡片", (await page.locator(".rm-wide .rm-join").count()) > 0
      && (await page.locator("svg.timeline-svg, .task-progress, main.roadmap .panel").count()) === 0);
    // An application without a date is a dotted run and is listed as 待确认; no date is drawn for it.
    const undatedRecords = await page.evaluate(async () => (await (await fetch("/api/application-records")).json())
      .filter((r) => ["considering", "applying"].includes(r.status) && !r.deadline).length);
    check("路线图：没有日期的申请画成虚线，清单里写待确认", (await page.locator(".rm-wide .rm-lane.is-unknown").count()) === undatedRecords
      && (await page.locator('.rm-dates li[data-state="unknown"]').count()) === undatedRecords, undatedRecords);
    // Choosing a stretch on the map shows its stations in the list under it.
    const lastStep = page.locator(".rm-wide .rm-step").last();
    await lastStep.click();
    check("路线图：点一段，下面的清单换成这一段的步骤", (await lastStep.getAttribute("aria-pressed")) === "true"
      && (await lastStep.locator(".rm-lbl b").innerText()) === (await page.locator("#h-stretch").innerText()).replace(/\s*当前$/, "").trim());
    await page.locator('.rm-wide .rm-step', { has: page.locator(".rm-stn:not(.on)") }).first().click();
    const firstOpen = page.locator(".rm-list li:not(.is-done) .rm-tick").first();
    const taskId = await firstOpen.getAttribute("id");
    // A first visit writes the task rows; the box is enabled once its row is back.
    await page.locator(".rm-list li:not(.is-done) .rm-tick:not([disabled])").first().waitFor({ timeout: 15000 });
    const filledBefore = await page.locator(".rm-wide .rm-stn.on").count();
    // Listen before ticking: the save can answer before a listener registered afterwards exists.
    const taskSaved = page.waitForResponse((r) => r.url().includes("/api/roadmap/tasks/") && r.request().method() === "PATCH", { timeout: 15000 });
    await page.locator(`[id="${taskId}"]`).check();
    await taskSaved;
    check("路线图：勾一项，图上多一个实心站", (await page.locator(".rm-wide .rm-stn.on").count()) === filledBefore + 1);
    await page.reload();
    await page.locator(".rm-list .rm-tick").first().waitFor();
    await settle(page);
    // The phase may have moved on after the tick, so the box is found by id in whichever phase holds it.
    const stillTicked = await page.evaluate(async (key) => {
      const body = await (await fetch("/api/roadmap")).json();
      return body.tasks.some((t) => `t-${t.materialKey}` === key && t.status === "completed");
    }, taskId);
    check("路线图：勾选在刷新后仍保存着", stillTicked, taskId);
    const upload = page.locator(".rm-list input[type=file]").first();
    // The library sniffs the type from the bytes and takes PDFs and images, so the file is a minimal PDF.
    const pdf = Buffer.from(`%PDF-1.4\n% ${stamp}\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n`);
    await upload.setInputFiles({ name: "walkthrough-transcript.pdf", mimeType: "application/pdf", buffer: pdf });
    await page.getByText(/已上传 walkthrough-transcript\.pdf/).waitFor({ timeout: 15000 });
    check("路线图：任务行上传了文件", true);
    await layout(page, "路线图");
    await screenshot(page, "roadmap");

    // ---------- roadmap: official deadlines (openspec requirement-dates) ----------
    // Two programs from the imported catalogue: one with a deadline on or after today (Beijing date), and
    // one whose every deadline has passed. They join the portfolio through the API, the roadmap is read,
    // then the portfolio is put back as it was.
    const BJ_TODAY = "(now() at time zone 'Asia/Shanghai')::date";
    // The open program's next round falls before the intake, so it is drawn on the axis.
    // The intake anchor by `intakeAnchor` in web/lib/roadmap.ts: S1 is 15 February, S2 15 July.
    const intake = await page.evaluate(async () => (await (await fetch("/api/profile")).json()).intake);
    const term = /(20\d{2})\s*S([12])/i.exec(intake || "");
    const anchor = term ? `${term[1]}-${term[2] === "1" ? "02" : "07"}-15` : "";
    check("截止日期：入学时间已排出锚点", anchor !== "", intake);
    const openId = dbRun(`select program_id from program_deadlines group by program_id having min(deadline) < ${BJ_TODAY} and min(deadline) filter (where deadline >= ${BJ_TODAY}) <= date '${anchor}' order by program_id limit 1`);
    const closedId = dbRun(`select program_id from program_deadlines group by program_id having max(deadline) < ${BJ_TODAY} order by program_id limit 1`);
    check("截止日期：库里有待截止和已截止的项目可走查", /^[\w-]+$/.test(openId) && /^[\w-]+$/.test(closedId), { openId, closedId });
    const originalRows = await page.evaluate(async () => (await (await fetch("/api/applications")).json()).map((r) => ({
      programId: r.programId, tier: r.tier, status: r.status, isPrimary: r.isPrimary, needsReview: r.needsReview,
    })));
    // A replacement states the stored rows it was based on (sync conflicts, PRD-multi-device 3.3).
    const putRows = (rows) => page.evaluate(async (body) => {
      const base = (await (await fetch("/api/applications")).json()).map((r) => ({ id: r.id, version: r.version }));
      return (await fetch("/api/applications", {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ rows: body, base }),
      })).status;
    }, rows);
    const [openProgram, closedProgram] = await page.evaluate(async (ids) => {
      const body = await (await fetch(`/api/programs?ids=${ids.join(",")}`)).json();
      return ids.map((id) => body.find((p) => p.slug === id));
    }, [openId, closedId]);
    const todayIso = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
    const nextRound = openProgram.deadlines.filter((d) => d.date >= todayIso).sort((a, b) => a.date.localeCompare(b.date))[0];
    const lastRound = closedProgram.deadlines.slice().sort((a, b) => a.date.localeCompare(b.date)).pop();
    check("截止日期：加入两个项目", (await putRows([...originalRows, { programId: openId, tier: "稳" }, { programId: closedId, tier: "保" }])) === 200);
    await page.reload();
    await page.locator(".rm-wide .rm-step").first().waitFor({ timeout: 20000 });
    await page.locator(`.rm-dates li[data-state="closed"]`).first().waitFor({ timeout: 15000 });
    await settle(page);
    // The roadmap reads the same records as the overview: a catalogue program's record is `catalog:<program id>`.
    const openRow = page.locator(`.rm-dates li[data-record="catalog:${openId}"]`);
    const closedRow = page.locator(`.rm-dates li[data-record="catalog:${closedId}"]`);
    check("截止日期：有下一轮的项目显示下一轮日期，写明是学校库采集、待核对，并链接到来源", (await openRow.getAttribute("data-state")) === "upcoming"
      && (await openRow.locator(`time[datetime="${nextRound.date}"]`).count()) === 1
      && (await openRow.locator(`a[href="${nextRound.sourceUrl}"]`, { hasText: "来源" }).count()) === 1
      && (await openRow.getByText("学校库采集").count()) === 1 && (await openRow.getByText("待核对").count()) === 1, nextRound);
    check("截止日期：全部已过的项目标「已截止」", (await closedRow.getAttribute("data-state")) === "closed"
      && (await closedRow.getByText("已截止").count()) === 1 && (await closedRow.locator(`time[datetime="${lastRound.date}"]`).count()) === 1, lastRound);
    check("截止日期：已截止的不画在时间轴上", (await page.locator(`.rm-wide .rm-lane[data-record="catalog:${closedId}"]`).count()) === 0);
    const openLane = page.locator(`.rm-wide .rm-lane[data-record="catalog:${openId}"]`);
    check("截止日期：下一轮画成这个项目的线，停在截止那天", (await openLane.count()) === 1 && (await openLane.locator(".rm-term").count()) === 1
      && (await openLane.getAttribute("aria-label")).includes(`${nextRound.date} 截止`), nextRound);
    // The line's colour and code are the rail's for the same application.
    const railBullet = page.locator(".rail-legend button", { hasText: openProgram.university }).locator(".bullet").first();
    check("截止日期：线的颜色和代号与侧栏里同一个申请一致", (await openLane.locator(".bullet").innerText()) === (await railBullet.innerText())
      && (await openLane.locator(".bullet").evaluate((el) => getComputedStyle(el).backgroundColor)) === (await railBullet.evaluate((el) => getComputedStyle(el).backgroundColor)));
    await layout(page, "路线图：截止日期");
    // A date entered on the portfolio row wins over the collected ones, and stays as entered.
    const entered = { date: "2027-01-02", url: "https://example.edu/walkthrough-entered-deadline" };
    check("截止日期：组合行写入自己的日期", (await putRows([...originalRows,
      { programId: openId, tier: "稳", officialDeadline: entered.date, deadlineSourceUrl: entered.url },
      { programId: closedId, tier: "保" }])) === 200);
    await page.reload();
    await page.locator(`.rm-dates li[data-state]`).first().waitFor({ timeout: 20000 });
    await settle(page);
    check("截止日期：组合里记录的日期优先于采集的", (await openRow.locator(`time[datetime="${entered.date}"]`).count()) === 1
      && (await openRow.locator(`a[href="${entered.url}"]`, { hasText: "来源" }).count()) === 1
      && (await openRow.getByText("自己填的").count()) === 1);
    const storedEntered = await page.evaluate(async (id) => (await (await fetch("/api/applications")).json()).find((r) => r.programId === id), openId);
    check("截止日期：采集的截止日期仍在项目上，组合行的日期没被改", storedEntered.officialDeadline === entered.date
      && JSON.stringify(storedEntered.program.deadlines) === JSON.stringify(openProgram.deadlines), storedEntered);
    check("截止日期：组合恢复原样", (await putRows(originalRows)) === 200);
    await page.goto(`${BASE}/programs/${encodeURIComponent(closedId)}`);
    await settle(page);
    check("截止日期：项目页列出截止日期，已过的标「已截止」", (await page.locator(`.deadline-list li[data-state="closed"]`).count()) === closedProgram.deadlines.length);

    await page.goto(`${BASE}/me`);
    await page.getByText("walkthrough-transcript.pdf").first().waitFor({ timeout: 15000 });
    await settle(page);
    check("我的：材料库列出上传的文件", true);
    check("我的：显示登录邮箱", (await page.getByText(emails[0]).count()) > 0);
    await layout(page, "我的");
    await page.getByRole("button", { name: "我的，打开用户菜单" }).click();
    await page.locator("#user-menu").getByRole("link", { name: "材料", exact: true }).click();
    await page.waitForURL("**/materials");
    await page.getByRole("heading", { level: 1, name: "材料", exact: true }).waitFor();
    await page.getByText("walkthrough-transcript.pdf").first().waitFor({ timeout: 15000 });
    check("用户菜单：材料页保留上传的文件", (await page.getByText("transcript.pdf", { exact: false }).count()) > 0);
    check("材料页：不重复显示申请背景", await page.getByRole("heading", { name: "申请背景", exact: true }).count() === 0);
    // ---------- 材料, signed in: the map follows what the records say, and nothing else ----------
    await page.locator(".map svg").waitFor({ timeout: 15000 });
    await settle(page);
    await layout(page, "材料");
    const myRecords = await page.evaluate(async () => (await fetch("/api/application-records")).json());
    const preparing = myRecords.filter((r) => ["considering", "applying"].includes(r.status));
    // A program whose page was read and lists no documents is drawn like one that was not read.
    const readPrograms = preparing.filter((r) => r.programId && r.materialsExtracted && r.materials.length > 0);
    const silentPrograms = preparing.filter((r) => r.programId && r.materialsExtracted && r.materials.length === 0);
    const unreadPrograms = preparing.filter((r) => r.programId && !r.materialsExtracted);
    check("材料：侧栏的材料是当前页", (await page.locator('nav[aria-label="主导航"] a[aria-current="page"]').innerText()).trim() === "材料");
    check("材料：没提取和页面没列材料的项目各画一条虚线，列了材料的各画一条实线", (await page.locator(".map .ln.is-unread").count()) === unreadPrograms.length + silentPrograms.length
      && (await page.locator(".map .ln:not(.is-unread)").count()) === readPrograms.length, { unread: unreadPrograms.length, silent: silentPrograms.length, read: readPrograms.length });
    check("材料：页面没列材料的项目写明页面没列材料，不写成 0 项", (await page.locator(".own-row .st", { hasText: "页面没列材料" }).count()) === silentPrograms.length
      && (await page.locator(".own-row .st", { hasText: "官网要求 0 项" }).count()) === 0
      && (await page.locator(".keys li", { hasText: "页面没列材料" }).count()) === (silentPrograms.length ? 1 : 0), { silent: silentPrograms.length });
    // A station or a capsule is a collected requirement. With none collected, none may be drawn.
    const collected = readPrograms.reduce((sum, r) => sum + r.materials.length, 0);
    check("材料：图上的站不多于学校库采集到的要求，没采集就一站也不画", (await page.locator(".map .stn").count()) <= collected
      && (collected > 0 || (await page.locator(".map .stn, .map .hub").count()) === 0), { collected });
    check("材料：没提取的项目写明还没提取，图例和标题下的说明也跟着", (await page.locator(".own-row .st", { hasText: "还没提取" }).count()) === unreadPrograms.length
      && (await page.locator(".keys li", { hasText: "还没提取" }).count()) === (unreadPrograms.length ? 1 : 0)
      && (await page.locator(".finding").innerText()).includes("还没提取") === (unreadPrograms.length > 0), { unread: unreadPrograms.length });
    // The own checklist is tried on any application that is being prepared; which one does not matter.
    const ownTarget = unreadPrograms[0] || preparing.find((r) => r.programId);
    check("材料：这个账号有一个在准备的学校库申请可走查", Boolean(ownTarget), preparing.length);
    if (ownTarget) {
      const ownRow = page.locator(".own-row", { has: page.locator(`a[href="/programs/${encodeURIComponent(ownTarget.programId)}"]`) });
      const reveal = ownRow.getByRole("button", { name: "加一项自己的材料", exact: true });
      if (await reveal.count()) await reveal.click();
      await ownRow.getByLabel("加一项自己的材料").fill("成绩单（走查）");
      await ownRow.getByRole("button", { name: "添加", exact: true }).click();
      const line = ownRow.getByRole("checkbox", { name: "成绩单（走查）", exact: true });
      await line.waitFor({ timeout: 10000 });
      // A click, not `check()`: the box is saved behind the click, and its state is the server's to confirm.
      await line.click();
      await page.waitForFunction(async (id) => {
        const record = (await (await fetch("/api/application-records")).json()).find((r) => r.id === id);
        return record.customMaterials.some((item) => item.label === "成绩单（走查）" && item.done);
      }, ownTarget.id, { timeout: 10000 });
      check("材料：勾选之后焦点还在那个勾选框上", await line.evaluate((node) => document.activeElement === node));
      await page.reload();
      await page.locator(".map svg").waitFor({ timeout: 15000 });
      check("材料：自己的清单加一项、勾上，刷新后还在", await page.locator(".own-row").getByRole("checkbox", { name: "成绩单（走查）", exact: true }).isChecked());
    }
    const manualRecord = preparing.find((r) => !r.programId && r.school === "示例大学（演示账号）");
    check("材料：手动添加的申请还在准备中，可走查", Boolean(manualRecord), preparing.map((r) => r.school));
    if (manualRecord) {
      const manualRow = page.locator(".own-row", { hasText: "示例大学（演示账号）" });
      check("材料：手动添加的申请列在自己的清单里，勾选和「我的申请」里一致", (await manualRow.locator("input:checked").count()) === manualRecord.customMaterials.filter((line) => line.done).length
        && (await manualRow.locator('input[type="checkbox"]').count()) === manualRecord.customMaterials.length
        && (await manualRow.locator(".st", { hasText: "手动添加" }).count()) === 1, manualRecord.customMaterials);
    }
    await screenshot(page, "materials");
    await page.goto(`${BASE}/me`);
    await settle(page);
    await screenshot(page, "me");

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
    // The school page is where programs are browsed: search by name, filter by study area, page through.
    await page.goto(`${BASE}/schools/00026A`);
    await settle(page);
    await page.locator("#field").selectOption("计算机与数据");
    await page.getByRole("button", { name: "筛选" }).click();
    await page.waitForURL(/field=/);
    await settle(page);
    const areas = await page.locator("table.program-table tbody tr td:nth-child(2)").allInnerTexts();
    check("学校详情：按方向筛选后只剩这个方向的项目", areas.length > 0 && areas.every((a) => a === "计算机与数据"), areas.slice(0, 3));
    const next = page.locator(".pager a", { hasText: "下一页" });
    check("学校详情：翻页链接带着筛选条件", (await next.count()) === 0 || /field=/.test(await next.getAttribute("href")));
    await page.locator("#q").fill("Data");
    await page.getByRole("button", { name: "筛选" }).click();
    await page.waitForURL(/q=Data/);
    await settle(page);
    const names = await page.locator("table.program-table tbody tr a.l1").allInnerTexts();
    check("学校详情：按名称搜索", names.length > 0 && names.every((n) => /data/i.test(n)), names.slice(0, 3));
    // "Technology" is also in UTS's own name: the search must look at program names only.
    await page.goto(`${BASE}/schools/00099F`);
    await settle(page);
    const utsTotal = Number((await page.locator("#programs-h + span").innerText()).replace(/\D/g, ""));
    await page.goto(`${page.url().split("?")[0]}?q=${encodeURIComponent("  Technology ")}`);
    await settle(page);
    const techNames = await page.locator("table.program-table tbody tr a.l1").allInnerTexts();
    check("学校详情：搜索词同时是校名时只按项目名匹配（UTS 搜 Technology）", techNames.length > 0 && techNames.length < utsTotal && techNames.every((n) => /technology/i.test(n)), { utsTotal, shown: techNames.length });
    await page.goto(`${page.url().split("?")[0]}?q=${encodeURIComponent("   ")}&page=99.5`);
    await settle(page);
    check("学校详情：只有空格的搜索不算筛选，超出范围的页码显示最后一页", (await page.locator("table.program-table tbody tr a.l1").count()) > 0
      && (await page.getByText("没有符合条件的项目").count()) === 0 && /第 (\d+) \/ \1 页/.test(await page.locator(".pager").innerText()));
    await page.goto(`${BASE}/schools/imperial-college-london`);
    await settle(page);
    const heads = await page.locator("table.program-table thead th").allInnerTexts();
    check("学校详情：全校都未收录的列不显示（帝国理工没有学制和总学费）", heads.length > 0 && !heads.includes("学制") && !heads.includes("总学费"), heads);
    check("学校详情：没有“未核对”“自动标注”字样", (await page.getByText(/未核对|自动标注/).count()) === 0);
    await layout(page, "学校详情：帝国理工");

    await page.goto(`${BASE}/programs/0100139`);
    await settle(page);
    check("项目详情：没收录的要求合成一行“未收录”", (await page.locator(".req-table tr.req-missing").count()) === 1
      && /均分门槛.*英语/.test(await page.locator(".req-table tr.req-missing").innerText()));
    check("项目详情：来源是指向官方页面的链接", (await page.locator('.req-table a.link[target="_blank"]').count()) > 0);
    check("项目详情：面包屑是学校库 › 学校", (await page.locator('nav.crumb a[href="/schools"]').count()) === 1 && (await page.locator('nav.crumb a[href^="/schools/"]').count()) === 1);
    check("项目详情：保留官方来源链接", await page.locator('a[target="_blank"][href^="https://"]').count() > 0);
    await layout(page, "项目详情");
    await screenshot(page, "program");

    const list = await page.goto(`${BASE}/programs`);
    check("项目库列表页已删除（404）", list.status() === 404, list.status());
    await page.goto(`${BASE}/privacy`);
    await settle(page);
    check("隐私政策：移除草稿提示", (await page.getByText("等待 MortyYJT 审核").count()) === 0);
    check("隐私政策：集中展示来源声明", await page.getByRole("heading", { name: "数据来源与版权声明", exact: true }).count() === 1);
    check("隐私政策：联系邮箱可点击", await page.locator('a[href="mailto:1360242321y@gmail.com"]').count() === 1);
    check("隐私政策：不显示全局页脚", await page.locator(".site-foot").count() === 0);
    await layout(page, "隐私政策");
    await screenshot(page, "privacy");

    await page.evaluate(() => {
      localStorage.clear();
      sessionStorage.clear();
    });
    await page.goto(`${BASE}/`);
    await page.locator(".lt-row").first().waitFor();
    await page.locator(".task-row").first().waitFor({ timeout: 15000 });
    check("回访：总览读取真实申请状态", await page.locator(".task-row").count() > 0);
    await screenshot(page, "dashboard");
    const overviewTask = page.locator('.task-row input:not(:disabled)').first();
    const beforeTick = await overviewTask.isChecked();
    await overviewTask.setChecked(!beforeTick);
    await settle(page);
    await page.reload();
    await page.locator('.task-row input:not(:disabled)').first().waitFor();
    check("总览：任务完成状态刷新后保留", await page.locator('.task-row input').first().isChecked() === !beforeTick);
    await page.locator('.task-row input').first().setChecked(beforeTick);
    await settle(page);
    const gone = await page.goto(`${BASE}/prototype/schools`);
    check("旧的原型路由已移除", gone.status() === 404, gone.status());
    const admin = await page.request.get(`${BASE}/admin`);
    check("顾问后台不提供", admin.status() === 404, admin.status());
    session = (await context.cookies(BASE)).find((c) => c.name === "leapashore_session") ?? null;
    check("登录会话是 httpOnly cookie", session && session.httpOnly, session && { httpOnly: session.httpOnly });

    // ---------- logout ----------
    const other = await browser.newContext({ viewport: DESKTOP });
    if (session) await other.addCookies([{ name: "leapashore_session", value: session.value, url: BASE }]);
    const leaving = await other.newPage();
    watch(leaving, "logout", errors);
    await leaving.goto(`${BASE}/me`);
    // A model key stored in this browser goes with the session.
    await leaving.evaluate(() => localStorage.setItem("leapashore:model-key", JSON.stringify({ provider: "deepseek", key: "sk-walkthrough0000000000000000beef" })));
    await leaving.getByRole("button", { name: "退出登录" }).click();
    await leaving.waitForURL(`${BASE}/`);
    check("退出登录：浏览器里的模型密钥被删除", await leaving.evaluate(() => localStorage.getItem("leapashore:model-key")) === null);
    await leaving.getByRole("button", { name: "我的，打开用户菜单" }).click();
    await leaving.locator("#user-menu").getByRole("button", { name: "登录", exact: true }).waitFor();
    const afterLogout = await leaving.evaluate(async () => (await fetch("/api/profile")).status);
    check("退出登录：之后读档案返回 401", afterLogout === 401, afterLogout);
    await other.close();
    // The first context's cookie was the same session, now ended; the phone pass logs in again below.
    await context.close();

    // ---------- 加入选校 while logged out -> register -> skip -> 先补信息 -> delete ----------
    const second = await browser.newContext({ viewport: DESKTOP });
    const b = await second.newPage();
    watch(b, "second", errors);
    await b.goto(`${BASE}/programs/0100139`);
    await settle(b);
    await b.getByRole("button", { name: "加入选校组合" }).click();
    await b.locator("dialog.dialog:not(.workspace-search-dialog)").waitFor();
    await loginThroughDialog(b, emails[1]);
    await b.locator("dialog.dialog:not(.workspace-search-dialog)").getByRole("heading", { name: "补充四项信息" }).waitFor({ timeout: 15000 });
    await b.locator("dialog.dialog:not(.workspace-search-dialog)").getByRole("button", { name: "跳过，以后再填" }).click();
    await b.getByRole("group", { name: "选择档位" }).waitFor({ timeout: 15000 });
    check("加入选校：登录后回到项目页并接着选档位", true);
    await b.getByRole("group", { name: "选择档位" }).getByRole("button", { name: "稳" }).click();
    check("加入选校：选了档位后显示“已加入”", (await b.getByRole("button", { name: /已加入/ }).count()) === 1);
    // ---------- overview: a deadline within two weeks, and 标记为已提交 against another device's edit ----------
    const inTenDays = new Date(Date.now() + 8 * 3600e3 + 10 * 86400e3).toISOString().slice(0, 10);
    const near = await b.evaluate(async (deadline) => (await fetch("/api/application-records", {
      method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": `walkthrough-${Date.now()}` },
      body: JSON.stringify({ school: "走查大学", name: "MSc Walkthrough", deadline, sourceUrl: "https://example.edu/near", confirmDeadline: true, customMaterials: [{ id: "c-walkthrough", label: "简历", done: true }] }),
    })).json(), inTenDays);
    await b.goto(`${BASE}/`);
    const nearRow = b.locator(".lt-row", { hasText: "走查大学" });
    await nearRow.waitFor({ timeout: 15000 });
    await settle(b);
    const urgent = await b.evaluate(() => {
      const probe = document.body.appendChild(document.createElement("span"));
      probe.style.color = "var(--urgent)";
      const colour = getComputedStyle(probe).color;
      probe.remove();
      return colour;
    });
    const dueColour = await nearRow.locator(".c-due .n").evaluate((node) => getComputedStyle(node).color);
    check("总览：两周内的截止日期用红色数字", (await nearRow.locator(".c-due.is-soon .n").innerText()) === "10" && dueColour === urgent
      && (await b.locator(".rail-legend button", { hasText: "走查大学" }).locator(".left.is-soon").count()) === 1, { dueColour, urgent });
    check("总览：自查过的日期不标「待核对」，材料就绪的终点是实心", (await nearRow.locator(".c-due .unchecked").count()) === 0 && (await nearRow.locator(".c-track.is-complete").count()) === 1);
    const nearAction = b.locator(".next > li", { hasText: "走查大学" });
    check("接下来：材料就绪的申请提示还没提交", (await nearAction.locator("p").innerText()) === "还有 10 天，材料已就绪，还没提交。");
    await screenshot(b, "overview-soon");
    conflictSteps.running = true;
    const otherDevice = await b.evaluate(async (record) => (await fetch(`/api/application-records/${encodeURIComponent(record.id)}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: "applying", baseVersion: record.version }),
    })).status, near);
    check("总览同步冲突：另一台设备改了状态", otherDevice === 200, otherDevice);
    await nearAction.getByRole("button", { name: "标记为已提交" }).click();
    await nearAction.getByText("已在其他设备上改为「准备中」").waitFor({ timeout: 15000 });
    const refusedMark = await b.evaluate(async (id) => (await (await fetch("/api/application-records")).json()).find((r) => r.id === id).status, near.id);
    check("总览同步冲突：过期的标记被拒绝，没有写入", refusedMark === "applying", refusedMark);
    await nearAction.getByRole("button", { name: "保留我的修改", exact: true }).click();
    await nearRow.locator(".st.is-sent").waitFor({ timeout: 15000 });
    conflictSteps.running = false;
    const marked = await b.evaluate(async (id) => (await (await fetch("/api/application-records")).json()).find((r) => r.id === id).status, near.id);
    check("总览同步冲突：保留我的修改后标记为已提交，线路退役", marked === "submitted" && (await nearRow.locator(".c-track.is-sent").count()) === 1 && (await b.locator(".next > li", { hasText: "走查大学" }).count()) === 0, marked);
    check("总览：侧栏里这条申请显示已提交", (await b.locator(".rail-legend button", { hasText: "走查大学" }).locator(".left").innerText()) === "已提交");

    await b.goto(`${BASE}/roadmap`);
    await b.locator(".rm-undated").waitFor({ timeout: 15000 }).catch(() => {});
    check("路线图：没有入学时间时不画时间轴和日期，只按先后顺序排，并给出去填的按钮", (await b.locator('.rm-undated a[href="/me"]').count()) === 1
      && (await b.locator(".rm-axis, .rm-lane, .rm-under, .rm-lbl .when").count()) === 0 && (await b.locator(".rm-wide .rm-step").count()) > 0);
    await layout(b, "路线图：没有入学时间");
    await b.goto(`${BASE}/tiers`);
    await settle(b);
    check("跳过信息页的用户在分档页看到“先补信息”", (await b.getByRole("heading", { name: "先补信息" }).count()) === 1);
    await layout(b, "先补信息");
    await screenshot(b, "tiers-basics");
    // ---------- an applicant cannot reach the admin pages (openspec source-verification D6) ----------
    const applicantAdmin = await b.goto(`${BASE}/admin`);
    check("管理页：申请人打开是 404", applicantAdmin.status() === 404 && (await b.getByRole("heading", { name: "没有这个页面" }).count()) === 1, applicantAdmin.status());
    const applicantApi = await apiAs(second, "/api/admin/verification");
    check("管理接口：申请人 403", applicantApi.status === 403, applicantApi.status);
    await b.goto(`${BASE}/me`);
    await settle(b);
    await b.getByRole("button", { name: "注销账号" }).click();
    await b.locator("#del-email").fill(emails[1]);
    await b.getByRole("button", { name: "永久注销" }).click();
    await b.waitForURL(`${BASE}/`);
    const deleted = dbRun(`SELECT count(*) FROM accounts WHERE email = '${emails[1]}'`);
    check("注销账号：账号行已删除", deleted === "0", deleted);
    await second.close();

    // ---------- admin: /admin, read one page, confirm, withdraw ----------
    await adminPass(browser, emails[2], errors);

    // ---------- phone ----------
    const fresh = await browser.newContext({ viewport: PHONE });
    const intro = await fresh.newPage();
    watch(intro, "phone-intro", errors);
    await intro.goto(`${BASE}/`);
    await settle(intro);
    const loggedOutAdmin = await intro.goto(`${BASE}/admin`);
    check("管理页：未登录打开是 404", loggedOutAdmin.status() === 404, loggedOutAdmin.status());
    const loggedOutApi = await apiAs(fresh, "/api/admin/me");
    check("管理接口：未登录 401", loggedOutApi.status === 401, loggedOutApi.status);
    await intro.goto(`${BASE}/`);
    await settle(intro);
    await layout(intro, "首页 390");
    if (expectedDemo) check("390（未登录）：演示叠成三层，说明和登录入口在第一屏", (await intro.locator(".lt-row").count()) >= 2 && !(await intro.locator(".lt-head").isVisible())
      && await intro.locator(".demo-note").getByRole("button", { name: "登录", exact: true }).isVisible()
      && (await intro.locator(".demo-note").boundingBox()).y < 844);
    const bars = await intro.evaluate(() => {
      const top = document.querySelector("#workspace-nav").getBoundingClientRect();
      const tabs = document.querySelector('nav[aria-label="主导航"]').getBoundingClientRect();
      return { top: [top.top, top.height, top.width], tabs: [Math.round(tabs.bottom), tabs.width], height: window.innerHeight, width: window.innerWidth };
    });
    // Both bars span the page. With classic scrollbars that is the window less the scrollbar's gutter.
    check("390：顶栏在上，五个入口在底部标签栏", bars.top[0] === 0 && bars.top[1] === 48 && bars.top[2] === bars.tabs[1] && bars.top[2] > bars.width - 20 && bars.tabs[0] === bars.height
      && (await intro.locator('nav[aria-label="主导航"] a').evaluateAll((links) => links.filter((link) => getComputedStyle(link).display !== "none").length)) === 5, bars);
    const mobileSchools = intro.locator("#workspace-nav").getByRole("link", { name: "学校库" });
    check("390：标签栏的链接可见，当前页是总览", await mobileSchools.isVisible() && (await intro.locator('nav[aria-label="主导航"] a[aria-current="page"]').innerText()).trim() === "总览");
    await intro.getByRole("button", {name:"我的，打开用户菜单"}).click();
    await intro.locator("#user-menu").waitFor({ state: "visible" });
    const menuBox = await intro.locator("#user-menu").boundingBox();
    check("390：头像菜单在屏幕内", menuBox && menuBox.x >= 0 && menuBox.x + menuBox.width <= bars.width && menuBox.y >= 48, menuBox);
    await intro.keyboard.press("Escape");
    await intro.locator("#user-menu").waitFor({ state: "hidden" });
    check("390：Esc 关闭头像菜单", !await intro.locator("#user-menu").isVisible());
    await screenshot(intro, "home-390");
    await sidebarLogin(intro);
    await intro.locator("dialog.dialog:not(.workspace-search-dialog)").waitFor();
    await layout(intro, "登录弹窗 390");
    await screenshot(intro, "login-390");
    // Header login returns to the current workspace; respect the 60 s code resend window.
    await new Promise((r) => setTimeout(r, Math.max(0, 61000 - (Date.now() - firstCodeAt))));
    await loginThroughDialog(intro, emails[0]);
    // The demo's rows were on screen before the login; the account's own replace them.
    await intro.locator(".demo-note").waitFor({ state: "detached", timeout: 15000 });
    await intro.locator(".lt-row").first().waitFor({ timeout: 15000 });
    check("直接点登录：登录后显示真实总览，演示和它的标记都不在了", (await intro.locator(".pill-sample").count()) === 0 && (await intro.locator('.lt-row .school a[href^="/programs/"]').count()) === 0);
    check("390：总览的每一行叠成三层，不画表头", !(await intro.locator(".lt-head").isVisible()) && await intro.locator(".lt-row .c-track .org").first().isVisible());
    check("390：没有停靠栏，顾问是底部标签里的一页", await intro.locator("#advisor-dock").isHidden() && await intro.locator("#advisor-toggle").isHidden() && await intro.locator('.rail-nav a[href="/advisor"]').isVisible());
    for (const [route, name] of [
      ["/", "dashboard-390"],
      ["/applications", "applications-390"],
      ["/materials", "materials-390"],
      ["/tiers", "tiers-390"],
      ["/portfolio", "portfolio-390"],
      ["/roadmap", "roadmap-390"],
      ["/me", "me-390"],
      ["/advisor", "advisor-390"],
      ["/schools", "schools-390"],
      ["/schools/imperial-college-london", "school-390"],
      ["/programs/cricos-0100139", "program-390"],
      ["/privacy", "privacy-390"],
    ]) {
      await intro.goto(`${BASE}${route}`);
      await settle(intro);
      if (route === "/tiers") await intro.locator("#not-collected").waitFor({ timeout: 30000 }).catch(() => {});
      if (route === "/roadmap") {
        await intro.locator(".rm-tall .rm-tstep").first().waitFor({ timeout: 20000 }).catch(() => {});
        const box = await intro.locator(".rm-tall").boundingBox();
        check("390：路线图竖着画，整张图在屏幕宽度内", await intro.locator(".rm-wide").isHidden() && box && box.x >= 0 && box.x + box.width <= 390, box);
      }
      if (route === "/materials") {
        await intro.locator(".map svg").waitFor({ timeout: 20000 }).catch(() => {});
        const box = await intro.locator(".map").boundingBox();
        check("390：材料线路图竖着画，整张图在屏幕宽度内", (await intro.locator(".map.is-vertical").count()) === 1 && box && box.x >= 0 && box.x + box.width <= 390, box);
      }
      await layout(intro, `${route} 390`);
      await screenshot(intro, name);
    }
    await fresh.close();
  } catch (error) {
    check("走查顺利跑完", false, String(error && error.stack ? error.stack : error).split("\n").filter((line) => !line.includes("node_modules")).slice(0, 6).join(" | "));
  } finally {
    await browser.close();
    const quoted = emails.map((e) => `'${e}'`).join(",");
    // The confirmation history this run's admin wrote (its page was withdrawn in adminPass).
    dbRun(`DELETE FROM source_verifications WHERE account_id IN (SELECT id FROM accounts WHERE email IN (${quoted}))`);
    dbRun(`DELETE FROM clients WHERE id IN (SELECT client_id FROM accounts WHERE email IN (${quoted}))`);
    dbRun(`DELETE FROM login_codes WHERE email IN (${quoted})`);
    const left = dbRun(`SELECT count(*) FROM accounts WHERE email IN (${quoted})`);
    check(`走查结束时清理了本次创建的账号`, left === "0", left);
  }

  check("没有控制台错误或页面错误", errors.length === 0, errors.slice(0, 5));
  const failed = results.filter((r) => !r.ok);
  console.log(`\n${results.length - failed.length}/${results.length} 项通过，截图在 docs/screenshots/`);
  if (failed.length) process.exitCode = 1;
})();
