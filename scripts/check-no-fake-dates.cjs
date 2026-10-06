#!/usr/bin/env node
// Fails when a verification date is hardcoded anywhere in the source or seed data.
//
// The previous implementation shipped verified_at = "2026-07-14" as a default, which made every
// record look checked. Verification dates must only ever come from a human writing to the database.
const { readFileSync } = require("node:fs");
const { execFileSync } = require("node:child_process");

const files = execFileSync("git", ["ls-files", "api", "scripts"], { encoding: "utf8" })
  .split("\n")
  .filter((f) => /\.(py|json|cjs)$/.test(f));

const offenders = [];
for (const file of files) {
  const text = readFileSync(file, "utf8");
  text.split("\n").forEach((line, i) => {
    if (/verified_at\s*[:=]\s*["']\d{4}-\d{2}-\d{2}/.test(line)) {
      offenders.push(`${file}:${i + 1}`);
    }
  });
}

if (offenders.length) {
  console.error("硬编码的核验日期:", offenders.join(", "));
  process.exit(1);
}
console.log("未发现硬编码的核验日期");
