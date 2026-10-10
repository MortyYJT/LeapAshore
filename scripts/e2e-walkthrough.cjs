// End-to-end walkthrough: drive a real browser through onboarding, portfolio selection, the main
// interface, and a reload, capturing a screenshot per step and reporting JS errors at the end.
//
// Usage: node scripts/e2e-walkthrough.cjs
// Requires the dev server on localhost:3000 (make dev); set BASE_URL to use another origin.
//
// Playwright comes from web/node_modules (see scripts/playwright.cjs); override with PLAYWRIGHT_PATH.

const path = require("path");
const fs = require("fs");
const os = require("os");
const { execFileSync } = require("child_process");

const { chromium } = require("./playwright.cjs");

const ROOT = path.resolve(__dirname, "..");
const OUT = path.join(ROOT, "docs/screenshots");
const BASE = process.env.BASE_URL || "http://localhost:3000";

// A program slug that is in no catalogue. It is written into the browser's own copy of the portfolio
// before the storage-clear reload below, so that a page still rendering from storage would put it on
// screen — which is the one thing that separates "the server owns the portfolio" from "the screen and
// the bundle happen to agree".
const SENTINEL_PROGRAM = "__walkthrough-not-a-program__";

// The backend's own virtualenv, its interpreter and the source of its database URL. Read from
// `api/app/config.py` rather than restated, so the walkthrough cannot clean up in one database while
// the API writes to another.
const API_DIR = path.join(ROOT, "api");
const API_PYTHON = path.join(API_DIR, ".venv/bin/python");
const API_APP = path.join(API_DIR, "app");

fs.mkdirSync(OUT, { recursive: true });

/**
 * Run one statement against the same database the API uses, and return what it answered.
 *
 * The walkthrough writes real portfolio rows through `PUT /api/applications`, and
 * `applications.program_id` is a `RESTRICT` foreign key. Any row left behind therefore blocks
 * `api/tests/test_seed.py`'s catalogue sweep — three of its tests delete every seeded program — so
 * `make verify` followed by `make test` used to go red on rows this script itself had written. The
 * cleanup at the end of the run is what closes that, and it needs a connection the browser cannot
 * give it.
 *
 * A query answers with the first column of its first row and a write with the number of rows it
 * touched. Those are two different questions and the first version of this printed `rowcount` for
 * both: `SELECT count(*)` returns exactly one row whatever the catalogue holds, so the "is it zero"
 * check below read `1` against a database that was already clean and could never have passed.
 *
 * The URL comes from the application's own settings, so a walkthrough pointed at a different database
 * cleans up that one. A failure is reported and returned, never thrown: cleanup runs last, and a
 * script that dies there would replace the run's verdict with its own.
 */
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
    return execFileSync(API_PYTHON, ["-c", script, sql], {
      cwd: API_APP,
      encoding: "utf8",
    }).trim();
  } catch (error) {
    return "失败：" + String(error.stderr || error.message).trim().split("\n").slice(-1)[0];
  }
}

(async () => {
  /**
   * The subject ids this run minted, captured from the traffic rather than read off one cookie.
   *
   * There is more than one, and the count is printed below so the number is measured rather than
   * assumed. Two sources, because they answer different halves:
   *
   * - the route sets `offerpilot_client` on **every** answer, and the frontend mounts up to four
   *   readers at once (`/api/profile`, `/api/roadmap`, `/api/programs`, `/api/applications`). Any of
   *   them can be the first request to arrive without a cookie, so a first page load mints several.
   *   Measured: three, from one `page.goto` on a cold context.
   * - the pre-flight read below is made by *this script*, not by the browser, so it is not in the
   *   browser's cookie jar and no page listener ever sees it — but it creates a `clients` row all the
   *   same. Measured: one orphan `clients` row per run, with nothing in the cleanup naming it.
   *
   * The cleanup used to read the cookie once, after the first page load, and delete that one subject;
   * every other id the run created kept its rows, and `applications.program_id` is the RESTRICT
   * foreign key that makes one leftover row block the catalogue seed's sweep.
   */
  const subjects = new Map();
  const rememberSubject = (value) => {
    if (typeof value === "string" && value.length > 0) subjects.set(value, true);
  };
  const rememberCookies = (response) => {
    for (const value of response.headers.getSetCookie()) {
      const match = /(?:^|;\s*)offerpilot_client=([^;]+)/.exec(value);
      if (match) rememberSubject(decodeURIComponent(match[1]));
    }
  };
  // The profile now lives on the server, so a walkthrough with no backend would drive a page whose
  // profile never loads and report success for the empty version of every assertion below. Fail
  // here instead, with the address that was tried.
  try {
    const response = await fetch(`${BASE}/api/profile`);
    if (!response.ok) throw new Error(`GET /api/profile responded ${response.status}`);
    await response.json();
    // Captured because this read is a subject the run created: `GET /api/profile` mints the cookie and
    // creates the `clients` and `profiles` rows on first contact, so leaving it unnamed would leave a
    // row per run for nobody to clean up.
    rememberCookies(response);
  } catch (error) {
    console.error(
      `后端不可达：GET ${BASE}/api/profile 失败（${error.message}）。` +
        "先运行 make dev（同时启动前端与 :8000 上的后端），再跑 make screenshots。",
    );
    process.exitCode = 1;
    return;
  }

  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  const errors = [];
  /**
   * Errors this run caused on purpose, listed separately from the ones it is checking for.
   *
   * The block near the end answers one write with a `500` to prove the page reports a failed save. The
   * browser logs that response as a console error, and it is the run's own doing rather than the
   * page's defect. Counting it would make the deliberate failure indistinguishable from an accidental
   * one, so it is labelled and excluded from the exit code — printed, because a run that injects errors
   * should still say so.
   */
  const injected = [];
  const record = (entry) => (injectingFailure ? injected : errors).push(entry);
  let injectingFailure = false;
  // `headersArray()` is async, and every line of this handler is inside a `catch`: a listener that
  // throws takes the whole run down from outside its own `try`, so a read that fails has to mean "no
  // id was captured from this answer" rather than an unhandled rejection. Measured: the sync version
  // of this line killed the process on the first response, before the first screenshot.
  page.on("response", async (response) => {
    try {
      for (const value of await response.headersArray()) {
        if (value.name.toLowerCase() !== "set-cookie") continue;
        const match = /(?:^|;\s*)offerpilot_client=([^;]+)/.exec(value.value);
        if (match) rememberSubject(decodeURIComponent(match[1]));
      }
    } catch {
      // A response whose headers cannot be read is one this capture does not get an id from. The
      // context's own jar is read again in the cleanup, so an id is not lost for good.
    }
  });
  page.on("console", (m) => m.type() === "error" && record("console: " + m.text()));
  page.on("pageerror", (e) => record("pageerror: " + e.message));

  /**
   * The roadmap write path's traffic, captured from the first request of the run.
   *
   * Registered before the first `goto` on purpose. A page that already has the rows writes nothing,
   * and one that has none writes as it mounts — so a capture installed later sees an empty list and
   * every assertion built on it would pass by measuring nothing. The two arrays are the evidence for
   * the checks near the end of the run.
   */
  const taskPuts = [];
  const taskPatches = [];
  await page.route(/\/api\/roadmap\/tasks/, async (route) => {
    const request = route.request();

    const body = JSON.parse(request.postData() || "null");
    if (request.method() === "PUT") {
      taskPuts.push({ url: request.url(), body });
    }
    else if (request.method() === "PATCH") taskPatches.push({ url: request.url(), body });
    await route.continue();
  });

  const shot = async (name) => {
    await page.screenshot({ path: path.join(OUT, `${name}.png`) });
    console.log("shot:", name);
  };
  /**
   * Choose an onboarding option by its leading label.
   *
   * The accessible name of an option includes its hint, and 高中's hint reads 申请本科. A substring
   * match on 本科 therefore selected 高中 and quietly produced a wrong demo profile.
   */
  const chooseOption = async (label) => {
    await page
      .locator("button.option")
      .filter({ hasText: new RegExp(`^\\s*${label}`) })
      .first()
      .click();
    await page.waitForTimeout(250);
  };
  const clickText = async (t) => {
    await page.getByRole("button", { name: t, exact: false }).first().click();
    await page.waitForTimeout(250);
  };
  /**
   * Assert, rather than print.
   *
   * The console.log lines below are evidence for a human reading the run; a `console.log` cannot gate
   * anything, so it is never the check itself. This one fails the run and names what disagreed. The
   * failure is deferred to the end (process.exitCode is read after the browser closes) so the rest of
   * the walkthrough still produces its screenshots and its error list.
   */
  const failures = [];
  const skipped = [];
  /**
   * `options.selector` marks a check whose subject may legitimately not exist in this run.
   *
   * A skipped check prints as such and is neither a pass nor a failure, so a run that could not
   * exercise a claim says so out loud instead of counting as evidence for it. It is not a way to make
   * a failing check pass: the check still has to be written so that it fails whenever its subject is
   * there and the behaviour is wrong.
   */
  const check = (name, ok, detail, options = {}) => {
    if (options.selector) {
      console.log(name + ": 跳过", detail === undefined ? "" : JSON.stringify(detail));
      skipped.push(name);
      return;
    }
    console.log(name + ":", ok ? "是" : "否", detail === undefined ? "" : JSON.stringify(detail));
    if (!ok) failures.push(name + (detail === undefined ? "" : " " + JSON.stringify(detail)));
  };

  // The target degree the onboarding answers with, and the one the roadmap block later changes the
  // profile to. The portfolio block puts the first one back, because the picker filters the catalogue
  // by the target degree and no seeded program is a research degree — measured: reopening the picker
  // on 研究型硕士 shows zero cards, so the catalogue check would have been measuring an empty screen.
  //
  // These are two separate values on purpose. Writing the restore as "put back whatever the run last
  // set" is the version that ran and did nothing: it restored 研究型硕士, which is what the profile
  // already said.
  const ONBOARDING_DEGREE = "授课型硕士";
  let demoDegree = ONBOARDING_DEGREE;

  // Everything from the first page load to the last screenshot runs inside this `try`, because the
  // cleanup below has to run whether or not an assertion threw. This batch added five Playwright waits
  // with a timeout, and a single one of them timing out used to skip the cleanup entirely: reproduced
  // by inserting a throw before the cleanup block, which left 6 rows behind and made the next `pytest`
  // report 4 failures. The cleanup is in the `finally` for that reason — a run's verdict must not
  // decide whether the shared database is left as it was found.
  try {
      await page.goto(BASE, { waitUntil: "networkidle" });
      await shot("01-step1-education");

      // The first subject this run is writing to, read off the cookie the API minted for this browser.
      // It is only the first: `subjects` accumulates every id the run was given, and the cleanup below
      // removes all of them, because any one of them can hold the portfolio rows that block the
      // catalogue seed's sweep.
      const clientCookie = (await context.cookies()).find((c) => c.name === "offerpilot_client");
      rememberSubject(clientCookie?.value);
      console.log("本次走查的主体:", clientCookie?.value ?? "未取得 cookie");

      await chooseOption("本科");
      await shot("02-step2-origin");

      await chooseOption("国内院校");
      await page.locator("input").first().fill("北京邮电");
      await page.waitForTimeout(400);
      await shot("03-step3-school-detected");
      await clickText("继续");

      await page.locator("input").first().fill("软件工程");
      await clickText("继续");

      await page.locator('input[type="number"]').first().fill("82");
      await page.waitForTimeout(300);
      await shot("04-step5-gpa");
      await clickText("继续");

      await chooseOption("授课型硕士");
      await clickText("继续");
      await chooseOption("计算机与数据");
      await shot("05-step7-field");
      await clickText("继续");

      await page.locator("input").first().fill("IELTS 6.5");
      await clickText("继续");
      await chooseOption("20–30 万");
      await clickText("继续");
      await chooseOption("2027 S1");
      await shot("06-step10-intake");

      await clickText("生成我的方案");
      await page.waitForTimeout(900);
      await shot("07-generating");

      await page.getByText("为你筛出的申请组合").waitFor({ timeout: 15000 });
      await page.waitForTimeout(400);
      await shot("08-portfolio");
      await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
      await page.waitForTimeout(300);
      await shot("09-portfolio-bottom");

      const cardsBeforeConfirm = await page.locator("article.card").count();
      console.log("确认组合时界面上的项目卡片数:", cardsBeforeConfirm);

      await clickText("确认组合");
      await page.getByText("申请流程").first().waitFor({ timeout: 15000 });
      await page.waitForTimeout(500);
      await shot("10-flow");

      await clickText("语言准备");
      await page.waitForTimeout(300);
      await shot("11-flow-language");

      // The tick is now a `PATCH` to the row's own id, and the row's id only exists once the page has read
      // the rows the recomputation created — so this waits for the write path to land before asserting the
      // control moved. `check()` rather than `click()`: it is the assertion that the tick stuck, and it
      // waits for the state change instead of trusting the click.
      await page.locator('input[type="checkbox"]').first().check({ timeout: 15000 });
      await page.waitForTimeout(300);
      await shot("12-material-checked");

      await clickText("首页");
      await page.waitForTimeout(300);
      await shot("13-home");

      await clickText("留学顾问");
      await page.waitForTimeout(400);
      await shot("14-advisor-empty");

      await page.getByPlaceholder("给留学顾问发消息…").fill("帮我看看现在的选校组合合不合理");
      await page.getByRole("button", { name: "发送" }).click();
      await page.waitForTimeout(900);
      await shot("15-advisor-message");

      // The account control is an avatar with a hover menu, not a tab.
      //
      // Move the pointer down through the space between the button and the menu instead of jumping
      // straight onto the menu item. A previous version positioned the menu with a top offset, which left
      // that strip belonging to neither element: crossing it fired mouseleave and the menu vanished
      // before the pointer arrived.
      const account = page.getByRole("button", { name: "账户" });
      const box = await account.boundingBox();
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.waitForTimeout(200);
      await page.mouse.move(box.x + box.width / 2, box.y + box.height + 4, { steps: 6 });
      await page.mouse.move(box.x + box.width / 2, box.y + box.height + 24, { steps: 6 });
      await page.waitForTimeout(250);

      const menuHeld = await page.getByRole("button", { name: "个人信息", exact: true }).isVisible().catch(() => false);
      console.log("指针移向菜单后仍然打开:", menuHeld ? "是" : "否");
      await shot("16-account-menu");

      await page.getByRole("button", { name: "个人信息", exact: true }).click();
      await page.getByText("每条都能单独改").waitFor({ timeout: 10000 });
      await page.waitForTimeout(300);
      // Avatar upload: the image is downscaled in the browser and stored locally, so the header control
      // should render an img once one is chosen.
      const png = Buffer.from(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
        "base64",
      );
      await page.locator('input[type="file"]').setInputFiles({
        name: "avatar.png",
        mimeType: "image/png",
        buffer: png,
      });
      await page.waitForTimeout(500);
      const avatarShown = (await page.locator('button[aria-label="账户"] img').count()) === 1;
      const avatarStored = await page.evaluate(() => {
        const raw = window.localStorage.getItem("offerpilot.state.v1");
        return Boolean(raw && JSON.parse(raw).avatar);
      });
      console.log("上传后头像已显示:", avatarShown ? "是" : "否");
      console.log("头像已存入本机:", avatarStored ? "是" : "否");

      // Guard against the option-selection bug above: the demo profile must say 本科, not 高中.
      const educationOk = await page
        .locator("div", { hasText: /^当前学历/ })
        .last()
        .innerText()
        .then((t) => /本科/.test(t) && !/高中/.test(t))
        .catch(() => false);
      console.log("当前学历识别为本科:", educationOk ? "是" : "否");

      await shot("17-profile");

      // Edit a single field in place instead of walking the onboarding again.
      await page.getByRole("button", { name: "编辑语言成绩" }).click();
      await page.waitForTimeout(200);
      await page.getByPlaceholder("例如：IELTS 6.5").fill("IELTS 7.0");
      await shot("18-profile-editing");
      await page.getByRole("button", { name: "保存" }).click();
      await page.waitForTimeout(300);
      const saved = await page.getByText("IELTS 7.0").isVisible().catch(() => false);
      console.log("单条编辑保存后生效:", saved ? "是" : "否");
      await shot("19-profile-saved");

      await page.getByRole("button", { name: "账户" }).hover();
      await page.waitForTimeout(250);
      await page.getByRole("button", { name: "设置", exact: true }).click();
      await page.getByText("数据说明").first().waitFor({ timeout: 10000 });
      await page.getByText("隐私政策").first().click();
      await page.waitForTimeout(300);
      await shot("20-settings");

      // No verification markers should remain anywhere in the interface.
      const bodyText = await page.locator("body").innerText();
      const markers = ["待核验", "待人工核验", "尚未逐条核验"].filter((m) => bodyText.includes(m));
      console.log("残留的数据核验标记:", markers.length ? markers.join(" / ") : "无");

      // Whether progress survives a reload (localStorage persistence). Run before the site data is
      // cleared, because that clear is what the next block is about.
      await page.reload({ waitUntil: "networkidle" });
      await page.waitForTimeout(700);
      const kept = await page
        .getByText("申请流程")
        .first()
        .isVisible()
        .catch(() => false);
      console.log("刷新后仍在主流程（localStorage 生效）:", kept);
      await shot("21-after-reload");

      // The profile must now survive without localStorage: reload after clearing site data and the
      // server-side copy should still answer. This runs last, because the clear also resets the stage
      // that still lives on localStorage and the browser ends up back in onboarding.
      await page.evaluate(() => window.localStorage.clear());
      await page.reload({ waitUntil: "networkidle" });
      await page.waitForTimeout(800);
      const serverProfile = await page.evaluate(async () => {
        const response = await fetch("/api/profile");
        return response.json();
      });
      console.log("清空 localStorage 后服务端仍有档案:", serverProfile.schoolName ? "是" : "否");

      // The assertion above only proves the server still holds a row. Clearing localStorage also reset
      // the stage, so the reload landed back on onboarding, and whether the UI *reads* that row is what
      // this line settles. The school field sits two steps in, and the value it has to show is the one
      // the server just answered with: the walker reads that value back from the API rather than
      // expecting a copy this script typed in.
      await page
        .locator("button.option")
        .filter({ hasText: /^\s*本科/ })
        .first()
        .click();
      await page.waitForTimeout(250);
      await page
        .locator("button.option")
        .filter({ hasText: /^\s*国内院校/ })
        .first()
        .click();
      await page.waitForTimeout(250);
      const serverSchoolName = await page.evaluate(
        async () => (await (await fetch("/api/profile")).json()).schoolName,
      );
      const shownSchoolName = await page
        .locator('input[placeholder="例如：北京邮电大学"]')
        .first()
        .inputValue()
        .catch(() => null);
      const restoredOk = Boolean(serverSchoolName) && shownSchoolName === serverSchoolName;
      console.log(
        "重新打开后档案已从服务端恢复:",
        restoredOk ? "是" : "否",
        JSON.stringify({ expected: serverSchoolName, actual: shownSchoolName }),
      );
      await shot("22-profile-restored-from-server");

      // The roadmap definition comes from the server, so the rendered phases have to match the served
      // ones — count and names, not merely "something rendered".
      //
      // The localStorage clear above also reset the stage, so the reload after it lands in onboarding and
      // the roadmap is not on screen at all. Putting the stage back into storage first is what makes the
      // reload a genuine cold start of the main interface with browser storage otherwise empty: the page
      // mounts, fetches the definition, builds the roadmap, and only then is anything counted.
      //
      // The expected value is read from the API in the same reloaded page rather than hardcoded, because a
      // hardcoded 7 would pass against a stale build and would have to be edited every time the definition
      // grows. That read is allowed to fail: a run against a broken definition route is a run where the
      // page is *supposed* to fall back, and reporting that is this block's job. Crashing on the read
      // instead would fail the run without saying which of the two things was wrong.
      await page.evaluate(() => {
        window.localStorage.setItem("offerpilot.state.v1", JSON.stringify({ stage: "app" }));
      });
      await page.reload({ waitUntil: "networkidle" });
      await page.getByText("申请流程").first().waitFor({ timeout: 15000 });
      await page.waitForTimeout(500);

      const readDefinition = () =>
        page.evaluate(async () => {
          // The marker separates this read from the page's own request for the same route. Without it the
          // two are indistinguishable, so a run that stubs the route cannot make the page and this check
          // disagree — and a check that cannot disagree with the page proves nothing about the page.
          const response = await fetch("/api/roadmap?from=walkthrough");
          if (!response.ok) return { ok: false, status: response.status };
          const body = await response.json();
          return { ok: true, phases: body.phases ?? [] };
        });
      let definition = await readDefinition();
      // One retry: this read races nothing in particular today, but a half-open route is not the condition
      // the assertion is about.
      if (!definition.ok) definition = await readDefinition();

      const renderedPhases = await page.evaluate(() => {
        const items = [...document.querySelectorAll("ol > li")];
        return items
          .map((li) => li.querySelector("strong")?.innerText?.trim() ?? null)
          .filter((title) => title !== null);
      });

      // Whether the page is showing the built-in copy is read first: it is the page's own answer, and the
      // condition that decides which of the two claims below is the one this run has to make.
      const fallbackNotice = await page
        .getByText("路线图定义未能从服务器读取")
        .first()
        .isVisible()
        .catch(() => false);

      if (definition.ok) {
        // The definition is reachable, so the page has to be rendering exactly it, in its order. A page
        // that never fetched, one that silently fell back to the six built-in phases, and one that dropped
        // a phase all disagree with the served list here.
        const servedTitles = definition.phases.map((p) => p.title);
        check(
          "清空浏览器存储并重载后路线图仍渲染，且阶段与接口一致",
          servedTitles.length > 0 && JSON.stringify(renderedPhases) === JSON.stringify(servedTitles),
          { served: servedTitles, rendered: renderedPhases },
        );
        // The same condition from the other side: the page says out loud when it is showing the built-in
        // copy, so the absence of that notice is what proves these phases came from the server.
        check("路线图由服务端定义渲染（未显示内置副本提示）", !fallbackNotice);
      } else {
        // The definition could not be fetched, so the page is required to keep rendering and to say which
        // copy it used. A blank screen and a silent fallback are both failures here.
        check(
          `定义接口不可用时（HTTP ${definition.status}）路线图仍渲染且说明用了内置副本`,
          renderedPhases.length > 0 && fallbackNotice,
          { rendered: renderedPhases, fallbackNotice },
        );
      }
      // No screenshot of its own: 21-after-reload already shows this exact view, and a second identical
      // image would be churn rather than evidence. The two lines above are the record.

      // ---------------------------------------------------------------------------------------------
      // The recomputation write path (M2b task 4): a tick reaches the server, survives a reload, and
      // survives a recomputation; a failed write is visible.
      //
      // The block works on the subject this page already has, which is the subject the blocks above have
      // been using. That is deliberate rather than a shortcut: a reload is the state the claim is about,
      // and a subject whose rows already exist on the server is exactly the case where a recomputation
      // must leave them alone. Its rows are all `system` when the walkthrough is run against a database
      // that has not seen this browser before, and the ticks it makes are the only `user` rows it creates.
      //
      // Every check here is a `check()`, not a `console.log`: each one can fail the run and names what
      // disagreed. The claims are the design's acceptance criteria — section 8.3's "a recomputation does
      // not lose completion state", from a reload and from a recompute — plus the visible-failure rule.
      // ---------------------------------------------------------------------------------------------
      const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
      /** The server's own rows for the current subject, as `GET /api/roadmap` serves them. */
      const readTasks = () =>
        page.evaluate(async () => {
          const response = await fetch("/api/roadmap?from=walkthrough-tasks");
          if (!response.ok) return null;
          return (await response.json()).tasks ?? [];
        });

      await page.reload({ waitUntil: "networkidle" });
      await page.getByText("申请流程").first().waitFor({ timeout: 15000 });
      await page.waitForTimeout(400);
      // From here on the captures describe this block alone. The arrays were also collecting the traffic
      // of the blocks above, and the first `PATCH` in that list belongs to the tick those blocks made —
      // which is how a check that read `taskPatches[0]` ended up asserting against the wrong row.
      await sleep(1200);
      taskPuts.length = 0;
      taskPatches.length = 0;

      // The first load of a subject with no rows on the server is the case that triggers a recomputation,
      // so the rows have to appear without anything being ticked. A subject that already has rows writes
      // nothing, which the last check in this block pins.
      let freshRows = [];
      for (let i = 0; i < 20 && freshRows.length === 0; i += 1) {
        await sleep(250);
        freshRows = (await readTasks()) ?? [];
      }
      check("重载后服务端持有本主体的任务行", freshRows.length > 0 && taskPuts.length <= 1, {
        puts: taskPuts.length,
        rows: freshRows.length,
      });
      // Every other row below is one this block writes, so it is `system`; the walkthrough's own earlier
      // tick is the single `user` row left over. The check names it rather than tolerating it, so a
      // recomputation that silently re-owned a human's row would fail here.
      const foreignRows = freshRows.filter((row) => row.origin !== "system");
      check(
        "服务端的行除申请人自己勾选的那条外，全部为 system 归属",
        foreignRows.length <= 1 && foreignRows.every((row) => row.origin === "user"),
        foreignRows.map((row) => [row.materialKey, row.origin]),
      );
      // The applicable keys are what tells the server "this key still applies" apart from "this payload
      // does not mention it" — the distinction §3.8 turns on. The check is made on the write this block
      // triggers just below, because a subject whose rows already exist correctly writes nothing, and this
      // block cannot force one without moving the profile. Skipped, not passed, when the page's read never
      // wrote; a check that read an absent payload would be green on no evidence.
      const keysCheck = (put) => {
        const body = put?.body ?? null;
        return (
          Array.isArray(body?.applicableKeys) &&
          Array.isArray(body?.rows) &&
          body.applicableKeys.length >= body.rows.length
        );
      };

      // Tick a material. It goes through PATCH, never through the replacement, which is what keeps the
      // applicant's own mark out of the recomputation's reach.
      //
      // The phase the first tick lands in is read off the screen rather than assumed: the page opens on
      // 锁定申请组合, and the block later needs a *different* phase to fail a write in, because every
      // material of the claimed one is checked by then and a checkbox that is already checked is not a
      // control `check()` can act on.
      const roadmapPhases = await page.evaluate(() =>
        [...document.querySelectorAll("ol > li")]
          .map((li) => li.querySelector("strong")?.innerText?.trim())
          .filter(Boolean),
      );
      /** The phase the detail panel is showing: the card the page marks as selected. */
      const selectedPhase = () =>
        page.evaluate(() => {
          const card = [...document.querySelectorAll("ol > li")].find((li) =>
            li.querySelector("button")?.className.includes("border-2"),
          );
          return card?.querySelector("strong")?.innerText?.trim() ?? null;
        });
      const tickedPhase = await selectedPhase();
      const tickedBox = page.locator('input[type="checkbox"]').first();
      const tickedLabel = (await tickedBox.locator("xpath=ancestor::label[1]").innerText()).split("\n")[0].trim();
      await tickedBox.check();
      await sleep(800);
      check("勾选材料通过 PATCH 写单条，而不是整体替换", taskPatches.length === 1, taskPatches);
      check(
        "勾选请求的正文把该行标为 completed",
        taskPatches[taskPatches.length - 1]?.body?.status === "completed",
        taskPatches[taskPatches.length - 1]?.body,
      );
      // The last one, not the first: the captures were reset above, so any earlier `PATCH` is a leftover
      // from a block with its own subject, and reading the first would assert about the wrong row.
      const tickedPatch = taskPatches[taskPatches.length - 1] ?? { url: "" };
      const tickedId = String(tickedPatch.url).split("/").pop();
      let tickedRow = ((await readTasks()) ?? []).find((row) => row.id === tickedId);
      check(
        "被勾选的行在服务端变为 completed，且归属转为 user",
        tickedRow?.status === "completed" && tickedRow?.origin === "user" && Boolean(tickedRow?.completedAt),
        tickedRow,
      );

      // Move the profile so the applicable material set changes, which is the second and only other
      // reason to recompute. 研究型硕士 makes the research-plan material apply, and the recomputation is
      // required to report that as a new key.
      const beforeKeys = new Set(((await readTasks()) ?? []).map((row) => row.materialKey));
      const putsBeforeDegree = taskPuts.length;
      await page.getByRole("button", { name: "账户" }).hover();
      await page.waitForTimeout(250);
      await page.getByRole("button", { name: "个人信息", exact: true }).click();
      await page.getByText("每条都能单独改").waitFor({ timeout: 10000 });
      await page.getByRole("button", { name: "编辑目标学位" }).click();
      const degreeSelect = page.locator("select").first();
      const degreeOptions = await degreeSelect.locator("option").evaluateAll((nodes) =>
        nodes.map((node) => node.value),
      );
      const nextDegree = degreeOptions.includes("研究型硕士") ? "研究型硕士" : degreeOptions[1];
      // Remembered because `assessAll` filters the catalogue by the target degree, and no seeded program
      // is a research degree: after this edit the picker legitimately shows zero cards. The portfolio
      // block below puts the degree back rather than assuming the catalogue still matches — measured: a
      // picker with no cards at all, and a check that would have been measuring the empty state.
      demoDegree = nextDegree;
      await degreeSelect.selectOption(nextDegree);
      await page.getByRole("button", { name: "保存" }).first().click();
      for (let i = 0; i < 20 && taskPuts.length === putsBeforeDegree; i += 1) await sleep(250);
      check(
        "档案改变适用材料后触发一次新的重算",
        taskPuts.length > putsBeforeDegree,
        { before: putsBeforeDegree, after: taskPuts.length, degree: nextDegree },
      );
      const secondPut = taskPuts[taskPuts.length - 1] ?? { body: null };
      // The applicable keys are what tells the server "this key still applies" apart from "this payload
      // does not mention it" — the distinction §3.8 turns on. It is checked on the write this block just
      // caused, and skipped when the profile edit produced no new write at all: reading the previous
      // payload would be green on a request this block did not make.
      check(
        "写入请求同时带上 applicableKeys（服务端据此区分「不再适用」与「本次未提及」）",
        keysCheck(secondPut),
        { keys: secondPut.body?.applicableKeys?.length, rows: secondPut.body?.rows?.length },
        { selector: taskPuts.length <= putsBeforeDegree },
      );
      const secondKeys = new Set(secondPut.body?.applicableKeys ?? []);
      const addedKeys = [...secondKeys].filter((key) => !beforeKeys.has(key));
      check(
        "这次写入的 applicableKeys 反映了新的适用材料集合",
        addedKeys.length > 0,
        { addedKeys, keys: secondKeys.size },
      );

      // The heart of the origin rule: the row the applicant claimed is not in the replacement's rows, so
      // the recomputation cannot have rewritten it.
      check(
        "重算的替换请求不包含申请人已勾选的行（origin 规则）",
        Array.isArray(secondPut.body?.rows) &&
          secondPut.body.rows.every((row) => row.materialKey !== tickedRow?.materialKey),
        { rows: secondPut.body?.rows?.length ?? 0, ticked: tickedRow?.materialKey },
      );
      const afterRecompute = ((await readTasks()) ?? []).find((row) => row.id === tickedId);
      check(
        "重算后该行仍是 completed，completedAt 未被重写",
        afterRecompute?.status === "completed" &&
          afterRecompute?.completedAt === tickedRow?.completedAt &&
          afterRecompute?.origin === "user",
        { after: afterRecompute, before: tickedRow, label: tickedLabel },
      );
      // The same claim as the check above, read from the other side: the recomputation did not re-own any
      // row, and the set of rows the applicant owns is exactly what it was plus the tick this block made.
      const ownedRows = ((await readTasks()) ?? []).filter((row) => row.origin === "user");
      check(
        "重算没有把申请人拥有的行改成自己所有",
        ownedRows.some((row) => row.id === tickedId) && ownedRows.length <= 2,
        ownedRows.map((row) => [row.materialKey, row.origin]),
      );

      // A failed write has to be visible. The next tick is answered with a 500, so the page cannot have
      // stored it and the applicant must not be left believing it did.
      const rejectNextPatch = async (route) => {
        if (route.request().method() === "PATCH") {
          await route.fulfill({
            status: 500,
            contentType: "application/json",
            body: JSON.stringify({ detail: "walkthrough: forced failure" }),
          });
          return;
        }
        await route.continue();
      };
      await page.route("**/api/roadmap/tasks/*", rejectNextPatch);
      injectingFailure = true;
      // A phase whose materials the block has not ticked yet, and the first one that is not the phase the
      // first tick claimed: the material is read out of the list rather than assumed, so the tick cannot
      // land on a control that is already checked (which `check()` would refuse) or on the phase the
      // reload below has to bring back.
      const untickedPhase = roadmapPhases.find((title) => title !== tickedPhase);
      await clickText("流程进度");
      await page.waitForTimeout(200);
      await clickText(untickedPhase);
      await page.waitForTimeout(300);
      const failedBox = page.locator('input[type="checkbox"]:not(:checked)').first();
      const failedLabel = (await failedBox.locator("xpath=ancestor::label[1]").innerText()).split("\n")[0].trim();
      // The material the control names, read off the server's own rows rather than the screen: the
      // checkbox carries the label, and the row carries both the label and the key. Matching on the label
      // is what makes the failed tick's row identifiable without assuming which row the page picked.
      const completedBefore = ((await readTasks()) ?? []).filter((row) => row.status === "completed").length;
      await failedBox.check();
      await sleep(900);
      const failureNotice = await page
        .getByText("没有保存到服务器")
        .first()
        .isVisible()
        .catch(() => false);
      const failedStillUnchecked = await failedBox.isChecked().catch(() => null);
      check("写入失败时页面给出可见提示", failureNotice);
      check("写入失败后勾选被回退，界面不与服务器不一致", failedStillUnchecked === false, {
        checked: failedStillUnchecked,
      });
      await page.unroute("**/api/roadmap/tasks/*", rejectNextPatch);
      injectingFailure = false;
      await page.waitForTimeout(700);
      const failedRows = (await readTasks()) ?? [];
      // The count of completed rows is what the server's own rows say, and it has to be the count from
      // before this tick: the write was rejected, so nothing about it may have reached the database. A
      // count rather than a key because the row this tick was for is not one either this script or the
      // page has an id for until it is stored.
      check(
        "失败的那一次勾选没有留在服务端",
        failedRows.filter((row) => row.status === "completed").length === completedBefore,
        { before: completedBefore, after: failedRows.filter((row) => row.status === "completed").length, label: failedLabel },
      );

      // A reload must show that same tick, because it comes from the server rather than this device.
      //
      // The write count is snapshotted *before* the reload, not after it. A page that recomputes as it
      // mounts issues its `PUT` while the reload is still settling, so a baseline read afterwards already
      // contains that write and the check below could not fail for the behaviour it names. Measured with
      // the page's "the server already holds rows" guard deleted: the reload issued `PUT rows=31`, the
      // baseline had been taken after it, and the check still printed 是 and the run exited 0. The count
      // below is a delta against this snapshot, so the reset at the top of this block — which is what
      // keeps the `PATCH` count to this block's own tick — is already accounted for, and nothing is
      // cleared here that could hide a write arriving while the reload is in flight.
      const putsBeforeReload = taskPuts.length;
      await page.reload({ waitUntil: "networkidle" });
      await page.getByText("申请流程").first().waitFor({ timeout: 15000 });
      await page.waitForTimeout(500);
      await page.getByRole("button", { name: "流程进度" }).click();
      await clickText(tickedPhase);
      await page.waitForTimeout(400);
      const restoredBox = page.locator('input[type="checkbox"]').first();
      const restoredChecked = await restoredBox.isChecked().catch(() => null);
      check("刷新后勾选状态仍在（完成状态来自服务端）", restoredChecked === true, {
        checked: restoredChecked,
        label: tickedLabel,
        phase: tickedPhase,
      });
      const putsAfterReload = taskPuts.length;
      await sleep(600);
      check(
        "服务端已有行时，刷新不会再次写入（不做无谓重算）",
        taskPuts.length === putsBeforeReload,
        { before: putsBeforeReload, after: taskPuts.length, settled: putsAfterReload },
      );
      await shot("23-task-tick-survives-reload");

      // ---------------------------------------------------------------------------------------------
      // The school-choice portfolio (M2c task 3): it is read from the server rather than from
      // localStorage, the application flow renders what the server holds, and a failed confirmation is
      // visible and does not advance the flow.
      //
      // The subject is the one every block above has used, and its portfolio rows are the ones the
      // picker's confirmation wrote through `PUT /api/applications`. That write is the hazard this
      // script's cleanup exists for, so it is real traffic against the real route rather than a stub.
      // ---------------------------------------------------------------------------------------------
      const readPortfolio = () =>
        page.evaluate(async () => {
          // The marker keeps this read distinguishable from the page's own request for the same route, so
          // a run that stubs the route cannot make the page and this check disagree.
          const response = await fetch("/api/applications?from=walkthrough-portfolio");
          if (!response.ok) return null;
          const body = await response.json();
          return Array.isArray(body) ? body : null;
        });

      const servedPortfolio = await readPortfolio();
      const serverSlugs = (servedPortfolio ?? []).map((row) => row.programId);
      check(
        "走查的确认动作把组合写进了服务端（PUT /api/applications）",
        servedPortfolio !== null &&
          servedPortfolio.length > 0 &&
          servedPortfolio.length === cardsBeforeConfirm,
        {
          rows: servedPortfolio === null ? null : servedPortfolio.length,
          cards: cardsBeforeConfirm,
          slugs: serverSlugs,
        },
      );

      // The catalogue the picker renders is the server's, and `nameEn` is the field this side's `name`
      // maps to. This is the mapping a key-for-key adapter gets wrong silently — it would show the
      // Chinese program name under a key whose whole meaning is "the English one" — so the assertion is
      // read off the rendered cards rather than off the payload the page happens to hold.
      //
      // The picker is reopened deliberately: this is where it renders, and reopening it also exercises the
      // read of the portfolio the server already holds, which is what stops a second confirmation from
      // dropping rows the applicant added by hand. The stage is put back afterwards so the block below
      // measures the main interface.
      // Back to the degree the onboarding answered with, so the catalogue has programs to render.
      const degreeRestore = await page.evaluate(async (degree) => {
        const response = await fetch("/api/profile", {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ targetDegree: degree }),
        });
        const body = await response.json();
        return { status: response.status, degree: body.targetDegree };
      }, ONBOARDING_DEGREE);
      // Asserted rather than assumed: if this write does not land, every catalogue check below is
      // measuring a picker with no cards, and the failure would be reported as "the interface is wrong".
      check(
        "走查把学位改回入学答案，项目目录才有可渲染的项目",
        degreeRestore.status === 200 && degreeRestore.degree === ONBOARDING_DEGREE,
        { ...degreeRestore, profileBefore: demoDegree },
      );
      await page.evaluate(() => {
        window.localStorage.clear();
        window.localStorage.setItem("offerpilot.state.v1", JSON.stringify({ stage: "portfolio" }));
      });
      await page.reload({ waitUntil: "networkidle" });
      await page.getByText("为你筛出的申请组合").waitFor({ timeout: 15000 });
      // The cards are rendered from the assessments, and the assessments come from the catalogue read this
      // page mounts with; waiting for a card rather than for a duration is what keeps this from measuring
      // the picker's empty first paint.
      await page.locator("article.card").first().waitFor({ timeout: 15000 });
      await page.waitForTimeout(400);

      const servedCatalogue = await page.evaluate(async () => {
        const response = await fetch("/api/programs?from=walkthrough-catalogue");
        if (!response.ok) return null;
        return response.json();
      });
      const renderedCards = await page.evaluate(() =>
        [...document.querySelectorAll("article.card")].map((card) => card.innerText),
      );
      const catalogue = servedCatalogue ?? [];
      // The number of cards is the catalogue's length, so a body that arrived empty is a failure here
      // rather than a comparison that passes over two empty lists.
      check(
        "选择页渲染的项目数与项目目录接口一致",
        catalogue.length > 0 && renderedCards.length === catalogue.length,
        { catalogue: catalogue.length, cards: renderedCards.length },
      );
      const englishOnScreen = catalogue.filter((program) =>
        renderedCards.some((text) => text.includes(program.nameEn)),
      );
      const chineseOnScreen = catalogue.filter((program) =>
        renderedCards.some((text) => text.includes(program.name)),
      );
      check(
        "项目目录来自接口，卡片渲染的是 nameEn（英文名）而不是 name",
        englishOnScreen.length === catalogue.length && chineseOnScreen.length === 0,
        {
          catalogue: catalogue.length,
          english: englishOnScreen.map((p) => p.nameEn),
          chinese: chineseOnScreen.map((p) => p.name),
        },
      );
      // The portfolio the server already holds is ticked when the picker opens, so the count on the
      // button is the evidence that the read above reached it rather than the recommendation only.
      const confirmLabel = await page.getByRole("button", { name: /确认组合/ }).innerText();
      const confirmCount = Number((/（(\d+) 个/.exec(confirmLabel) ?? [])[1] ?? NaN);
      check(
        "重新打开选择页时，服务端已有的组合被带入勾选状态",
        serverSlugs.length > 0 && confirmCount >= serverSlugs.length,
        { label: confirmLabel, serverRows: serverSlugs.length },
      );
      // No screenshot of its own: 08-portfolio already shows this exact view — the same catalogue, the same
      // ticks — and the checks above are the record of what it proves. A second identical image would be
      // churn rather than evidence.

      // The claim the brief's Step 5 names: clear the browser's storage, reload, and the portfolio is
      // still there and still the server's. The stage lives in localStorage, so it is put back first —
      // otherwise the reload lands in onboarding and there is no portfolio on screen to measure.
      await page.evaluate((sentinel) => {
        window.localStorage.clear();
        window.localStorage.setItem(
          "offerpilot.state.v1",
          JSON.stringify({
            stage: "app",
            // A program that is in no catalogue. If anything on this page rendered from storage, this
            // slug would be in the list below.
            portfolio: [{ programSlug: sentinel, tier: "保", confirmed: true }],
          }),
        );
      }, SENTINEL_PROGRAM);
      await page.reload({ waitUntil: "networkidle" });
      await page.getByText("申请流程").first().waitFor({ timeout: 15000 });
      await page.waitForTimeout(600);
      await page.getByRole("button", { name: "首页" }).click();
      await page.waitForTimeout(400);
      const renderedSlugs = await page.evaluate(() =>
        [...document.querySelectorAll("li span.font-semibold")].map((n) =>
          // The list renders `大学 · 名称` from the program the server served with the row, for every row:
          // a program the catalogue cannot resolve prints the unknown marker on both sides of the dot
          // rather than a bare slug, so this reads the name half back out of the one shape there is.
          n.innerText.includes(" · ") ? n.innerText.split(" · ").slice(1).join(" · ") : n.innerText,
        ),
      );
      const afterClear = await readPortfolio();
      const afterClearSlugs = (afterClear ?? []).map((row) => row.programId);
      check(
        "清空浏览器存储并重载后组合仍在，且与服务器一致",
        afterClearSlugs.length > 0 &&
          JSON.stringify([...afterClearSlugs].sort()) === JSON.stringify([...serverSlugs].sort()) &&
          renderedSlugs.length === afterClearSlugs.length,
        { server: afterClearSlugs, rendered: renderedSlugs, before: serverSlugs },
      );
      // The other half of "the server owns it", and the check that can fail: a sentinel row was written
      // into the browser's copy of the portfolio *before* the reload, and if the page were still rendering
      // from storage the sentinel would be on screen. It is not: the list is the server's answer.
      //
      // A weaker version of this compared the re-saved storage field against `undefined` and stayed red
      // without meaning anything — the key is still written, with whatever this device holds, because the
      // storage contract is `store.test.ts`'s subject and was deliberately left alone (the
      // `completedMaterials` precedent). What actually changed is who the value comes from, and that is
      // what the sentinel measures.
      check(
        "组合的真相在服务端：浏览器存储里的组合不会被渲染",
        !renderedSlugs.includes(SENTINEL_PROGRAM),
        { sentinelOnScreen: renderedSlugs.includes(SENTINEL_PROGRAM), rendered: renderedSlugs },
      );

      // The claim M2d is about: the portfolio card renders the program the *server* sent, rather than a
      // lookup in `web/lib/programs.ts`.
      //
      // The expected side is `nameEn`, which is the name this side calls `name` (§3.6), read off the rows
      // the route served to this same reloaded page. The two sides are kept apart on purpose: a page that
      // resolved the row through the constants array would print the *Chinese* names for the programs the
      // array carries and the bare slug for anything it does not, and both are disagreements this check
      // reports. The expected value is never the slug and never the string the page happens to hold, so the
      // two can differ — an assertion written against the page's own idea of the label would agree with
      // any implementation, including the one this task removes.
      //
      // What this check cannot settle is the *source*: the constants array and the seeded catalogue agree
      // on all six programs, so a lookup renders the same text and keeps this green. The static half is
      // `make check-programs-readers` — it walks the import graph out of `web/app` and fails if
      // `web/lib/programs.ts` is reachable from a page, however many hops away — and this check is the
      // half that measures what the page actually drew.
      //
      // The card is addressed by its `data-testid` because 首页 renders the `·`-joined school label in the
      // 申请档案 card as well, and a text-shaped selector would leave the subject of this check ambiguous.
      // Each row is compared whole, `大学 · 名称` together: that is the copy the card shows, so it is the
      // copy the server's answer has to account for. Trimming the label out of it would compare one half
      // and leave the other free to drift.
      const servedLabels = (afterClear ?? [])
        .map((row) =>
          row.program === null || !row.program?.nameEn
            ? null
            : `${row.program.university} · ${row.program.nameEn}`,
        )
        .filter((label) => label !== null)
        .sort();
      const renderedLabels = await page.evaluate(() =>
        [...document.querySelectorAll('[data-testid="home-portfolio"] li span.font-semibold')].map(
          (node) => node.innerText,
        ),
      );
      check(
        "首页组合卡片渲染的项目名来自服务端下发的 program（不是常量数组）",
        servedLabels.length > 0 &&
          renderedLabels.length === servedLabels.length &&
          JSON.stringify([...renderedLabels].sort()) === JSON.stringify(servedLabels),
        { served: servedLabels, rendered: renderedLabels },
      );
      // The other view this batch changed, and the one the plan recorded as a risk: its roadmap phases
      // carry no program at all, so the only program copy on that screen is the branch list, and it has to
      // come from the same served rows.
      //
      // The settlement of the comparison is the card's own: `首页` draws `大学 · 名称` in one span, and
      // that view draws the two in two elements, so its rendered text separates them with a space rather
      // than the dot. Both sides are normalised to the same shape before they are compared, which keeps
      // the check about the program rather than about the punctuation between the two fields.
      //
      // `.first()` because 首页 renders two controls whose accessible name contains 流程进度 — the tab and
      // the 进入流程进度 button — and an unqualified role query resolves to both and throws.
      await page.getByRole("button", { name: "流程进度" }).first().click();
      await page.waitForTimeout(500);
      const normalise = (text) => text.replace(/[·\s]+/g, " ").trim();
      const renderedBranches = await page.evaluate(() =>
        [...document.querySelectorAll('[data-testid="flow-program-branches"] li')].map((node) =>
          node.innerText,
        ),
      );
      check(
        "流程页的项目分支渲染的也是服务端下发的项目名",
        servedLabels.length > 0 &&
          servedLabels.every((label) =>
            renderedBranches.some((branch) => normalise(branch).includes(normalise(label))),
          ),
        { served: servedLabels, rendered: renderedBranches },
      );
      // Back to 首页 before the screenshot: 24 has always shown the portfolio card, and a run that left
      // the tab on 流程 would quietly replace that image with a different view.
      await page.getByRole("button", { name: "首页" }).first().click();
      await page.waitForTimeout(400);
      await shot("24-portfolio-survives-storage-clear");

      // A confirmation the server refuses has to be visible and must not advance the flow, or the
      // applicant lands on an application view built from a portfolio the database never stored. The
      // write is answered with a 500 here, which is the same shape as the failed tick above.
      const beforeFailedConfirm = (await readPortfolio() ?? []).length;
      const rejectPortfolio = async (route) => {
        if (route.request().method() === "PUT") {
          await route.fulfill({
            status: 500,
            contentType: "application/json",
            body: JSON.stringify({ detail: "walkthrough: forced failure" }),
          });
          return;
        }
        await route.continue();
      };
      await page.route("**/api/applications", rejectPortfolio);
      await page.evaluate(() => {
        window.localStorage.clear();
        window.localStorage.setItem("offerpilot.state.v1", JSON.stringify({ stage: "portfolio" }));
      });
      await page.reload({ waitUntil: "networkidle" });
      await page.getByText("为你筛出的申请组合").waitFor({ timeout: 15000 });
      await page.waitForTimeout(900);
      injectingFailure = true;
      const chosenBefore = await page.getByRole("button", { name: /确认组合/ }).innerText();
      await page.getByRole("button", { name: /确认组合/ }).click();
      await page.waitForTimeout(900);
      const confirmFailure = await page
        .getByText("申请组合没有保存到服务器")
        .first()
        .isVisible()
        .catch(() => false);
      const stillOnPicker = await page.getByText("为你筛出的申请组合").isVisible().catch(() => false);
      // The navigation tab, matched exactly. A substring match on 申请流程 also matches the picker's own
      // subtitle ("勾掉不想申的，确认后进入申请流程。"), so the loose version of this check reported
      // "the flow is on screen" against the picker itself and could never pass.
      const reachedFlow = await page
        .getByRole("button", { name: "流程进度", exact: true })
        .first()
        .isVisible()
        .catch(() => false);
      check("组合写入失败时页面给出可见提示", confirmFailure, { button: chosenBefore });
      check(
        "组合写入失败后没有进入申请流程（界面不与服务器不一致）",
        stillOnPicker && !reachedFlow,
        { picker: stillOnPicker, flow: reachedFlow },
      );
      await page.unroute("**/api/applications", rejectPortfolio);
      injectingFailure = false;
      const afterFailedConfirm = (await readPortfolio() ?? []).length;
      check(
        "失败的那一次确认没有改到服务端的组合",
        afterFailedConfirm === beforeFailedConfirm,
        { before: beforeFailedConfirm, after: afterFailedConfirm },
      );
      await shot("25-portfolio-save-failed");

      // ---------------------------------------------------------------------------------------------
      // The material library (M3): one file uploaded against a roadmap requirement, classified, sent
      // for review, downloaded, reviewed, and still there after a reload. Every step goes through the
      // real route with the real cookie, because the point of the block is that the library is the
      // server's answer rather than this tab's.
      //
      // The review is recorded by the operator command rather than through the page, because that is
      // the only way it can be recorded at all: this batch deliberately has no HTTP route for it. The
      // command runs as a real process here, which is also what makes the rendering of a sourced finding
      // reachable in a browser at all.
      // ---------------------------------------------------------------------------------------------
      const materialUploads = [];
      await page.route(/\/api\/documents$/, async (route) => {
        if (route.request().method() === "POST") materialUploads.push(route.request().url());
        await route.continue();
      });

      // A real file on disk, named so that its extension lies about its contents.
      //
      // The name is the point. The browser declares a part's content type from the extension, so a file
      // called `.pdf` holding PDF bytes is declared correctly and the check below could not tell a server
      // that sniffs from one that believes the declaration. With PDF bytes in a `.png`, the two answers
      // differ and the check can fail: the route must store `application/pdf`.
      const materialPath = path.join(os.tmpdir(), "offerpilot-walkthrough-material.png");
      const materialBytes =
        "%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n";
      fs.writeFileSync(materialPath, materialBytes);

      const readMaterials = () =>
        page.evaluate(async () => {
          // The marker keeps this read distinguishable from the page's own request for the same route.
          const response = await fetch("/api/documents?from=walkthrough-materials");
          if (!response.ok) return null;
          const body = await response.json();
          return Array.isArray(body) ? body : null;
        });

      // The block above deliberately ends on the picker, with a confirmation the stub refused, so the
      // first thing to do is get back into the application flow: confirming the same portfolio again
      // succeeds now that the failing route is unrouted. Without this the tab row does not exist yet and
      // the click below waits for a button that is not on the page — measured, as a 30s timeout.
      await page.getByRole("button", { name: /确认组合/ }).click();
      await page.waitForTimeout(1200);
      await page.getByRole("button", { name: "流程进度" }).first().click();
      await clickText("学术与身份材料");
      await page.waitForTimeout(400);
      await page
        .locator('[data-testid="upload-material"] input[type="file"]')
        .first()
        .setInputFiles(materialPath);
      await page.waitForTimeout(1500);
      check("上传材料发出了一条真实的 POST /api/documents", materialUploads.length === 1, {
        uploads: materialUploads.length,
      });

      const uploadedRows = (await readMaterials()) ?? [];
      check("服务端自己持有刚上传的材料", uploadedRows.length === 1, { rows: uploadedRows.length });
      check(
        "服务端按魔数判定了类型，而没有信浏览器按扩展名给的类型",
        uploadedRows[0]?.currentVersion?.mimeType === "application/pdf",
        {
          declaredByName: "image/png",
          stored: uploadedRows[0]?.currentVersion?.mimeType,
          filename: uploadedRows[0]?.currentVersion?.filename,
        },
      );
      check("上传时没有分类，服务端如实记为空", uploadedRows[0]?.kind === null, {
        kind: uploadedRows[0]?.kind,
      });
      check(
        "上传时挂上了这条材料对应的任务要求",
        typeof uploadedRows[0]?.taskId === "string" && uploadedRows[0].taskId.length > 0,
        { taskId: uploadedRows[0]?.taskId },
      );

      await page.getByRole("button", { name: "材料库" }).click();
      await page.waitForTimeout(600);
      const materialRows = page.locator('[data-testid="material-row"]');
      check("材料库渲染了这份材料", (await materialRows.count()) === 1, {
        rows: await materialRows.count(),
      });
      // The badges, not the row's whole text: the row contains the classification picker, whose options
      // include 其他材料, so a substring test over the row passes and fails for the wrong reason.
      const uploadedBadges = await materialRows
        .first()
        .locator('[data-testid="material-badge"]')
        .allInnerTexts();
      check(
        "未分类的材料显示为未分类，而不是其他材料",
        uploadedBadges.includes("未分类") && !uploadedBadges.includes("其他材料"),
        { badges: uploadedBadges.join(" / ") },
      );
      // The picker must not have a classification of its own: this batch's review found it defaulting to
      // 成绩单, which made one click on 归档 file an unclassified material as a transcript.
      const pickerBeforeChoice = await materialRows.first().locator("select").inputValue();
      check("分类下拉框没有替申请人预选一个分类", pickerBeforeChoice === "", {
        value: pickerBeforeChoice,
      });
      check(
        "还没有选分类时，归档按钮不可点",
        await materialRows.first().getByRole("button", { name: "归档" }).isDisabled(),
        {},
      );
      await shot("26-material-uploaded");

      await materialRows.first().locator("select").selectOption("gs");
      await materialRows.first().getByRole("button", { name: "归档" }).click();
      await page.waitForTimeout(1200);
      const archivedRow = (await readMaterials() ?? [])[0];
      check(
        "归档写进了服务端，并记下了申请人选的分类与归档时间",
        archivedRow?.kind === "gs" &&
          archivedRow?.status === "archived" &&
          typeof archivedRow?.archivedAt === "string",
        { kind: archivedRow?.kind, status: archivedRow?.status },
      );
      check("界面上显示的是服务端的状态", (await materialRows.first().innerText()).includes("已归档"), {});

      await materialRows.first().getByRole("button", { name: "送审" }).click();
      await page.waitForTimeout(1200);
      const submittedRow = (await readMaterials() ?? [])[0];
      check("送审把材料推进到审核中", submittedRow?.status === "under_review", {
        status: submittedRow?.status,
      });
      await shot("27-material-submitted");

      // The download, clicked rather than read: the link is a plain navigation, so the only way to know
      // it serves the stored bytes is to follow it.
      const [download] = await Promise.all([
        page.waitForEvent("download"),
        materialRows.first().getByRole("link", { name: "下载" }).click(),
      ]);
      const downloadedPath = await download.path();
      const downloaded = fs.readFileSync(downloadedPath);
      check(
        "下载拿到的是存进去的那份文件",
        downloaded.equals(Buffer.from(materialBytes, "utf8")),
        { bytes: downloaded.length, name: download.suggestedFilename() },
      );

      await materialRows.first().getByRole("button", { name: /查看审核/ }).click();
      await page.waitForTimeout(1000);
      const materialDetail = page.locator('[data-testid="material-detail"]');
      const detailText = await materialDetail.innerText().catch(() => "");
      check(
        "还没有审核结论时，面板说的是还没有，而不是编一条出来",
        detailText.includes("还没有审核结论") && !detailText.includes("通过 ·"),
        { text: detailText.replace(/\n/g, " / ").slice(0, 160) },
      );

      // The operator command, as a real process against the same database. Its `--version` is the
      // material's current version, which is what makes the recorded review bind to the bytes on screen.
      execFileSync(
        API_PYTHON,
        [
          "review_cli.py", "review", archivedRow.id,
          "--version", String(archivedRow.currentVersion.versionNo),
          "--overall", "needs_revision",
          "--reviewed-by", "走查审查者",
          "--summary", "回答需要补充",
          "--finding", "gs-answer-length:warning:第二条回答 213 词，超过 150 词",
        ],
        { cwd: API_DIR },
      );

      await page.reload({ waitUntil: "networkidle" });
      await page.waitForTimeout(700);
      await page.getByRole("button", { name: "材料库" }).click();
      await page.waitForTimeout(700);
      const reloadedText = await page.locator('[data-testid="material-row"]').first().innerText();
      check(
        "刷新后材料、分类与状态仍在（全部来自服务端）",
        reloadedText.includes("Genuine Student 陈述") && reloadedText.includes("需要修改"),
        { text: reloadedText.replace(/\n/g, " / ") },
      );

      await page.locator('[data-testid="material-row"]').first().getByRole("button", { name: /查看审核/ }).click();
      await page.waitForTimeout(1200);
      const reviewedDetail = await page.locator('[data-testid="material-detail"]').innerText();
      check(
        "审核结论渲染出了具体建议",
        reviewedDetail.includes("第二条回答 213 词，超过 150 词") &&
          reviewedDetail.includes("走查审查者"),
        { text: reviewedDetail.replace(/\n/g, " / ").slice(0, 200) },
      );
      check(
        "每条建议都带着它引用的审核要点",
        reviewedDetail.includes("回答长度") && reviewedDetail.includes("gs-answer-length"),
        {},
      );
      // The target, not the link's text: the panel shows the page's title and puts the URL in the href,
      // so `innerText` cannot see it — the first version of this check looked for the URL in the text and
      // failed while the link was correct.
      const reviewedSource = page
        .locator('[data-testid="material-detail"] a[href^="https://immi.homeaffairs.gov.au/"]')
        .first();
      const sourceHref = await reviewedSource.getAttribute("href").catch(() => null);
      check(
        "每条建议都带着要点出自的官方页面与它的核验状态",
        sourceHref ===
          "https://immi.homeaffairs.gov.au/visas/getting-a-visa/visa-listing/student-500/genuine-student-requirement" &&
          reviewedDetail.includes("待核验"),
        { href: sourceHref, mentionsStatus: reviewedDetail.includes("待核验") },
      );
      await shot("28-material-survives-reload");

      // The library at a phone width, which is the layout the tab row and the row controls have to
      // survive: the tabs scroll rather than being pushed off, and every control on a material stays
      // reachable instead of being clipped by the narrower card.
      await page.setViewportSize({ width: 390, height: 844 });
      await page.waitForTimeout(500);
      const narrowRow = page.locator('[data-testid="material-row"]').first();
      check(
        "窄屏下材料行仍然完整可见",
        await narrowRow.isVisible().catch(() => false),
        { width: 390 },
      );
      const narrowControls = await narrowRow
        .locator("a, button, select, label")
        .evaluateAll((nodes) =>
          nodes.map((node) => {
            const box = node.getBoundingClientRect();
            return { text: (node.textContent || "").trim().slice(0, 12), right: Math.round(box.right) };
          }),
        );
      check(
        "窄屏下没有控件被裁到视口外",
        narrowControls.every((control) => control.right <= 390),
        {
          widest: narrowControls.reduce((max, control) => Math.max(max, control.right), 0),
          controls: narrowControls.length,
        },
      );
      await shot("29-material-narrow");
      await page.setViewportSize({ width: 1280, height: 900 });
      await page.waitForTimeout(300);
      await page.unroute(/\/api\/documents$/);


  } catch (error) {
    // A walked step that threw is reported through the same list an assertion uses, so the run still
    // prints every screenshot and every check it reached, then names what ended it. Letting it
    // propagate instead would replace all of that with a stack trace; the cleanup below would still
    // run, but nothing would say what had failed.
    failures.push("走查中断：" + (error instanceof Error ? error.message : String(error)));
  } finally {
    // ---------------------------------------------------------------------------------------------
    // Cleanup: put the shared development database back the way this run found it.
    //
    // This is not tidiness, and it is not conditional on the run having reached this line by the
    // ordinary path — it is in the `finally` because the opposite was measured. A walkthrough that
    // failed before its cleanup left 6 rows behind, and the next `pytest` reported 4 failures.
    // `applications.program_id` is a RESTRICT foreign key, so a portfolio row left behind blocks the
    // catalogue seed's sweep — `api/tests/test_seed.py` deletes every seeded program in three of its
    // tests — and `make verify` followed by `make test` then goes red on rows this script wrote itself,
    // with nothing in the failure saying who wrote them.
    //
    // Every subject this run minted is removed, not just the one cookie the script happened to read:
    // the pre-flight read below the browser launch is a subject of its own, and the first page load
    // mints several more. The count is printed so the number is measured rather than assumed.
    //
    // The check below can fail: the run's own portfolio rows are asserted gone, and outside a parallel
    // run they are the only ones these subjects have. It is written against the ids the run captured,
    // so it removes exactly the subjects the walkthrough created, along with their rows. A baseline
    // row count would be a weaker check — a concurrent run would make it disagree for a reason that is
    // not this one — so the captured ids are what the statements name.
    // ---------------------------------------------------------------------------------------------
    console.log("\n=== 清理 ===");
    for (const cookie of await context.cookies()) {
      if (cookie.name === "offerpilot_client") rememberSubject(cookie.value);
    }
    const captured = [...subjects.keys()];
    console.log("本次走查创建的主体数:", captured.length, JSON.stringify(captured));
    if (captured.length === 0) {
      check("走查结束时清理了本次主体", false, "没有读到任何 offerpilot_client cookie");
    } else {
      const quoted = captured.map((id) => `'${id}'`).join(", ");
      const removedRows = dbRun(`DELETE FROM applications WHERE client_id IN (${quoted})`);
      const removedClients = dbRun(`DELETE FROM clients WHERE id IN (${quoted})`);
      // Counted for the ids the run captured rather than for the whole table: a developer clicking in
      // the dev UI at the same time is not this run's leftover, and failing on their rows would be the
      // same defect this cleanup exists to prevent, one layer up.
      const leftOver = dbRun(`SELECT count(*) FROM applications WHERE client_id IN (${quoted})`);
      const clientsLeft = dbRun(`SELECT count(*) FROM clients WHERE id IN (${quoted})`);
      check("走查结束时清理了本次主体（组合行与主体行）", leftOver === "0" && clientsLeft === "0", {
        subjects: captured.length,
        removedApplications: removedRows,
        removedClients,
        leftOver,
        clientsLeft,
      });
      console.log("清理后这些主体的组合行数:", leftOver, "主体行数:", clientsLeft);
    }

    console.log("\n=== JS 错误 ===");
    console.log(errors.length ? errors.join("\n") : "无");
    if (injected.length) console.log("本次走查有意注入的错误:\n" + injected.join("\n"));
    if (skipped.length) console.log("跳过（本次运行没有对应的前提）:\n" + skipped.join("\n"));

    await browser.close();
    if (failures.length) console.error("断言未通过:\n" + failures.join("\n"));
    if (errors.length || failures.length) process.exitCode = 1;
  }
})();
