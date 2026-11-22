// Tests for which roadmap steps offer a file upload, and what a step's row shows for files.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { FILE_STEPS, producesFile, stepFiles } from "./roadmap-files.ts";
import { MATERIALS } from "./roadmap.ts";

const BUILT_IN = Object.values(MATERIALS).flat();
// The visa phase is authored in the seed and has no entry in `MATERIALS`; its keys are read from there.
const SEED = readFileSync(new URL("../../api/app/seed_roadmap.py", import.meta.url), "utf8");
const SEEDED_KEYS = [...SEED.matchAll(/"key": "([a-z]+-[a-z-]+)"/g)].map((match) => match[1]);

test("every classified key is a step the seed serves", () => {
  assert.equal(SEEDED_KEYS.length, 33);
  for (const key of Object.keys(FILE_STEPS)) assert.ok(SEEDED_KEYS.includes(key), key);
  for (const item of BUILT_IN) assert.ok(SEEDED_KEYS.includes(item.id), item.id);
});

test("the steps that are things to do are tick-only", () => {
  for (const key of ["sel-goal", "sel-shortlist", "sel-check", "sel-portfolio", "sel-primary"]) assert.equal(producesFile(key), false, key);
  for (const key of ["lang-requirement", "lang-book", "lang-send", "sub-account", "sub-form", "sub-upload", "sub-fee"]) assert.equal(producesFile(key), false, key);
  for (const key of ["dec-follow", "dec-interview", "dec-deposit"]) assert.equal(producesFile(key), false, key);
});

test("the steps that leave a document offer the upload", () => {
  const filed = SEEDED_KEYS.filter(producesFile).sort();
  assert.deepEqual(filed, Object.keys(FILE_STEPS).sort());
  assert.equal(filed.length, 18);
  for (const key of ["aca-transcript", "aca-passport", "lang-score", "spe-cv", "spe-ps", "spe-ref", "sub-receipt", "dec-compare", "dec-coe", "visa-gs-responses", "visa-gs-evidence"]) assert.ok(producesFile(key), key);
});

test("a key nobody classified is tick-only, and inherited names are not keys", () => {
  assert.equal(producesFile("later-step"), false);
  assert.equal(producesFile("toString"), false);
});

const LIBRARY = [
  { title: "second.pdf", taskId: "task-1", createdAt: "2026-11-02T00:00:00Z" },
  { title: "first.pdf", taskId: "task-1", createdAt: "2026-11-01T00:00:00Z" },
  { title: "other.pdf", taskId: "task-2", createdAt: "2026-11-01T00:00:00Z" },
  { title: "loose.pdf", taskId: null, createdAt: "2026-11-01T00:00:00Z" },
];

test("a file step lists its own files, oldest first, and offers the upload", () => {
  assert.deepEqual(stepFiles("aca-transcript", "task-1", LIBRARY), { upload: true, attached: ["first.pdf", "second.pdf"] });
});

test("a tick-only step keeps the files already attached to it, without the upload", () => {
  assert.deepEqual(stepFiles("sel-goal", "task-2", LIBRARY), { upload: false, attached: ["other.pdf"] });
  assert.deepEqual(stepFiles("sel-goal", "task-9", LIBRARY), { upload: false, attached: [] });
});

test("a step whose row is not written yet claims no file, not the unattached ones", () => {
  assert.deepEqual(stepFiles("aca-transcript", null, LIBRARY), { upload: true, attached: [] });
});
