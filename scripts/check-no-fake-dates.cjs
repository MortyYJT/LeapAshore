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

const SELF = "scripts/check-no-fake-dates.cjs";

const files = execFileSync("git", ["ls-files", "api", "scripts"], { encoding: "utf8" })
  .split("\n")
  .filter((f) => /\.(py|json|cjs)$/.test(f))
  .filter((f) => f !== SELF);

// `verified_at` is written with the field name directly before the colon or equals sign, optionally
// closed by a quote when the key itself was quoted: verified_at="…", 'verified_at': …, and the JSON
// form "verified_at": "…". The JSON form is what seed data uses, so a trailing quote must be allowed.
//
// A date literal is either an ISO date (quoted or bare) or a constructor call. The quoted forms are
// tried before the bare one, because a bare pattern would otherwise match the year alone and stop
// without retrying the longer parse. The bare form is delimited so that `2026-07-14` inside a longer
// token is not mistaken for a date.
const FAKE_DATE =
  /verified_at["']?\s*[:=]\s*(?:"\d{4}-\d{2}-\d{2}"|'\d{4}-\d{2}-\d{2}'|date(?:time)?\s*\(\s*\d{4}\s*,|\d{4}-\d{2}-\d{2}(?![\d-]))/;

const offenders = [];
for (const file of files) {
  const text = readFileSync(file, "utf8");
  text.split("\n").forEach((line, i) => {
    if (FAKE_DATE.test(line)) {
      offenders.push(`${file}:${i + 1}`);
    }
  });
}

if (offenders.length) {
  console.error("硬编码的核验日期:", offenders.join(", "));
  process.exit(1);
}
console.log("未发现硬编码的核验日期");
