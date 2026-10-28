// Render one page in real Chrome and print {status, url, html} as JSON on stdout.
//
// Used by `api/app/collect/snapshot.py --render` for program pages that build their content with
// JavaScript. It runs the installed Chrome (`channel: "chrome"`), not Playwright's bundled browser,
// which clips CJK glyphs. It does not retry or disguise itself when a site refuses the request.

const { chromium } = require("./playwright.cjs");

(async () => {
  const [url, userAgent] = process.argv.slice(2);
  const browser = await chromium.launch({ channel: "chrome" });
  try {
    const page = await browser.newPage({ userAgent });
    const response = await page.goto(url, { waitUntil: "networkidle", timeout: 60000 });
    await page.waitForTimeout(800);
    process.stdout.write(JSON.stringify({ status: response ? response.status() : 0, url: page.url(), html: await page.content() }));
  } finally {
    await browser.close();
  }
})().catch((error) => {
  process.stderr.write(String(error && error.stack ? error.stack : error));
  process.exit(1);
});
