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
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const errors = [];
  page.on("console", (m) => m.type() === "error" && errors.push("console: " + m.text()));
  page.on("pageerror", (e) => errors.push("pageerror: " + e.message));

  const shot = async (name) => {
    await page.screenshot({ path: path.join(OUT, `${name}.png`) });
    console.log("shot:", name);
  };
  const clickText = async (t) => {
    await page.getByRole("button", { name: t, exact: false }).first().click();
    await page.waitForTimeout(250);
  };

  await page.goto(BASE, { waitUntil: "networkidle" });
  await shot("01-step1-education");

  await clickText("本科");
  await shot("02-step2-origin");

  await clickText("国内院校");
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

  await clickText("授课型硕士");
  await clickText("继续");
  await clickText("计算机与数据");
  await shot("05-step7-field");
  await clickText("继续");

  await page.locator("input").first().fill("IELTS 6.5");
  await clickText("继续");
  await clickText("20–30 万");
  await clickText("继续");
  await clickText("2027 S1");
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
  await clickText("个人中心");
  await page.waitForTimeout(300);
  await shot("14-profile");
  await clickText("留学顾问");
  await page.waitForTimeout(300);
  await shot("15-advisor");

  // Whether progress survives a reload (localStorage persistence).
  await page.reload({ waitUntil: "networkidle" });
  await page.waitForTimeout(700);
  const kept = await page
    .getByText("申请流程")
    .first()
    .isVisible()
    .catch(() => false);
  console.log("刷新后仍在主流程（localStorage 生效）:", kept);
  await shot("16-after-reload");

  console.log("\n=== JS 错误 ===");
  console.log(errors.length ? errors.join("\n") : "无");

  await browser.close();
  if (errors.length) process.exitCode = 1;
})();
