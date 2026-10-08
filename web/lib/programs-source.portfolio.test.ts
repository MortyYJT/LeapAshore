// Tests for the program a portfolio row carries, and for the label the two portfolio views draw from it.
//
// M2d moved `HomeView` and `FlowView` off `web/lib/programs.ts`. Both used to resolve a row's program
// with `PROGRAMS.find((x) => x.slug === item.programSlug)`, while `GET /api/applications` had been
// serving the program alongside every row since M2c — declared in `programs-source.ts`, and read by
// nobody. The cost of the lookup was a silent one: a program the constants array does not carry
// rendered as its bare slug, which is a slug on a portfolio card rather than a program name.
//
// The fixture is read here for the same reason `programs-source.test.ts` reads it: the names under test
// have to be the server's, not this repository's idea of them. Every expectation below is derived from
// the captured `GET /api/programs` body, and the two that are not — a missing English name and a
// missing program — cannot be taken from it, because every seeded program carries both today. Those two
// are built from the capture by override, so only the null is this file's own invention.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  UNKNOWN,
  toPortfolioItems,
  toProgramLabel,
  toProgramRef,
} from "./programs-source.ts";
import type {
  ServedApplication,
  ServedProgram,
  ServedProgramRef,
} from "./programs-source.ts";

/**
 * A `GET /api/programs` body captured from the running server, read as the wire record it is.
 *
 * The same capture `programs-source.test.ts` is bound to, and for the same reason: the program a
 * portfolio row serves under `program` is a projection of exactly these catalogue rows, so the field
 * names and the two names' values have to be the server's rather than a pair typed out here.
 */
const CAPTURED_RESPONSE: ServedProgram[] = (
  JSON.parse(
    readFileSync(new URL("./programs-response.fixture.json", import.meta.url), "utf8"),
  ) as { response: ServedProgram[] }
).response;

/** One captured program as the portfolio route's own `ProgramRef` projection: the same seven fields. */
function toRef(program: ServedProgram): ServedProgramRef {
  return {
    slug: program.slug,
    name: program.name,
    nameEn: program.nameEn,
    university: program.university,
    city: program.city,
    degreeLevel: program.degreeLevel,
    dataStatus: program.dataStatus,
  };
}

/** The capture as program references, with its first entry checked so the helpers cannot be vacuous. */
function capturedRefs(): ServedProgramRef[] {
  assert.ok(CAPTURED_RESPONSE.length > 0, "the capture must carry at least one program");
  return CAPTURED_RESPONSE.map(toRef);
}

/** The first captured program's reference, for the overrides below. */
function ref(overrides: Partial<ServedProgramRef> = {}): ServedProgramRef {
  return { ...capturedRefs()[0], ...overrides };
}

/** One served portfolio row, built around a given program reference. */
function servedRow(program: ServedProgramRef | null): ServedApplication {
  return {
    id: "0f0f0f0f-0000-0000-0000-000000000000",
    programId: program?.slug ?? "unsw-master-it",
    tier: "冲",
    status: "considering",
    isPrimary: false,
    officialDeadline: null,
    deadlineSourceUrl: null,
    needsReview: false,
    origin: "user",
    program,
    createdAt: "2026-10-08T04:04:12.332920Z",
    updatedAt: "2026-10-08T04:04:12.332920Z",
  };
}

// ------------------------------------------------------------------------------------------------
// `toProgramLabel`: the name the two portfolio views print for a row.
// ------------------------------------------------------------------------------------------------

test("the capture still distinguishes the English program name from the Chinese one", () => {
  // The label has one right answer — the wire's `nameEn` — and this is what makes the assertions below
  // able to notice the wrong one. A capture whose two names agreed would let a mapping that read
  // `name` pass every test in this file.
  const both = CAPTURED_RESPONSE.filter(
    (program) => program.nameEn !== null && program.nameEn !== program.name,
  );
  assert.equal(
    both.length,
    CAPTURED_RESPONSE.length,
    "every captured program must carry an English name that differs from the Chinese one",
  );
});

test("a label comes from the served program rather than from the constants array", () => {
  for (const program of capturedRefs()) {
    assert.equal(
      toProgramLabel(program),
      program.nameEn,
      `the label of ${program.slug} is the name the server sent`,
    );
  }
});

test("a label is the English name, never the served Chinese one", () => {
  // The defect §3.6 rules on, named directly: the frontend's `name` is `nameEn`, so a key-for-key
  // reading of the projection puts the Chinese copy on the card with nothing to report it. The
  // capture's two names differ, so this cannot be passed by a program that only has one.
  for (const program of capturedRefs()) {
    assert.notEqual(toProgramLabel(program), program.name, `swapped copy for ${program.slug}`);
  }
});

test("a program the server did not resolve has no label, rather than a made-up one", () => {
  // `program: null` is the row the catalogue cannot answer for. There is nothing on this side to
  // resolve it with any more — the constants array is not a fallback, it is the thing this change
  // removed — so the answer is "no label" and the render site prints the unknown marker.
  assert.equal(toProgramLabel(null), null);
});

test("a served program with no English name has no label, not the Chinese name and not a blank", () => {
  // `name_en` is nullable on the wire, and the fallback a lookup would have taken — show the Chinese
  // name — is the swap above under another name. A blank is the other wrong answer this product keeps
  // out of its data: it turns "nobody recorded an English name" into "this program has no name".
  const label = toProgramLabel(ref({ nameEn: null }));
  assert.equal(label, null);
  assert.notEqual(label, "");
  assert.notEqual(label, UNKNOWN, "the marker belongs to the render site, not to the mapping");
  assert.notEqual(label, ref().name, "the Chinese name is not a stand-in for the English one");
});

test("the label mapping reads the wire's `nameEn`, and falls to null when the field is absent", () => {
  // A backstop for a body that omits the key rather than sending it as null. The property comes off a
  // capture, so it is the server's spelling; a mapping that read `name` or `englishName` would answer
  // with the Chinese name or with `undefined`, and neither is a label.
  const { nameEn: _omit, ...withoutNameEn } = ref();
  assert.equal(toProgramLabel(withoutNameEn as ServedProgramRef), null);
});

test("the label mapping is pure: the same reference maps to an equal label and is untouched", () => {
  const program = ref();
  const before = JSON.stringify(program);
  assert.equal(toProgramLabel(program), toProgramLabel(program));
  assert.equal(JSON.stringify(program), before);
});

test("toProgramRef copies the projection field by field", () => {
  const program = capturedRefs()[0];
  assert.deepEqual(toProgramRef(program), program);
});

// ------------------------------------------------------------------------------------------------
// The row the views are handed: the served program travels with it, because that is what replaced the
// lookup. `PortfolioItem` is the interface the whole app passes around, so a row that dropped the
// program here would leave the two views with nothing to render.
// ------------------------------------------------------------------------------------------------

test("a served row's program travels with the item the interface passes around", () => {
  const [item] = toPortfolioItems([servedRow(ref({ slug: "unsw-master-it" }))]);
  assert.deepEqual(item.program, toProgramRef(ref({ slug: "unsw-master-it" })));
  assert.equal(toProgramLabel(item.program), ref({ slug: "unsw-master-it" }).nameEn);
});

test("a row whose program is null carries the null through, rather than a substitute", () => {
  const [item] = toPortfolioItems([servedRow(null)]);
  assert.equal(item.program, null);
  assert.equal(toProgramLabel(item.program), null);
});

test("a row with no program key at all is carried as null rather than as an empty object", () => {
  // A body that omits `program` is the same case as one that sends `null`, and read as `undefined` it
  // would reach the view as "something is there" and render `undefined` through the label path. The
  // view's fallback chain (`toProgramLabel(program) ?? toProgramLabel({university})`) would also read
  // a hole in the item's own shape as a program with no name.
  const [item] = toPortfolioItems([
    { ...servedRow(ref()), program: undefined } as unknown as ServedApplication,
  ]);
  assert.equal(item.program, null);
});

test("the views' label path is the served one for every captured program", () => {
  // The end-to-end shape of the change, against the capture: row in, label out, no constants array
  // anywhere in the path. A view that still resolved the row through `web/lib/programs.ts` would print
  // this capture's Chinese `name` for a program the constants carry, and the bare slug for one it does
  // not; both are compared here.
  const items = toPortfolioItems(capturedRefs().map((program) => servedRow(program)));
  assert.equal(items.length, CAPTURED_RESPONSE.length);
  for (const [index, item] of items.entries()) {
    assert.equal(toProgramLabel(item.program), CAPTURED_RESPONSE[index].nameEn);
    assert.notEqual(toProgramLabel(item.program), CAPTURED_RESPONSE[index].name);
    assert.notEqual(toProgramLabel(item.program), item.programSlug);
  }
});
