#!/usr/bin/env node
// Fails when the seeded catalogue stops mirroring the frontend data it was transcribed from.
//
// The seed in api/app/seed.py exists only to copy web/lib/programs.ts into tables until the
// annotation stage replaces both with reviewed data. Nothing used to bind the two: a future edit
// could change UQ's 71.4 to 5.0, drop a prerequisite or truncate a source url and the whole suite
// stayed green. This script is that binding.
//
// It compares values, never shape, in up to three directions at once:
//
//   web/lib/programs.ts  <->  scripts/seed-programs.snapshot.json  <->  the JSON dump a pytest
//                                                                      writes from the database
//
// The TypeScript is read through Node's own type stripping, so the expected values come from the
// source of truth rather than from a parser or a second hand-copied table that could drift with the
// first. The committed snapshot is what turns a silent edit of programs.ts or of the seed into a
// red build, and the dump is what catches a seed, a model or a migration that no longer stores what
// it read. Without a dump the guard still runs TypeScript against snapshot, so it stays useful in
// an environment without the database container.
//
// Every program is compared field by field: city, degree level, field, duration, both mark
// thresholds, the cognate flag, the English requirement, the official source url and the full
// prerequisite list in order. `null` and `0` are kept apart, because five programs publish no
// non-211 baseline and "unknown" must never read as "zero".
//
// Usage:
//   node scripts/verify-programs-mirror.cjs [--ts <path>] [--snapshot <path>] [<database-dump.json>]
//   node scripts/verify-programs-mirror.cjs [--ts <path>] [--snapshot <path>] --write-snapshot
//
// The dump is produced by api/tests/test_seed.py, which seeds the database and reads the rows back.
// --write-snapshot regenerates the committed snapshot from web/lib/programs.ts; run it only after
// the frontend data itself changed on purpose.

const { execFileSync } = require("node:child_process");
const { readFileSync, writeFileSync } = require("node:fs");
const { resolve } = require("node:path");

const SELF = "scripts/verify-programs-mirror.cjs";
const TS_SOURCE = "web/lib/programs.ts";
const SNAPSHOT = "scripts/seed-programs.snapshot.json";

// The rows are matched on the TypeScript `slug`, which is the identifier both sides agree on. The
// seed stores the longer ids the task brief fixed, and the frontend never reads a program id, so
// the two spellings are related here explicitly instead of guessed. A new program that appears in
// either file without an entry below is reported as unmatched rather than skipped.
const SLUG_ALIASES = {
  "unsw-master-it": "unsw-master-of-it",
  "usyd-master-cs": "usyd-master-cs",
  "monash-master-ai": "monash-master-ai",
  "monash-master-cs": "monash-master-cs",
  "uq-master-data-science": "uq-master-data-science",
  "uwa-master-it": "uwa-master-it",
};

// The field-by-field mapping. Both sides of the comparison are normalised into
// { city, degree_level, ... }, and the report names the field with these keys.
const FIELDS = [
  "city",
  "degree_level",
  "field",
  "duration",
  "minimum_mark",
  "non_211_minimum_mark",
  "requires_cognate",
  "english_requirement",
  "source_url",
  "prerequisites",
];

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

// Numbers always compare as fixed-point text. The columns are NUMERIC(5, 2) and the TypeScript
// carries plain numbers, so 71.4, "71.40" and Decimal("71.40") have to land on the same string.
function normaliseNumber(value) {
  if (typeof value === "number" && !Number.isFinite(value)) {
    throw new Error(`not a finite number: ${String(value)}`);
  }
  return Number(value).toFixed(2);
}

// Unknown stays unknown. Conflating a published baseline of zero with "no baseline published" is
// the exact mistake this guard is here to catch, so the two become different strings, not equal.
function normaliseMark(value) {
  if (value === null || value === undefined) return "<null>";
  return normaliseNumber(value);
}

function normaliseBool(value) {
  if (typeof value !== "boolean") {
    throw new Error(`expected a boolean, got ${JSON.stringify(value)}`);
  }
  return value ? "true" : "false";
}

function normaliseList(value) {
  if (!Array.isArray(value)) throw new Error(`expected an array, got ${JSON.stringify(value)}`);
  return JSON.stringify(value.map((item) => String(item)));
}

function normaliseText(value) {
  return value === null || value === undefined ? "<null>" : String(value);
}

// One normalised record per representation, keyed by the TypeScript slug. The TypeScript
// identifies a program by `slug`; the seed reuses the brief's longer ids for the same six rows, so
// the dump is re-keyed through an alias table on the way in.
const NORMALISERS = {
  city: normaliseText,
  degree_level: normaliseText,
  field: normaliseText,
  duration: normaliseText,
  minimum_mark: normaliseMark,
  non_211_minimum_mark: normaliseMark,
  requires_cognate: normaliseBool,
  english_requirement: normaliseText,
  source_url: normaliseText,
  prerequisites: normaliseList,
};

function fromTypeScript(rows, label) {
  const programs = new Map();
  for (const row of rows) {
    if (!row || typeof row.slug !== "string" || row.slug === "") {
      throw new Error(`${label}: a record has no usable slug: ${JSON.stringify(row)}`);
    }
    if (programs.has(row.slug)) throw new Error(`${label}: duplicate slug ${row.slug}`);
    programs.set(row.slug, {
      city: row.city,
      degree_level: row.degreeLevel,
      field: row.field,
      duration: row.duration,
      minimum_mark: row.minimumMark,
      non_211_minimum_mark: row.non211MinimumMark,
      requires_cognate: row.requiresCognate,
      english_requirement: row.englishRequirement,
      source_url: row.source && row.source.url,
      prerequisites: row.prerequisites,
    });
  }
  return programs;
}

function fromDump(rows, aliasIds) {
  const programs = new Map();
  const ids = new Set();
  for (const row of rows) {
    if (!row) throw new Error(`database dump: empty record`);
    const id = row.id;
    if (typeof id !== "string" || id === "") {
      throw new Error(`database dump: a record has no id: ${JSON.stringify(row)}`);
    }
    if (ids.has(id)) throw new Error(`database dump: duplicate id ${id}`);
    ids.add(id);
    const slug = aliasIds.href(id);
    const value = {};
    for (const field of FIELDS) {
      if (!(field in row)) throw new Error(`database dump: ${id} is missing the field ${field}`);
      value[field] = row[field];
    }
    programs.set(slug, value);
  }
  return programs;
}

function makeAliasLookup(label) {
  const byId = new Map(Object.entries(SLUG_ALIASES).map(([slug, id]) => [id, slug]));
  return {
    href(id) {
      const slug = byId.get(id);
      if (!slug) {
        throw new Error(
          `${label} holds the program id ${id}, which has no entry in SLUG_ALIASES in ${SELF}`,
        );
      }
      return slug;
    },
  };
}

// The TypeScript is loaded through Node's own TypeScript support, so this script never parses it.
// A bare `require` cannot reach a `.ts` module, so a child process imports it and prints JSON.
function loadTypeScriptPrograms(tsPath) {
  // The path is reported from the argument the child actually imported, so `--ts <other file>` does
  // not produce an error message naming web/lib/programs.ts.
  const bootstrap = `
    const mod = await import(process.argv[1]);
    if (!Array.isArray(mod.PROGRAMS)) {
      throw new Error(process.argv[1] + " no longer exports a PROGRAMS array");
    }
    process.stdout.write(JSON.stringify({ rows: mod.PROGRAMS.length, programs: mod.PROGRAMS }));
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
  if (typeof parsed.rows !== "number") {
    throw new Error(`importing ${tsPath} produced no row count`);
  }
  if (parsed.rows === 0) {
    throw new Error(`${tsPath} exports an empty PROGRAMS array, so there is nothing to check`);
  }
  return fromTypeScript(parsed.programs, tsPath);
}

// The snapshot is generated from the TypeScript itself, never hand-written, so it can only ever be
// a copy of the source of truth rather than a second opinion about it.
function writeSnapshot(snapshotPath, typescript) {
  const programs = [];
  for (const [slug, row] of typescript) {
    const id = SLUG_ALIASES[slug];
    const entry = { id };
    for (const field of FIELDS) entry[field] = row[field];
    programs.push(entry);
  }
  const document = {
    $comment:
      `Generated from ${TS_SOURCE} by ${SELF} --write-snapshot. Do not edit by hand: ` +
      `change ${TS_SOURCE} and regenerate, or fix api/app/seed.py when only the seed is wrong.`,
    programs,
  };
  writeFileSync(snapshotPath, `${JSON.stringify(document, null, 2)}\n`, "utf8");
  console.log(`wrote ${programs.length} programs to ${snapshotPath}`);
}

function loadSnapshot(snapshotPath) {
  let parsed;
  try {
    parsed = JSON.parse(readFileSync(snapshotPath, "utf8"));
  } catch (error) {
    throw new Error(`could not read the committed snapshot ${snapshotPath}: ${error.message}`);
  }
  if (!parsed || !Array.isArray(parsed.programs)) {
    throw new Error(`${snapshotPath} has no "programs" array`);
  }
  return fromDump(parsed.programs, makeAliasLookup(snapshotPath));
}

function loadDump(dumpPath) {
  let parsed;
  try {
    parsed = JSON.parse(readFileSync(dumpPath, "utf8"));
  } catch (error) {
    throw new Error(`could not read the database dump ${dumpPath}: ${error.message}`);
  }
  if (!parsed || !Array.isArray(parsed.programs)) {
    throw new Error(`${dumpPath} has no "programs" array`);
  }
  return fromDump(parsed.programs, makeAliasLookup(dumpPath));
}

function compare(source, sourceLabel, other, otherLabel, problems) {
  for (const slug of source.keys()) {
    if (!other.has(slug)) {
      problems.push(`${slug}: present in ${sourceLabel} but missing from ${otherLabel}`);
      continue;
    }
    const left = source.get(slug);
    const right = other.get(slug);
    for (const field of FIELDS) {
      let a;
      let b;
      try {
        a = NORMALISERS[field](left[field]);
        b = NORMALISERS[field](right[field]);
      } catch (error) {
        problems.push(`${slug}.${field}: ${error.message}`);
        continue;
      }
      if (a !== b) {
        problems.push(
          `${slug}.${field}: ${sourceLabel} has ${a}, ${otherLabel} has ${b}`,
        );
      }
    }
  }
  for (const slug of other.keys()) {
    if (!source.has(slug)) {
      problems.push(`${slug}: present in ${otherLabel} but missing from ${sourceLabel}`);
    }
  }
}

function verify(settings) {
  const tsPath = resolve(settings.ts || TS_SOURCE);
  const snapshotPath = resolve(settings.snapshot || SNAPSHOT);
  const dumpPath = settings.dump ? resolve(settings.dump) : null;

  const typescript = loadTypeScriptPrograms(tsPath);
  if (settings.writeSnapshot) {
    writeSnapshot(snapshotPath, typescript);
    return { written: true, programs: typescript.size, problems: [] };
  }

  const snapshot = loadSnapshot(snapshotPath);
  // The database dump is optional so the guard still binds the source of truth to the committed
  // snapshot in an environment without the database container. The pytest that owns the database
  // passes the dump in, which is what extends the binding down to the seeded tables.
  const database = dumpPath ? loadDump(dumpPath) : null;

  // A guard that scanned nothing must never report an all-clear. Every representation present has
  // to carry at least one program, and they all have to agree on how many.
  const counts = [
    [label(tsPath, TS_SOURCE), typescript.size],
    [label(snapshotPath, SNAPSHOT), snapshot.size],
  ];
  if (database) counts.push([label(dumpPath, "<database dump>"), database.size]);
  const empty = counts.filter(([, count]) => count === 0);
  if (empty.length > 0) {
    const detail = counts.map(([name, count]) => `${name}: ${count}`).join(", ");
    throw new Error(
      `found no programs to compare (${detail}) — the guard would otherwise pass on nothing`,
    );
  }
  const sizes = new Set(counts.map(([, count]) => count));
  if (sizes.size !== 1) {
    const detail = counts.map(([name, count]) => `${name}: ${count}`).join(", ");
    throw new Error(`the compared representations hold different program counts (${detail})`);
  }

  const problems = [];
  compare(typescript, label(tsPath, TS_SOURCE), snapshot, label(snapshotPath, SNAPSHOT), problems);
  if (database) {
    compare(
      typescript,
      label(tsPath, TS_SOURCE),
      database,
      label(dumpPath, "<database dump>"),
      problems,
    );
  }
  return {
    written: false,
    programs: typescript.size,
    slugs: [...typescript.keys()],
    problems,
    withDatabase: Boolean(database),
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
      `\napi/app/seed.py must be changed to match ${TS_SOURCE}. Never the other way round.`,
    );
    return 1;
  }

  for (const slug of result.slugs) {
    console.log(`${slug.padEnd(23)} ${FIELDS.length}/${FIELDS.length} fields match`);
  }
  const scope = result.withDatabase
    ? `${SNAPSHOT} and the database dump`
    : `${SNAPSHOT} (no database dump was given)`;
  console.log(
    `\nOK — ${result.programs} programs match ${TS_SOURCE} field by field, through ${scope}`,
  );
  return 0;
}

module.exports = { verify, FIELDS, TS_SOURCE, SNAPSHOT, resolve };

if (require.main === module) {
  try {
    process.exitCode = main(process.argv.slice(2));
  } catch (error) {
    console.error(`FAIL — ${error.message}`);
    process.exitCode = 1;
  }
}
