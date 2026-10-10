// Shared Playwright loader for the browser scripts in this directory.
//
// `@playwright/test` is a devDependency of `web/`, so `make install` puts it in `web/node_modules`.
// It is resolved from there rather than from this directory, because the repository root has no
// package.json of its own. Set PLAYWRIGHT_PATH to load a different copy instead (a module name or a
// path to the package directory).
//
// Only the npm package is installed this way; the browser binaries are not. If Chromium is missing,
// run `npx playwright install chromium` inside `web/`.

const path = require("path");

const WEB = path.resolve(__dirname, "..", "web");

function resolvePlaywright() {
  if (process.env.PLAYWRIGHT_PATH) return process.env.PLAYWRIGHT_PATH;
  try {
    return require.resolve("@playwright/test", { paths: [WEB] });
  } catch {
    throw new Error(
      "@playwright/test is not installed in web/node_modules. Run `make install`, " +
        "or point PLAYWRIGHT_PATH at an existing copy.",
    );
  }
}

module.exports = require(resolvePlaywright());
