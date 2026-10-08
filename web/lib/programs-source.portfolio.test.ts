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
// are built from the capture by override, so only the null and the empty string are this file's own
// invention.
//
// What a portfolio item carries about its program is `PortfolioProgram` — the institution and the
// English name, the two fields both views read — rather than the route's seven-field reference. That
// narrower shape is what makes the fallback path answerable: `PortfolioPicker` builds items out of the
// catalogue it holds, where the English name lives on `Program.name` (§3.6) and the wire's Chinese
// `name` has no counterpart at all, so a full reference is something the picker cannot fill truthfully.
// `toProgramRef` narrows a served row and `toPortfolioProgram` maps a catalogue entry; every
// expectation below is written out from the capture rather than produced by either function, so the two
// can disagree with the wire but not with each other.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  UNKNOWN,
  toPortfolioItems,
  toPortfolioProgram,
  toProgramLabel,
  toProgramRef,
  toProgramView,
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

/**
 * One captured program as the portfolio route's own `ProgramRef` projection: the seven fields
 * `api/app/schemas/application.py` serves under `program`.
 *
 * Written out here rather than taken from `toProgramRef`, which is the function under test: an
 * expectation the adapter produced itself would agree with the adapter whatever it answered. These
 * seven fields are the wire's, and they are what an item is handed before it is narrowed.
 */
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

/**
 * A program slug no captured program carries: the one a row with `program: null` names.
 *
 * A row the catalogue cannot answer for names a program the catalogue does not carry. Reusing a
 * captured slug here would describe a row the catalogue does know while claiming the route could not
 * resolve it, which is a fixture contradicting itself.
 */
const UNCATALOGUED_SLUG = "not-in-this-catalogue";

/** One served portfolio row, built around a given program reference. */
function servedRow(program: ServedProgramRef | null): ServedApplication {
  return {
    id: "0f0f0f0f-0000-0000-0000-000000000000",
    // The row names the program it carries; the null case is the row whose program is the one above.
    programId: program?.slug ?? UNCATALOGUED_SLUG,
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

test("an empty served name has no label either, so the card cannot print a blank after the dot", () => {
  // The hole `?? null` leaves: `""` is not nullish, so it survives the mapping and the render site's
  // `?? UNKNOWN` keeps it — `大学 · ` with nothing after the dot, which reads as a program with no
  // name. The capture carries a value in every seeded row, so the empty string is injected here.
  const label = toProgramLabel(ref({ nameEn: "" }));
  assert.equal(label, null);
  assert.notEqual(label, "");
  assert.equal(label ?? UNKNOWN, UNKNOWN);
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

test("toProgramRef narrows the served row to the two fields an item carries", () => {
  // Compared against the capture's own values, written out here, rather than against
  // `toProgramRef(program)` — the function under test agreeing with itself is not a binding. The other
  // five fields of the wire reference are deliberately not carried: no view reads them, and a full
  // reference is what `PortfolioPicker` cannot rebuild, which is the bug this shape removes.
  for (const program of capturedRefs()) {
    assert.deepEqual(toProgramRef(program), {
      university: program.university,
      nameEn: program.nameEn,
    });
  }
});

test("toProgramRef answers null for an empty served field, as it does for a missing one", () => {
  // The two text fields an item carries are the two a card prints, so an empty string is the case that
  // produces a blank half of the label rather than the marker.
  assert.deepEqual(toProgramRef(ref({ university: "", nameEn: "" })), {
    university: null,
    nameEn: null,
  });
});

test("toPortfolioProgram maps a catalogue entry onto the same two fields", () => {
  // The picker's own path: the items it builds become the rendered portfolio when the confirmation's
  // re-read fails, so a catalogue entry has to reach the views with the name the applicant just chose.
  // `Program.name` is the served English name (§3.6), which `toProgramView` wrote from the capture.
  for (const program of CAPTURED_RESPONSE) {
    const itemProgram = toPortfolioProgram(toProgramView(program));
    assert.deepEqual(itemProgram, { university: program.university, nameEn: program.nameEn });
    assert.equal(toProgramLabel(itemProgram), program.nameEn);
    assert.notEqual(toProgramLabel(itemProgram), UNKNOWN);
  }
});

test("toPortfolioProgram answers the marker for a catalogue entry with no English name", () => {
  // The picker renders `Program.name` through its own `?? UNKNOWN`, and this is the same rule one layer
  // down: an empty mapping result is what the view turns into the marker, never a blank.
  const view = toProgramView({ ...CAPTURED_RESPONSE[0], nameEn: "" });
  assert.equal(view.name, null);
  assert.equal(toPortfolioProgram(view).nameEn, null);
  assert.equal(toProgramLabel(toPortfolioProgram(view)), null);
});

// ------------------------------------------------------------------------------------------------
// The row the views are handed: the served program travels with it, because that is what replaced the
// lookup. `PortfolioItem` is the interface the whole app passes around, so a row that dropped the
// program here would leave the two views with nothing to render.
// ------------------------------------------------------------------------------------------------

test("a served row's program travels with the item the interface passes around", () => {
  const program = ref();
  const [item] = toPortfolioItems([servedRow(program)]);
  assert.deepEqual(item.program, { university: program.university, nameEn: program.nameEn });
  assert.equal(toProgramLabel(item.program), program.nameEn);
});

test("a row whose program is null carries the null through, rather than a substitute", () => {
  const [item] = toPortfolioItems([servedRow(null)]);
  assert.equal(item.program, null);
  assert.equal(toProgramLabel(item.program), null);
});

test("a row with no program key at all is carried as null rather than as an empty object", () => {
  // A body that omits `program` is the same case as one that sends `null`. Read as `undefined` the
  // field would leave a hole in the item's own shape and reach the views as a program that is present
  // and carries nothing — a different claim from "the route did not answer for this row", which is what
  // the views turn into the marker. `null` is the value that says the latter.
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
