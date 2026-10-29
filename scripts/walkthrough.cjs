// Browser walkthrough in login mode (openspec account-login). A logged-out visitor types a question in the
// advisor and presses 发送 -> logs in with a mailed code -> fills the four basics -> the advisor sends the
// sentence that was typed. Then /tiers -> /portfolio (confirm) -> 我的 (edit intake) -> /roadmap (tick,
// upload) -> 我的 (materials) -> the library pages -> logout. A second visitor presses 加入选校组合 on a
// program, registers, skips the info step, sees 先补信息 on /tiers and deletes the account. Every page is
// then opened again at 390px. Each step writes docs/screenshots/NN-*.png.
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

/** Watch a page: console errors and page errors fail the run. */
function watch(page, label, errors, expected = EXPECTED) {
  page.on("console", (msg) => {
    if (msg.type() !== "error") return;
    const text = msg.text();
    if (expected.some((pattern) => pattern.test(text))) return;
    errors.push(`${label} console: ${text}`);
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
  const dialog = page.locator("dialog.dialog");
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
  const emails = [`walkthrough-${stamp}@example.test`, `walkthrough-${stamp}-b@example.test`];
  const errors = [];
  let firstCodeAt = Date.now();
  const browser = await chromium.launch();
  try {
    let session = null;
    // ---------- desktop: logged out ----------
    const context = await browser.newContext({ viewport: DESKTOP });
    const page = await context.newPage();
    watch(page, "desktop", errors);

    await page.goto(`${BASE}/`);
    await settle(page);
    await layout(page, "首页");
    check("首页：有“看看能申哪些”和“先看学校”", (await page.getByRole("link", { name: "看看能申哪些" }).count()) > 0 && (await page.getByRole("link", { name: "先看学校" }).count()) > 0);
    check("首页：示例时间线标了“示例”", (await page.locator("figure .pill-sample").count()) === 1);
    check("首页：未登录时顶栏有“登录”", await page.locator(".bar").getByRole("button", { name: "登录" }).isVisible());
    await screenshot(page, "home");

    await page.goto(`${BASE}/roadmap`);
    await settle(page);
    check("未登录：路线图只显示示例并请你登录", (await page.locator("figure .pill-sample").count()) === 1 && (await page.getByText("登录后查看你自己的路线图").count()) === 1);
    await layout(page, "路线图（未登录）");
    await page.goto(`${BASE}/me`);
    await settle(page);
    check("未登录：我的页请你登录", (await page.getByText("登录后查看你的背景和材料").count()) === 1);
    const anonymous = await page.evaluate(async () => (await fetch("/api/profile")).status);
    check("未登录：读档案返回 401", anonymous === 401, anonymous);
    const assess = await page.goto(`${BASE}/assess`);
    check("背景测评页已删除，跳到分档页", page.url().endsWith("/tiers") && assess.status() === 200, page.url());

    // ---------- 未登录点发送 -> 登录 -> 信息页 -> 回到顾问并发出原句 ----------
    await page.goto(`${BASE}/advisor`);
    await settle(page);
    check("顾问：页面里没有 emoji", !/[\u{1F300}-\u{1FAFF}]/u.test(await page.locator("main").innerText()));
    const question = "我是北邮软件工程，均分 85，雅思 6.5，能申哪些计算机硕士？";
    await page.locator("#msg").fill(question);
    await page.getByRole("button", { name: "发送" }).click();
    const dialog = page.locator("dialog.dialog");
    await dialog.waitFor();
    check("顾问：未登录点发送弹出登录", await dialog.getByRole("heading", { name: "登录" }).isVisible());
    check("顾问：登录时原句还在输入框里", (await page.locator("#msg").inputValue()) === question);
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
    check("顾问：对话里显示原句，输入框已清空", (await page.locator("#msg").inputValue()) === "");
    const chatResponse = await chat.response();
    check("顾问：发送请求带着登录会话（不是 401）", chatResponse && chatResponse.status() === 200, chatResponse && chatResponse.status());
    await settle(page);
    await layout(page, "顾问");
    await screenshot(page, "advisor");
    const basics = await page.evaluate(async () => (await fetch("/api/profile")).json());
    check("信息页：服务器档案就是填的四项", basics.schoolName === "北京邮电大学" && basics.domesticTier === "211" && Number(basics.gpaScore) === 85 && basics.targetField === "计算机与数据" && basics.englishScore === "IELTS 6.5", basics);
    check("登录后顶栏显示“我的”", await page.locator(".bar .me-link").isVisible());

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
    const putRows = (rows) => page.evaluate(async (body) => (await fetch("/api/applications", {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ rows: body }),
    })).status, rows);
    const [openProgram, closedProgram] = await page.evaluate(async (ids) => {
      const body = await (await fetch(`/api/programs?ids=${ids.join(",")}`)).json();
      return ids.map((id) => body.find((p) => p.slug === id));
    }, [openId, closedId]);
    const todayIso = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
    const nextRound = openProgram.deadlines.filter((d) => d.date >= todayIso).sort((a, b) => a.date.localeCompare(b.date))[0];
    const lastRound = closedProgram.deadlines.slice().sort((a, b) => a.date.localeCompare(b.date)).pop();
    check("截止日期：加入两个项目", (await putRows([...originalRows, { programId: openId, tier: "稳" }, { programId: closedId, tier: "保" }])) === 200);
    await page.reload();
    await page.locator("svg.timeline-svg").waitFor({ timeout: 20000 });
    await page.locator(`.deadline-row[data-state="closed"]`).first().waitFor({ timeout: 15000 });
    await settle(page);
    const openRow = page.locator(".deadline-row", { has: page.locator(`a[href="/programs/${encodeURIComponent(openId)}"]`) });
    const closedRow = page.locator(".deadline-row", { has: page.locator(`a[href="/programs/${encodeURIComponent(closedId)}"]`) });
    check("截止日期：有下一轮的项目显示下一轮日期并链接到来源", (await openRow.getAttribute("data-state")) === "upcoming"
      && (await openRow.locator(`a.num[href="${nextRound.sourceUrl}"]`, { hasText: nextRound.date }).count()) === 1, nextRound);
    check("截止日期：全部已过的项目标「已截止」", (await closedRow.getAttribute("data-state")) === "closed"
      && (await closedRow.getByText("已截止").count()) === 1 && (await closedRow.getByText(lastRound.date).count()) === 1, lastRound);
    const closedLabel = `${closedProgram.university} ${closedProgram.nameEn}`;
    check("截止日期：已截止的不画在时间轴上", (await page.locator(`a.deadline-mark[aria-label^="${closedLabel} "]`).count()) === 0);
    const openLabel = `${openProgram.university} ${openProgram.nameEn}`;
    check("截止日期：下一轮画在时间轴上（实心、带来源）", (await page.locator(`a.deadline-mark[aria-label="${openLabel} 官方截止 ${nextRound.date}"][href="${nextRound.sourceUrl}"]`).count()) === 1, { openLabel, nextRound });
    await layout(page, "路线图：截止日期");
    // A date entered on the portfolio row wins over the collected ones, and stays as entered.
    const entered = { date: "2027-01-02", url: "https://example.edu/walkthrough-entered-deadline" };
    check("截止日期：组合行写入自己的日期", (await putRows([...originalRows,
      { programId: openId, tier: "稳", officialDeadline: entered.date, deadlineSourceUrl: entered.url },
      { programId: closedId, tier: "保" }])) === 200);
    await page.reload();
    await page.locator(`.deadline-row[data-state]`).first().waitFor({ timeout: 20000 });
    await settle(page);
    check("截止日期：组合里记录的日期优先于采集的", (await openRow.locator(`a.num[href="${entered.url}"]`, { hasText: entered.date }).count()) === 1
      && (await openRow.getByText("组合里记录的日期").count()) === 1);
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

    await page.goto(`${BASE}/programs/0100139`);
    await settle(page);
    check("项目详情：没收录的要求写“未收录”", (await page.locator(".req-table").getByText("未收录").count()) >= 2);
    check("项目详情：引用 CRICOS 数据集", (await page.getByText("CRICOS（澳大利亚教育部").count()) > 0);
    await layout(page, "项目详情");
    await screenshot(page, "program");

    await page.goto(`${BASE}/programs`);
    await settle(page);
    await layout(page, "项目库");
    await page.goto(`${BASE}/privacy`);
    await settle(page);
    check("隐私政策：公开可读并标明是草稿", (await page.getByText("等待 MortyYJT 审核").count()) === 1);
    await layout(page, "隐私政策");
    await screenshot(page, "privacy");

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
    session = (await context.cookies(BASE)).find((c) => c.name === "leapashore_session") ?? null;
    check("登录会话是 httpOnly cookie", session && session.httpOnly, session && { httpOnly: session.httpOnly });

    // ---------- logout ----------
    const other = await browser.newContext({ viewport: DESKTOP });
    if (session) await other.addCookies([{ name: "leapashore_session", value: session.value, url: BASE }]);
    const leaving = await other.newPage();
    watch(leaving, "logout", errors);
    await leaving.goto(`${BASE}/me`);
    await leaving.getByRole("button", { name: "退出登录" }).click();
    await leaving.waitForURL(`${BASE}/`);
    await leaving.locator(".bar").getByRole("button", { name: "登录" }).waitFor();
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
    await b.locator("dialog.dialog").waitFor();
    await loginThroughDialog(b, emails[1]);
    await b.locator("dialog.dialog").getByRole("heading", { name: "补充四项信息" }).waitFor({ timeout: 15000 });
    await b.locator("dialog.dialog").getByRole("button", { name: "跳过，以后再填" }).click();
    await b.getByRole("group", { name: "选择档位" }).waitFor({ timeout: 15000 });
    check("加入选校：登录后回到项目页并接着选档位", true);
    await b.getByRole("group", { name: "选择档位" }).getByRole("button", { name: "稳" }).click();
    check("加入选校：选了档位后显示“已加入”", (await b.getByRole("button", { name: /已加入/ }).count()) === 1);
    await b.goto(`${BASE}/tiers`);
    await settle(b);
    check("跳过信息页的用户在分档页看到“先补信息”", (await b.getByRole("heading", { name: "先补信息" }).count()) === 1);
    await layout(b, "先补信息");
    await screenshot(b, "tiers-basics");
    await b.goto(`${BASE}/me`);
    await settle(b);
    await b.getByRole("button", { name: "注销账号" }).click();
    await b.locator("#del-email").fill(emails[1]);
    await b.getByRole("button", { name: "永久注销" }).click();
    await b.waitForURL(`${BASE}/`);
    const deleted = dbRun(`SELECT count(*) FROM accounts WHERE email = '${emails[1]}'`);
    check("注销账号：账号行已删除", deleted === "0", deleted);
    await second.close();

    // ---------- phone ----------
    const fresh = await browser.newContext({ viewport: PHONE });
    const intro = await fresh.newPage();
    watch(intro, "phone-intro", errors);
    await intro.goto(`${BASE}/`);
    await settle(intro);
    await layout(intro, "首页 390");
    check("390：导航收进菜单", !(await intro.locator("#main-nav").isVisible()) && (await intro.getByRole("button", { name: "菜单" }).isVisible()));
    check("390：未登录时“登录”按钮可见", await intro.locator(".bar").getByRole("button", { name: "登录" }).isVisible());
    await intro.getByRole("button", { name: "菜单" }).click();
    check("390：按菜单后出现五个链接", await intro.locator("#main-nav").getByRole("link", { name: "学校库" }).isVisible());
    await screenshot(intro, "home-390");
    await intro.locator(".bar").getByRole("button", { name: "登录" }).click();
    await intro.locator("dialog.dialog").waitFor();
    await layout(intro, "登录弹窗 390");
    await screenshot(intro, "login-390");
    // Logging in from the header lands on the tiers page; the code resend window is 60 s, so wait it out.
    await new Promise((r) => setTimeout(r, Math.max(0, 61000 - (Date.now() - firstCodeAt))));
    await loginThroughDialog(intro, emails[0]);
    await intro.waitForURL("**/tiers", { timeout: 15000 });
    check("直接点登录：登录后去分档页", true);
    for (const [route, name] of [
      ["/tiers", "tiers-390"],
      ["/portfolio", "portfolio-390"],
      ["/roadmap", "roadmap-390"],
      ["/me", "me-390"],
      ["/advisor", "advisor-390"],
      ["/schools", "schools-390"],
      ["/programs/cricos-0100139", "program-390"],
      ["/privacy", "privacy-390"],
    ]) {
      await intro.goto(`${BASE}${route}`);
      await settle(intro);
      if (route === "/tiers") await intro.locator("#not-collected").waitFor({ timeout: 30000 }).catch(() => {});
      if (route === "/roadmap") await intro.locator("svg.timeline-svg").waitFor({ timeout: 20000 }).catch(() => {});
      await layout(intro, `${route} 390`);
      await screenshot(intro, name);
    }
    await fresh.close();
  } catch (error) {
    check("走查顺利跑完", false, String(error && error.message ? error.message : error).split("\n")[0]);
  } finally {
    await browser.close();
    const quoted = emails.map((e) => `'${e}'`).join(",");
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
