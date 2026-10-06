#!/usr/bin/env node
// Fails when a verification date is hardcoded anywhere in the source or seed data.
//
// The previous implementation shipped a fixed verification date as a default, which made every
// record look checked. Verification dates must only ever come from a human writing to the database.
//
// This script is skipped by its own scan: it has to spell out the field name and the date shapes it
// looks for, and that description must not read as an offence.
const { readFileSync } = require("node:fs");
const { execFileSync } = require("node:child_process");
const { join } = require("node:path");

const SELF = "scripts/check-no-fake-dates.cjs";

// The field name plus a literal, in any of the shapes a regression takes:
//
//   1. directly after `:`/`=` — a kwarg, a quoted JSON seed key, or a bare annotation
//   2. after an annotation, e.g. `verified_at: str = "…"` or `Mapped[datetime] = Column(…, "…")`
//   3. after a `default=` / `server_default=` keyword further along the same statement
//   4. the same, when the call is wrapped and the keyword lands on the following line
//
// Branches 3 and 4 matter because the gap in front of the literal is what the old one-token regex
// missed: it required the date to sit immediately after the field name, so every real reintroduction
// (`verified_at: str = "…"`, `server_default=sa.text("…")`) passed the guard it was written for.
const DATE = /(?:"\d{4}-\d{2}-\d{2}"|'\d{4}-\d{2}-\d{2}'|date(?:time)?\s*\(\s*\d{4}\s*,|(?<![\d-])\d{4}-\d{2}-\d{2}(?![\d-]))/;

const TEMPLATES = [
  String.raw`\bverified_at["']?[ \t]*[:=][ \t]*%DATE%`,
  String.raw`\bverified_at["']?[ \t]*[:=][ \t]*[^=;"'\n]{0,60}?[ \t]*=[ \t]*%DATE%`,
  String.raw`\bverified_at["']?[ \t]*[:=][^\n]*?(?:default|server_default)[ \t]*=[^\n]*?%DATE%`,
  String.raw`\bverified_at["']?[ \t]*[:=][^\n]*\n[^\n]*?(?:default|server_default)[ \t]*=[^\n]*?%DATE%`,
];

// The literal lives in one place, so the alternation cannot leak out and swallow the branch that
// embeds it. `test()` is used below, so no global flag: a stateful `lastIndex` would skip lines.
const FAKE_DATE = new RegExp(
  TEMPLATES.map((t) => `(?:${t.replace("%DATE%", DATE.source)})`).join("|"),
);

// A comment cannot hardcode a value, and prose about the field trips a keyword-based pattern, so
// comments are blanked before matching. String literals are kept verbatim: a `#` inside one is not a
// comment, and the quotes around a literal are part of the shape this guard has to recognise. Every
// character is replaced by a space of the same width, so line numbers and layout survive.
function stripComments(text) {
  const out = text.split("");
  let i = 0;
  const blank = (from, to) => {
    for (let k = from; k < to; k += 1) {
      if (out[k] !== "\n") out[k] = " ";
    }
  };
  while (i < text.length) {
    const c = text[i];
    const triple = text.slice(i, i + 3);
    if (triple === '"""' || triple === "'''") {
      const end = text.indexOf(triple, i + 3);
      i = end === -1 ? text.length : end + 3;
      continue;
    }
    if (c === '"' || c === "'") {
      i += 1;
      while (i < text.length && text[i] !== c) {
        i += text[i] === "\\" ? 2 : 1;
      }
      i += 1;
      continue;
    }
    if (c === "#") {
      const end = text.indexOf("\n", i);
      blank(i, end === -1 ? text.length : end);
      i = end === -1 ? text.length : end;
      continue;
    }
    i += 1;
  }
  return out.join("");
}

// Fail loudly rather than silently passing when the scan has nothing to look at. `git ls-files`
// resolves its pathspecs against the process cwd, so without a root it would list nothing when the
// guard is run from `api/` and report success over an empty list. The root makes the scan identical
// from any directory, and the floor catches a list that is non-empty but still implausibly short.
const MINIMUM_FILES = 10;

let files = [];
let root = "";
try {
  root = execFileSync("git", ["rev-parse", "--show-toplevel"], { encoding: "utf8" }).trim();
  files = execFileSync("git", ["-C", root, "ls-files", "api", "scripts"], { encoding: "utf8" })
    .split("\n")
    .filter((f) => /\.(py|json|cjs)$/.test(f))
    .filter((f) => f !== SELF);
} catch (error) {
  console.error("核验日期检查无法运行:", String(error.message).split("\n")[0]);
  process.exit(1);
}

if (files.length < MINIMUM_FILES) {
  console.error(
    `核验日期检查扫描的文件为空或过少（${files.length} 个，至少应为 ${MINIMUM_FILES} 个）：` +
      "请在仓库内运行 node scripts/check-no-fake-dates.cjs",
  );
  process.exit(1);
}

const offenders = new Set();
for (const file of files) {
  const lines = stripComments(readFileSync(join(root, file), "utf8")).split("\n");
  // A wrapped call spans two lines, so the pattern is tested over each adjacent pair as well as each
  // line on its own. The window starts at `i === 0 ? 0 : i - 1`, so a match at window offset `p`
  // lands on line `start + newlinesBefore(p)`, and every offence is reported where the match begins.
  for (let i = 0; i < lines.length; i += 1) {
    const start = i === 0 ? 0 : i - 1;
    const window = lines.slice(start, i + 1).join("\n");
    const match = FAKE_DATE.exec(window);
    if (!match) continue;
    const before = window.slice(0, match.index).split("\n").length - 1;
    offenders.add(`${file}:${start + before + 1}`);
  }
}

if (offenders.size) {
  console.error("硬编码的核验日期:", [...offenders].join(", "));
  process.exit(1);
}
console.log("未发现硬编码的核验日期");
