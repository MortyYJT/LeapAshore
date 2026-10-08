#!/usr/bin/env node
// Fails when a page the browser renders can reach `web/lib/programs.ts`, however many hops away.
//
// M2d moved `HomeView` and `FlowView` off the constants array: a program the array does not carry used
// to render as its bare slug, and the server has been sending the program with every portfolio row
// since M2c. Nothing binds that any more. The walkthrough's two checks compare the page against the
// server's own answer, and the constants and the seeded catalogue agree on all six programs — the
// array *is* what the seed was transcribed from — so putting a `PROGRAMS.find(...)` back into a view
// keeps every unit test and the whole walkthrough green while the slug bug returns. Measured during
// the M2d review: with the lookup restored to `HomeView` and no other change, the walkthrough's own
// M2d check still printed 是.
//
// The first version of this guard grepped the module specifiers of `web/components` and `web/app` for
// the constants' own path. The whole-branch review demonstrated it was bypassable one hop away, against
// the real browser, the real API and the real unit suite: a new `web/lib/program-lookup.ts` holding
// nothing but `import { PROGRAMS } from "./programs"` and the removed lookup, imported by `HomeView`
// instead of `@/lib/programs`, left this guard at exit 0, the walkthrough green, all 148 unit tests
// passing and `make test` green — the exact defect this batch removed, surviving its own guard. A
// specifier grep cannot see through a module that re-exports, and `web/lib` is exactly where a future
// author would put a shared lookup.
//
// So this is a reachability scan rather than a grep over two directories. It starts at the App Router's
// entry points (every source file under `web/app`, which is the set the browser can land on) and
// follows each module's `from` / `import` / `require` specifiers through the `@/` alias, relative paths
// and extension or `index` resolution. The guard fails when that walk lands on `web/lib/programs.ts`,
// and it names the chain it walked, so the reader sees the hop that did it.
//
// What this settles that a directory grep cannot: `web/lib/eligibility.test.ts` legitimately imports the
// constants as a fixture, and `scripts/verify-programs-mirror.cjs` reads the file through Node's type
// stripping. Neither is reachable from a page, so a reachability scan resolves them correctly where a
// scan of `web/lib` would have to special-case them, and a *new* legitimate reader under `web/lib` needs
// no exception either. `web/lib/programs-source.ts` is the replacement every view reads instead.
//
// Usage: node scripts/check-no-programs-import.cjs

const { existsSync, readdirSync, readFileSync, statSync } = require("node:fs");
const { dirname, join, relative, resolve } = require("node:path");

const SELF = "scripts/check-no-programs-import.cjs";
const ROOT = resolve(__dirname, "..");
const CONSTANTS = "web/lib/programs.ts";

// The directory the browser renders from. Every source file under it is an entry point: a page, a
// layout or a route handler added later is picked up without this list being edited, and a file nothing
// routes to yet is still treated as reachable, which is the safe direction for a guard.
const ENTRY_DIRECTORY = "web/app";

// The App Router files whose absence would mean the scan no longer starts where the review pinned it.
// A rename or a move has to fail the guard rather than quietly narrow what it walks.
const REQUIRED_ENTRIES = ["web/app/page.tsx", "web/app/layout.tsx"];

// The `@/*` alias from `web/tsconfig.json` (`"paths": { "@/*": ["./*"] }`), resolved against `web/`.
const ALIAS_PREFIX = "@/";
const ALIAS_ROOT = resolve(ROOT, "web");

// The extensions a specifier may be resolved by, in the order TypeScript resolves them. `.json` is a
// real import here (`resolveJsonModule` is on), so it is resolved like the rest, but it is not parsed
// for further specifiers.
const SOURCE_EXTENSIONS = [".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"];
const RESOLVABLE_EXTENSIONS = [...SOURCE_EXTENSIONS, ".json"];

// Import forms that create a reachability edge: `import x from "m"`, `export ... from "m"`, a bare
// side-effect `import "m"`, `require("m")` and a dynamic `import("m")`. Each pattern captures a module
// specifier rather than the path anywhere in a file, so the comments in `HomeView` and `FlowView` that
// name `web/lib/programs.ts` while explaining what they stopped doing do not trip this.
const SPECIFIERS = [
  /\bfrom\s*["']([^"']+)["']/g,
  /\bimport\s*["']([^"']+)["']/g,
  /\bimport\s*\(\s*["']([^"']+)["']\s*\)/g,
  /\brequire\(\s*["']([^"']+)["']\s*\)/g,
];

/** Whether a path is an existing file, so a missing one is an answer rather than a throw. */
function isFile(path) {
  return existsSync(path) && statSync(path).isFile();
}

/** Whether a resolved file is one this walk parses for further specifiers. */
function isParsable(path) {
  return SOURCE_EXTENSIONS.some((extension) => path.endsWith(extension));
}

/**
 * The file one module specifier names, or `null` when this side cannot resolve it.
 *
 * `@/...` resolves against `web/`, exactly as the alias in `web/tsconfig.json` does; a specifier
 * starting with `.` resolves against the importing file's own directory. Anything else — a bare
 * `react`, `next/link`, `node:fs` — is a package or a builtin, which is not a file in this tree and so
 * is not an edge this walk follows.
 *
 * Resolution tries the path as written first (an explicit `./programs.ts`, which
 * `allowImportingTsExtensions` permits and `eligibility.test.ts` uses), then each extension, then an
 * `index` file inside a directory. A specifier that names nothing is therefore not an edge rather than
 * a guess.
 */
function resolveSpecifier(specifier, fromFile) {
  let base;
  if (specifier.startsWith(ALIAS_PREFIX)) {
    base = resolve(ALIAS_ROOT, specifier.slice(ALIAS_PREFIX.length));
  } else if (/^\.\.?(?:\/|$)/.test(specifier)) {
    base = resolve(dirname(fromFile), specifier);
  } else {
    return null;
  }

  if (isFile(base)) return base;
  for (const extension of RESOLVABLE_EXTENSIONS) {
    if (isFile(base + extension)) return base + extension;
  }
  for (const extension of RESOLVABLE_EXTENSIONS) {
    const index = join(base, `index${extension}`);
    if (isFile(index)) return index;
  }
  return null;
}

/** Every module specifier a source file names, in the order they appear. */
function specifiersIn(text) {
  const found = [];
  for (const pattern of SPECIFIERS) {
    pattern.lastIndex = 0;
    let match;
    while ((match = pattern.exec(text)) !== null) found.push(match[1]);
  }
  return found;
}

/** Every source file under one directory, node_modules and dot-directories excluded. */
function sourceFiles(directory) {
  const files = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "node_modules" || entry.name.startsWith(".")) continue;
      files.push(...sourceFiles(path));
    } else if (entry.isFile() && isParsable(entry.name)) {
      files.push(path);
    }
  }
  return files;
}

/**
 * The entry points the walk starts from, or a refusal when there is nothing sensible to walk.
 *
 * A guard that scanned nothing must never report an all-clear: a rename or a move would otherwise turn
 * this check into a no-op that still passes. So a missing `web/app`, an absent entry file and a
 * directory with no source files under it are each a failure rather than a pass.
 */
function entryPoints() {
  const directory = resolve(ROOT, ENTRY_DIRECTORY);
  if (!existsSync(directory) || !statSync(directory).isDirectory()) {
    throw new Error(`${ENTRY_DIRECTORY} is not a directory, so there is nothing to scan`);
  }
  for (const required of REQUIRED_ENTRIES) {
    const absolute = resolve(ROOT, required);
    if (!isFile(absolute)) {
      throw new Error(`${required} is not a file, so the scan has no entry point`);
    }
  }
  const files = sourceFiles(directory);
  if (files.length === 0) throw new Error(`no source files under ${ENTRY_DIRECTORY}`);
  return files;
}

/**
 * Every module reachable from the entry points, and the chains that reach the constants.
 *
 * Breadth-first over the import graph, with a visited set so a cycle (or a diamond) is walked once. The
 * chain travels with the file rather than being rebuilt afterwards, because the point of the failure
 * message is the hop that made the constants reachable, not merely that they are.
 */
function walk(entries) {
  const target = resolve(ROOT, CONSTANTS);
  const visited = new Set();
  const chains = [];
  const queue = entries.map((entry) => ({ file: entry, chain: [relative(ROOT, entry)] }));

  while (queue.length > 0) {
    const { file, chain } = queue.shift();
    if (visited.has(file)) continue;
    visited.add(file);
    if (file === target) {
      chains.push(chain);
      continue;
    }
    if (!isParsable(file)) continue;

    for (const specifier of specifiersIn(readFileSync(file, "utf8"))) {
      const resolved = resolveSpecifier(specifier, file);
      if (resolved === null || visited.has(resolved)) continue;
      queue.push({
        file: resolved,
        chain: [...chain, `${relative(ROOT, resolved)} (via "${specifier}")`],
      });
    }
  }
  return { modules: visited.size, chains };
}

function verify(entries = entryPoints()) {
  // The same refusal the entry-point scan makes, restated for a caller that hands this function its own
  // list: a walk with no start and a walk that reaches nothing are both "the guard checked nothing",
  // and neither may be reported as an all-clear.
  if (entries.length === 0) {
    throw new Error(`no entry points under ${ENTRY_DIRECTORY}, so there is nothing to scan`);
  }
  const { modules, chains } = walk(entries);
  if (modules === 0) throw new Error(`the scan reached no module under ${ENTRY_DIRECTORY}`);
  return {
    modules,
    entryPoints: entries.map((entry) => relative(ROOT, entry)),
    problems: chains.map((chain) => chain.join(" → ")),
  };
}

function main() {
  const result = verify();
  if (result.problems.length > 0) {
    console.error(`MISMATCH — ${CONSTANTS} is reachable from the pages the browser renders:`);
    for (const problem of result.problems) console.error(`  - ${problem}`);
    console.error(
      `\n${CONSTANTS} is the mirror guard's comparison target and a test fixture since M2d, not a ` +
        "runtime catalogue. A page that reaches it renders a program the array does not carry as a " +
        "bare slug, which is the defect M2d removed, and a lookup one re-export away is that same " +
        "defect through a different door. Read the program the server serves instead, through " +
        "web/lib/programs-source.ts.",
    );
    return 1;
  }
  console.log(
    `OK — ${result.entryPoints.length} entry points and ${result.modules} reachable modules under ` +
      `${ENTRY_DIRECTORY} reach none of ${CONSTANTS}`,
  );
  return 0;
}

module.exports = {
  verify,
  resolveSpecifier,
  entryPoints,
  ENTRY_DIRECTORY,
  REQUIRED_ENTRIES,
  CONSTANTS,
  SELF,
};

if (require.main === module) {
  try {
    process.exitCode = main();
  } catch (error) {
    console.error(`FAIL — ${error.message}`);
    process.exitCode = 1;
  }
}
