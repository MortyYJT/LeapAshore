#!/usr/bin/env node
// Fails when the seeded roadmap definition stops mirroring the frontend data it was transcribed from.
//
// The seed in api/app/seed_roadmap.py exists only to copy web/lib/roadmap.ts into the two roadmap
// tables until the annotation stage replaces both with reviewed data. Nothing used to bind the two:
// a future edit could move selection's 330 to 33, reword a material's title or drop 作品集 and the
// whole suite stayed green. This script is that binding.
//
// It compares values, never shape, in up to three directions at once:
//
//   web/lib/roadmap.ts  <->  scripts/roadmap-definition.snapshot.json  <->  the JSON dump a pytest
//                                                                          writes from the database
//
// The TypeScript is read through Node's own type stripping, so the expected values come from the
// source of truth rather than from a parser or a second hand-copied table that could drift with the
// first. The committed snapshot is what turns a silent edit of roadmap.ts into a red build, and the
// dump is what catches a seed, a model or a migration that no longer stores what it read. Without a
// dump the guard still runs TypeScript against snapshot, so it stays useful in an environment
// without the database container.
//
// Every phase is compared on its key, title, subtitle, offset and order, and every material on its
// key, phase, title, detail, appliesTo and order. The order is carried by `sort_order`, which the
// frontend expresses as array position: the index is the translation, so a reordered array is a
// divergence, not a formatting change. `null` and the empty string are kept apart, because a phase
// with no description and a phase whose description was blanked are not the same phase.
//
// The visa phase and its two materials are excluded on purpose. They are authored in
// api/app/seed_roadmap.py, not transcribed: web/lib/roadmap.ts has no visa phase, so there is no
// value on the TypeScript side to compare them against. api/tests/test_seed_roadmap.py covers them
// instead, and this guard fails if the frontend ever grows a visa phase of its own, because then the
// exclusion below has stopped describing the tree.
//
// Usage:
//   node scripts/verify-roadmap-mirror.cjs [--ts <path>] [--snapshot <path>] [<database-dump.json>]
//   node scripts/verify-roadmap-mirror.cjs [--ts <path>] [--snapshot <path>] --write-snapshot
//
// The dump is produced by api/tests/test_seed_roadmap.py, which seeds the database and reads the rows
// back. --write-snapshot regenerates the committed snapshot from web/lib/roadmap.ts; run it only
// after the frontend data itself changed on purpose.

const { execFileSync } = require("node:child_process");
const { readFileSync, writeFileSync } = require("node:fs");
const { resolve } = require("node:path");

const SELF = "scripts/verify-roadmap-mirror.cjs";
const TS_SOURCE = "web/lib/roadmap.ts";
const SNAPSHOT = "scripts/roadmap-definition.snapshot.json";

// The one phase this guard does not compare, for the reason given in the header.
const AUTHORED_PHASE = "visa";

// The field-by-field mapping. Both sides of the comparison are normalised into these names, and the
// report names the field with them. The frontend calls a phase's id `id` and its description
// `detail`; the tables call them `key` and `subtitle`, so the mapping is spelled out in
// fromTypeScript rather than guessed from the names.
const PHASE_FIELDS = ["key", "title", "subtitle", "offset_days", "sort_order"];
const MATERIAL_FIELDS = ["key", "phase", "title", "detail", "applies_to", "sort_order"];

function usage() {
  return (
    `usage: node ${SELF} [--ts <path>] [--snapshot <path>] [<database-dump.json>]\n` +
    `       node ${SELF} [--ts <path>] [--snapshot <path>] --write-snapshot`
  );
}

function parseArgs(argv) {
  const options = { ts: TS_SOURCE, snapshot: SNAPSHOT, dump: null, writeSnapshot: false };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--ts") {
      options.ts = argv[(i += 1)];
    } else if (arg === "--snapshot") {
      options.snapshot = argv[(i += 1)];
    } else if (arg === "--write-snapshot") {
      options.writeSnapshot = true;
    } else if (arg.startsWith("-")) {
      throw new Error(`unknown option ${arg}\n${usage()}`);
    } else if (options.dump === null) {
      options.dump = arg;
    } else {
      throw new Error(`unexpected extra argument ${arg}\n${usage()}`);
    }
  }
  return options;
}

function normaliseText(value) {
  return value === null || value === undefined ? "<null>" : String(value);
}

// The offsets and the orders are integers in both the TypeScript and the columns. A string that
// looks like a number is not the same value, so it is rejected as malformed rather than coerced.
function normaliseInteger(value) {
  if (typeof value !== "number" || !Number.isInteger(value)) {
    throw new Error(`expected an integer, got ${JSON.stringify(value)}`);
  }
  return String(value);
}

const PHASE_NORMALISERS = {
  key: normaliseText,
  title: normaliseText,
  subtitle: normaliseText,
  offset_days: normaliseInteger,
  sort_order: normaliseInteger,
};

const MATERIAL_NORMALISERS = {
  key: normaliseText,
  phase: normaliseText,
  title: normaliseText,
  detail: normaliseText,
  applies_to: normaliseText,
  sort_order: normaliseInteger,
};

// One normalised record per phase or material, keyed by the primary key. The TypeScript identifies a
// phase by `id` and a material by `id`; the snapshot and the tables call both `key`, and the two
// spellings have to hold the same value, so nothing is keyed by a translated name in between.
function indexRows(rows, fields, label, kind) {
  const indexed = new Map();
  for (const row of rows) {
    if (!row || typeof row !== "object") {
      throw new Error(`${label}: an empty ${kind} record`);
    }
    const key = row.key;
    if (typeof key !== "string" || key === "") {
      throw new Error(`${label}: a ${kind} has no usable key: ${JSON.stringify(row)}`);
    }
    if (indexed.has(key)) throw new Error(`${label}: duplicate ${kind} key ${key}`);
    const value = {};
    for (const field of fields) {
      if (!(field in row)) throw new Error(`${label}: ${key} is missing the field ${field}`);
      value[field] = row[field];
    }
    indexed.set(key, value);
  }
  return indexed;
}

// The TypeScript is loaded through Node's own TypeScript support, so this script never parses it.
// A bare `require` cannot reach a `.ts` module, so a child process imports it and prints JSON. The
// translation from the frontend's names to the columns happens here and nowhere else.
function loadTypeScriptRoadmap(tsPath) {
  const bootstrap = `
    const mod = await import(process.argv[1]);
    const phaseDefs = mod.PHASE_DEFS;
    const materials = mod.MATERIALS;
    if (!Array.isArray(phaseDefs)) {
      throw new Error(process.argv[1] + " no longer exports a PHASE_DEFS array");
    }
    if (!materials || typeof materials !== "object") {
      throw new Error(process.argv[1] + " no longer exports a MATERIALS record");
    }
    const phases = phaseDefs.map((def, index) => ({
      key: def.id,
      title: def.title,
      subtitle: def.detail,
      offset_days: def.offsetDays,
      sort_order: index,
    }));
    const flat = [];
    for (const [phase, items] of Object.entries(materials)) {
      if (!Array.isArray(items)) {
        throw new Error("MATERIALS." + phase + " is not an array");
      }
      items.forEach((item, index) => {
        flat.push({
          key: item.id,
          phase,
          title: item.label,
          detail: item.detail,
          applies_to: item.appliesTo,
          sort_order: index,
        });
      });
    }
    process.stdout.write(JSON.stringify({ phases, materials: flat }));
  `;
  let stdout;
  try {
    stdout = execFileSync(
      process.execPath,
      ["--experimental-strip-types", "--input-type=module", "-e", bootstrap, tsPath],
      { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"], maxBuffer: 16 * 1024 * 1024 },
    );
  } catch (error) {
    const stderr = error.stderr ? error.stderr.toString().trim() : error.message;
    throw new Error(
      `could not import ${tsPath} with Node's TypeScript support, so no value can be checked:\n${stderr}`,
    );
  }
  let parsed;
  try {
    parsed = JSON.parse(stdout);
  } catch {
    throw new Error(`importing ${tsPath} did not produce JSON:\n${stdout.slice(0, 2000)}`);
  }
  if (!Array.isArray(parsed.phases) || !Array.isArray(parsed.materials)) {
    throw new Error(`importing ${tsPath} produced no phase or material list`);
  }
  const phases = indexRows(parsed.phases, PHASE_FIELDS, tsPath, "phase");
  const materials = indexRows(parsed.materials, MATERIAL_FIELDS, tsPath, "material");
  if (phases.size === 0) {
    throw new Error(`${tsPath} exports an empty PHASE_DEFS array, so there is nothing to check`);
  }
  if (materials.size === 0) {
    throw new Error(`${tsPath} exports an empty MATERIALS record, so there is nothing to check`);
  }
  // The frontend growing a visa phase would make the exclusion in this guard stale, and a stale
  // exclusion is the silent kind of failure: it would skip real values and still report success.
  if (phases.has(AUTHORED_PHASE) || [...materials.values()].some((m) => m.phase === AUTHORED_PHASE)) {
    throw new Error(
      `${tsPath} now defines the ${AUTHORED_PHASE} phase, which this guard excludes as ` +
        `authored data in api/app/seed_roadmap.py — remove the exclusion before it hides a divergence`,
    );
  }
  return { phases, materials };
}

// The snapshot is generated from the TypeScript itself, never hand-written, so it can only ever be a
// copy of the source of truth rather than a second opinion about it.
function writeSnapshot(snapshotPath, roadmap) {
  const document = {
    $comment:
      `Generated from ${TS_SOURCE} by ${SELF} --write-snapshot. Do not edit by hand: change ` +
      `${TS_SOURCE} and regenerate, or fix api/app/seed_roadmap.py when only the seed is wrong. ` +
      `The ${AUTHORED_PHASE} phase and its materials are authored in the seed and have no ` +
      `counterpart here.`,
    phases: [...roadmap.phases.values()],
    materials: [...roadmap.materials.values()],
  };
  writeFileSync(snapshotPath, `${JSON.stringify(document, null, 2)}\n`, "utf8");
  console.log(
    `wrote ${document.phases.length} phases and ${document.materials.length} materials to ${snapshotPath}`,
  );
}

function readDocument(path, kind) {
  let parsed;
  try {
    parsed = JSON.parse(readFileSync(path, "utf8"));
  } catch (error) {
    throw new Error(`could not read the ${kind} ${path}: ${error.message}`);
  }
  if (!parsed || !Array.isArray(parsed.phases) || !Array.isArray(parsed.materials)) {
    throw new Error(`${path} has no "phases" and "materials" arrays`);
  }
  return parsed;
}

function loadSnapshot(snapshotPath) {
  const parsed = readDocument(snapshotPath, "committed snapshot");
  return {
    phases: indexRows(parsed.phases, PHASE_FIELDS, snapshotPath, "phase"),
    materials: indexRows(parsed.materials, MATERIAL_FIELDS, snapshotPath, "material"),
  };
}

// The dump is the only representation that carries the authored rows, because it is the only one
// read out of the seeded tables. They are dropped here rather than compared, and how many were
// dropped is reported, so a dump that turns out to hold nothing else cannot pass as a clean run.
function loadDump(dumpPath) {
  const parsed = readDocument(dumpPath, "database dump");
  const keptPhases = parsed.phases.filter((row) => row.key !== AUTHORED_PHASE);
  const keptMaterials = parsed.materials.filter((row) => row.phase !== AUTHORED_PHASE);
  const dropped =
    parsed.phases.length - keptPhases.length + (parsed.materials.length - keptMaterials.length);
  return {
    phases: indexRows(keptPhases, PHASE_FIELDS, dumpPath, "phase"),
    materials: indexRows(keptMaterials, MATERIAL_FIELDS, dumpPath, "material"),
    dropped,
  };
}

function compare(source, sourceLabel, other, otherLabel, fields, normalisers, kind, problems) {
  for (const key of source.keys()) {
    if (!other.has(key)) {
      problems.push(`${key}: ${kind} present in ${sourceLabel} but missing from ${otherLabel}`);
      continue;
    }
    const left = source.get(key);
    const right = other.get(key);
    for (const field of fields) {
      let a;
      let b;
      try {
        a = normalisers[field](left[field]);
        b = normalisers[field](right[field]);
      } catch (error) {
        problems.push(`${key}.${field}: ${error.message}`);
        continue;
      }
      if (a !== b) {
        problems.push(`${key}.${field}: ${sourceLabel} has ${a}, ${otherLabel} has ${b}`);
      }
    }
  }
  for (const key of other.keys()) {
    if (!source.has(key)) {
      problems.push(`${key}: ${kind} present in ${otherLabel} but missing from ${sourceLabel}`);
    }
  }
}

function comparePair(typescript, typescriptLabel, other, otherLabel, problems) {
  compare(
    typescript.phases,
    typescriptLabel,
    other.phases,
    otherLabel,
    PHASE_FIELDS,
    PHASE_NORMALISERS,
    "phase",
    problems,
  );
  compare(
    typescript.materials,
    typescriptLabel,
    other.materials,
    otherLabel,
    MATERIAL_FIELDS,
    MATERIAL_NORMALISERS,
    "material",
    problems,
  );
}

function verify(settings) {
  const tsPath = resolve(settings.ts || TS_SOURCE);
  const snapshotPath = resolve(settings.snapshot || SNAPSHOT);
  const dumpPath = settings.dump ? resolve(settings.dump) : null;

  const typescript = loadTypeScriptRoadmap(tsPath);
  if (settings.writeSnapshot) {
    writeSnapshot(snapshotPath, typescript);
    return { written: true, phases: typescript.phases.size, materials: typescript.materials.size, problems: [] };
  }

  const snapshot = loadSnapshot(snapshotPath);
  // The database dump is optional so the guard still binds the source of truth to the committed
  // snapshot in an environment without the database container. The pytest that owns the database
  // passes the dump in, which extends the binding down to the seeded tables.
  const database = dumpPath ? loadDump(dumpPath) : null;

  // A guard that scanned nothing must never report an all-clear. Every representation present has to
  // carry at least one phase and one material, and they all have to agree on how many of each.
  const counts = [
    [label(tsPath, TS_SOURCE), typescript.phases.size, typescript.materials.size],
    [label(snapshotPath, SNAPSHOT), snapshot.phases.size, snapshot.materials.size],
  ];
  if (database) {
    counts.push([
      label(dumpPath, "<database dump>"),
      database.phases.size,
      database.materials.size,
    ]);
  }
  const detail = counts.map(([name, p, m]) => `${name}: ${p} phases, ${m} materials`).join(", ");
  const empty = counts.filter(([, p, m]) => p === 0 || m === 0);
  if (empty.length > 0) {
    throw new Error(
      `found no definition to compare (${detail}) — the guard would otherwise pass on nothing`,
    );
  }
  const shapes = new Set(counts.map(([, p, m]) => `${p}/${m}`));
  if (shapes.size !== 1) {
    throw new Error(`the compared representations hold different definition sizes (${detail})`);
  }

  const problems = [];
  comparePair(typescript, label(tsPath, TS_SOURCE), snapshot, label(snapshotPath, SNAPSHOT), problems);
  if (database) {
    comparePair(
      typescript,
      label(tsPath, TS_SOURCE),
      database,
      label(dumpPath, "<database dump>"),
      problems,
    );
  }
  return {
    written: false,
    phases: typescript.phases.size,
    materials: typescript.materials.size,
    phaseKeys: [...typescript.phases.keys()],
    materialsPerPhase: [...typescript.phases.keys()].map((key) => [
      key,
      [...typescript.materials.values()].filter((m) => m.phase === key).length,
    ]),
    problems,
    withDatabase: Boolean(database),
    droppedAuthoredRows: database ? database.dropped : 0,
  };
}

function label(absolute, fallback) {
  return absolute === resolve(fallback) ? fallback : absolute;
}

function main(argv) {
  const options = parseArgs(argv);
  const result = verify(options);
  if (result.written) return 0;

  if (result.problems.length > 0) {
    console.error("MISMATCH — the seed no longer mirrors its source of truth:");
    for (const problem of result.problems) console.error(`  - ${problem}`);
    console.error(
      `\napi/app/seed_roadmap.py must be changed to match ${TS_SOURCE}. Never the other way round.`,
    );
    return 1;
  }

  for (const [key, count] of result.materialsPerPhase) {
    console.log(
      `${key.padEnd(12)} ${count} material(s), ${PHASE_FIELDS.length}/${PHASE_FIELDS.length} phase ` +
        `fields and ${MATERIAL_FIELDS.length}/${MATERIAL_FIELDS.length} material fields match`,
    );
  }
  const scope = result.withDatabase
    ? `${SNAPSHOT} and the database dump`
    : `${SNAPSHOT} (no database dump was given)`;
  console.log(
    `\nOK — ${result.phases} phases and ${result.materials} materials match ${TS_SOURCE} field by ` +
      `field, through ${scope}`,
  );
  if (result.withDatabase) {
    console.log(
      `   ${result.droppedAuthoredRows} authored row(s) under the ${AUTHORED_PHASE} phase were ` +
        `excluded: they live only in api/app/seed_roadmap.py`,
    );
  }
  return 0;
}

module.exports = {
  verify,
  PHASE_FIELDS,
  MATERIAL_FIELDS,
  TS_SOURCE,
  SNAPSHOT,
  AUTHORED_PHASE,
  resolve,
};

if (require.main === module) {
  try {
    process.exitCode = main(process.argv.slice(2));
  } catch (error) {
    console.error(`FAIL — ${error.message}`);
    process.exitCode = 1;
  }
}
