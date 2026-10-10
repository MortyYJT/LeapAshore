// Regression guard for dev-server origin access.
//
// Next.js blocks its own dev assets and the HMR socket when the page is opened from a hostname the
// dev server does not trust, which leaves the page rendered but unresponsive because React never
// hydrates. The failure is silent in the browser: the markup looks correct and nothing reports an
// error on screen, so it is easy to ship.
//
// This script opens the app from every origin the config allows plus localhost and asserts that one
// click actually advances the flow.
//
// Usage: node scripts/dev-origin-check.cjs   (requires the dev server on port 3000)

const fs = require("fs");
const path = require("path");

const { chromium } = require("./playwright.cjs");

const ROOT = path.resolve(__dirname, "..");
const PORT = process.env.PORT || "3000";

// Read the allowlist straight from the config so this check cannot drift away from it.
const configSource = fs.readFileSync(path.join(ROOT, "web/next.config.ts"), "utf8");
const match = /allowedDevOrigins:\s*\[([^\]]*)\]/.exec(configSource);
const configured = match
  ? [...match[1].matchAll(/"([^"]+)"/g)].map((m) => m[1])
  : [];

const hosts = ["localhost", ...configured];
const origins = hosts.map((h) => `http://${h}:${PORT}`);

(async () => {
  const browser = await chromium.launch();
  const failures = [];
  let firstStepOk = 0;

  for (const origin of origins) {
    const page = await browser.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));

    let reachable = true;
    try {
      await page.goto(origin, { waitUntil: "networkidle", timeout: 10000 });
    } catch {
      reachable = false;
    }

    if (!reachable) {
      console.log(`SKIP  ${origin}  (not reachable from this machine)`);
      await page.close();
      continue;
    }

    await page
      .getByRole("button", { name: "本科", exact: false })
      .first()
      .click({ timeout: 4000 })
      .catch(() => {});
    await page.waitForTimeout(500);

    const advanced = await page
      .getByText("你的学校在哪里")
      .isVisible()
      .catch(() => false);

    if (advanced) {
      firstStepOk += 1;
      console.log(`PASS  ${origin}  interactive`);
    } else {
      failures.push(origin);
      console.log(`FAIL  ${origin}  rendered but not interactive`);
      if (errors.length) console.log(`      page errors: ${errors.slice(0, 2).join(" | ")}`);
    }
    await page.close();
  }

  await browser.close();

  console.log(`\n${firstStepOk}/${origins.length} origins interactive`);
  if (failures.length) {
    console.log("\nNot interactive:");
    for (const f of failures) console.log(`  - ${f}`);
    console.log(
      "\nAdd the hostname to allowedDevOrigins in web/next.config.ts (hostname only, no scheme or port).",
    );
    process.exitCode = 1;
  }
})();
