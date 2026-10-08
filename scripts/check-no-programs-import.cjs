#!/usr/bin/env node
// Fails when a component or a page renders from `web/lib/programs.ts` instead of the served catalogue.
//
// M2d moved `HomeView` and `FlowView` off the constants array: a program the array does not carry used
// to render as its bare slug, and the server has been sending the program with every portfolio row since
// M2c. Nothing binds that any more. The walkthrough's two checks compare the page against the server's
// own answer, and the constants and the seeded catalogue agree on all six programs — the array *is* what
// the seed was transcribed from — so putting a `PROGRAMS.find(...)` back into a view keeps every unit
// test and the whole walkthrough green while the slug bug returns. Measured during the M2d review: with
// the lookup restored to `HomeView` and no other change, the walkthrough's own M2d check still printed
// 是.
//
// This is the cheaper, deterministic pin the review asked for: a static assertion about the imports of
// the two directories a browser can render, `web/components` and `web/app`. `web/lib` is deliberately
// not scanned — `scripts/verify-programs-mirror.cjs` reads the file through Node's type stripping and
// `eligibility.test.ts` uses it as a fixture, and both are legitimate readers of a file that is no
// longer a runtime catalogue. `web/lib/programs-source.ts` is the replacement.
//
// Usage: node scripts/check-no-programs-import.cjs

const { existsSync, readdirSync, readFileSync, statSync } = require("node:fs");
const { join, relative, resolve } = require("node:path");

const SELF = "scripts/check-no-programs-import.cjs";
const ROOT = resolve(__dirname, "..");
const CONSTANTS = "web/lib/programs.ts";

// The two directories the browser can render. Every file under them is scanned, `*.test.*` included: a
// test is not shipped, but it is also not a reason for a view's directory to import the array.
const DIRECTORIES = ["web/components", "web/app"];

// Import and require forms, and the re-export `export ... from "..."`, which is a read as well. The
// patterns look for a module specifier rather than for the path anywhere in the file, so the comments in
// `HomeView` and `FlowView` that name `web/lib/programs.ts` while explaining what they stopped doing do
// not trip this.
const SPECIFIERS = [
  /\bfrom\s*["']([^"']+)["']/g,
  /\brequire\(\s*["']([^"']+)["']\s*\)/g,
  /\bimport\(\s*["']([^"']+)["']\s*\)/g,
];

/**
 * Whether one module specifier resolves to `web/lib/programs.ts`.
 *
 * The spellings that reach the two scanned directories are `@/lib/programs` and a relative
 * `./programs` / `../lib/programs`. The trailing `$` is what keeps `@/lib/programs-source` — the
 * replacement adapter, which every view may import — apart from the constants it replaced.
 */
function namesTheConstants(specifier) {
  return /^(?:@\/lib\/programs|(?:\.\.?\/)+lib\/programs|\.\.?\/programs)$/.test(
    specifier.replace(/\.tsx?$/, ""),
  );
}

/** Every source file under one directory, node_modules and dot-directories excluded. */
function sourceFiles(directory) {
  const files = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "node_modules" || entry.name.startsWith(".")) continue;
      files.push(...sourceFiles(path));
    } else if (entry.isFile() && /\.(?:ts|tsx|js|jsx|mjs|cjs)$/.test(entry.name)) {
      files.push(path);
    }
  }
  return files;
}

function verify(directories = DIRECTORIES) {
  const files = [];
  for (const directory of directories) {
    const absolute = resolve(ROOT, directory);
    // A guard that scanned nothing must never report an all-clear: a rename or a move would otherwise
    // turn this check into a no-op that still passes.
    if (!existsSync(absolute) || !statSync(absolute).isDirectory()) {
      throw new Error(`${directory} is not a directory, so there is nothing to scan`);
    }
    files.push(...sourceFiles(absolute));
  }
  if (files.length === 0) throw new Error(`no source files under ${directories.join(", ")}`);

  const problems = [];
  for (const file of files) {
    const text = readFileSync(file, "utf8");
    for (const pattern of SPECIFIERS) {
      pattern.lastIndex = 0;
      let match;
      while ((match = pattern.exec(text)) !== null) {
        if (namesTheConstants(match[1])) {
          problems.push({ file: relative(ROOT, file), specifier: match[1] });
        }
      }
    }
  }
  return { files: files.length, directories, problems };
}

function main() {
  const result = verify();
  if (result.problems.length > 0) {
    console.error("MISMATCH — a component or a page reads the frontend constants array as its data:");
    for (const problem of result.problems) {
      console.error(`  - ${problem.file} imports ${problem.specifier}`);
    }
    console.error(
      `\n${CONSTANTS} is the mirror guard's comparison target and a test fixture since M2d, not a ` +
        "runtime catalogue. A view that reads it renders a program the array does not carry as a bare " +
        "slug, which is the defect M2d removed; read the program the server serves instead, through " +
        "web/lib/programs-source.ts.",
    );
    return 1;
  }
  console.log(
    `OK — ${result.files} files under ${result.directories.join(" and ")} read none of ${CONSTANTS}`,
  );
  return 0;
}

module.exports = { verify, namesTheConstants, DIRECTORIES, CONSTANTS, SELF };

if (require.main === module) {
  try {
    process.exitCode = main();
  } catch (error) {
    console.error(`FAIL — ${error.message}`);
    process.exitCode = 1;
  }
}
