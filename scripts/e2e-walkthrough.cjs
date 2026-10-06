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

  console.log("\n=== JS 错误 ===");
  console.log(errors.length ? errors.join("\n") : "无");

  await browser.close();
  if (errors.length) process.exitCode = 1;
})();
