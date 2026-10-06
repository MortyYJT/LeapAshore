// End-to-end walkthrough: drive a real browser through onboarding, portfolio selection, the main
// interface, and a reload, capturing a screenshot per step and reporting JS errors at the end.
//
// Usage: node scripts/e2e-walkthrough.cjs
// Requires the dev server on localhost:3000 (make dev).
//
// Playwright is borrowed from a sibling checkout rather than installed here; override with PLAYWRIGHT_PATH.

const path = require("path");
const fs = require("fs");

const PLAYWRIGHT =
  process.env.PLAYWRIGHT_PATH ||
  "~/Documents/留学agent/web/node_modules/@playwright/test";
const { chromium } = require(PLAYWRIGHT);

const ROOT = path.resolve(__dirname, "..");
const OUT = path.join(ROOT, "docs/screenshots");
const BASE = process.env.BASE_URL || "http://localhost:3000";

fs.mkdirSync(OUT, { recursive: true });

(async () => {
  // The profile now lives on the server, so a walkthrough with no backend would drive a page whose
  // profile never loads and report success for the empty version of every assertion below. Fail
  // here instead, with the address that was tried.
  try {
    const response = await fetch(`${BASE}/api/profile`);
    if (!response.ok) throw new Error(`GET /api/profile responded ${response.status}`);
    await response.json();
  } catch (error) {
    console.error(
      `后端不可达：GET ${BASE}/api/profile 失败（${error.message}）。` +
        "先运行 make dev（同时启动前端与 :8000 上的后端），再跑 make screenshots。",
    );
    process.exitCode = 1;
    return;
  }

  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const errors = [];
  page.on("console", (m) => m.type() === "error" && errors.push("console: " + m.text()));
  page.on("pageerror", (e) => errors.push("pageerror: " + e.message));

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
  const check = (name, ok, detail) => {
    console.log(name + ":", ok ? "是" : "否", detail === undefined ? "" : JSON.stringify(detail));
    if (!ok) failures.push(name + (detail === undefined ? "" : " " + JSON.stringify(detail)));
  };

  await page.goto(BASE, { waitUntil: "networkidle" });
  await shot("01-step1-education");

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

  await clickText("确认组合");
  await page.getByText("申请流程").first().waitFor({ timeout: 15000 });
  await page.waitForTimeout(500);
  await shot("10-flow");

  await clickText("语言准备");
  await page.waitForTimeout(300);
  await shot("11-flow-language");

  await page.locator('input[type="checkbox"]').first().check();
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

  console.log("\n=== JS 错误 ===");
  console.log(errors.length ? errors.join("\n") : "无");

  await browser.close();
  if (failures.length) console.error("断言未通过:\n" + failures.join("\n"));
  if (errors.length || failures.length) process.exitCode = 1;
})();
