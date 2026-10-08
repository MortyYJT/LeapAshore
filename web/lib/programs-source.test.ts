// Tests for the mapping from the served catalogue onto the shape the picker renders.
//
// The fixture at the top is the point of this file. `web/lib/roadmap-source.test.ts` records the
// defect that made the pattern necessary: that adapter read `material.id` and `material.label` while
// the wire said `key` and `title`, and every test passed, because the fixtures had been typed out
// against the adapter's own declarations. Nothing type-checked the difference — both sides were
// declared in the same module, so the compiler was only ever comparing the adapter with its own wrong
// idea of the response. So the tests that matter here read `programs-response.fixture.json`, a
// captured `GET /api/programs` body, and their expectations are derived from the capture rather than
// from `ServedProgram`.
//
// Two names in this mapping are not type errors anywhere when they are got wrong, which is why they
// are pinned separately below:
//
//   - `ProgramView.name` is the English program name, which the wire calls `nameEn`. A key-for-key
//     adapter maps `name` to `name`, which is the Chinese name, and silently swaps the copy rendered
//     in `PortfolioPicker`, `HomeView` and `FlowView`. `note/.../2026-10-06-stage-2-m2-design.md`
//     §3.6 is the ruling: the endpoint keeps its shape and the adapter makes the mapping.
//   - five fields the frontend declared as non-nullable `string` come back as `string | null`, where
//     `null` means "this catalogue does not know yet". Substituting `""` for one of them turns an
//     unknown into a claim, which is the failure this product exists to avoid (the same rule
//     `api/app/schemas/program.py` states for the wire).

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  UNKNOWN,
  toApplicationRows,
  toPortfolioItems,
  toProgramLabel,
  toProgramView,
} from "./programs-source.ts";
import type { ServedApplication, ServedProgram } from "./programs-source.ts";
import type { PortfolioItem, Program } from "./types.ts";

/**
 * A `GET /api/programs` body captured from the running server, read here as the wire record it is.
 *
 * The file is `programs-response.fixture.json`; its `$comment` names the command that produced it. It
 * is not written by hand and must not be edited by hand — its value is that the names inside it were
 * not chosen by this repository.
 */
const CAPTURED_RESPONSE: ServedProgram[] = (
  JSON.parse(
    readFileSync(new URL("./programs-response.fixture.json", import.meta.url), "utf8"),
  ) as { response: ServedProgram[] }
).response;

/** Read a field the capture carries but this side does not declare, without typing it into the module. */
function wireField(row: object, field: string): unknown {
  return (row as unknown as Record<string, unknown>)[field];
}

/** One served program, in the spelling the route uses, built from the capture where possible. */
function served(overrides: Partial<ServedProgram> = {}): ServedProgram {
  const [first] = CAPTURED_RESPONSE;
  assert.ok(first, "the capture must carry at least one program");
  return { ...first, ...overrides };
}

// The capture is the record of the server, so it is checked before it is used as one. A regeneration
// from `ServedProgram` would produce a body without these properties, or with the frontend's names.
test("the capture still carries the wire's own names", () => {
  assert.ok(CAPTURED_RESPONSE.length > 0, "the capture must carry programs");
  const wire = CAPTURED_RESPONSE[0] as unknown as Record<string, unknown>;
  assert.equal("nameEn" in wire, true, "the wire names the English program name `nameEn`");
  assert.equal("name" in wire, true);
  // The database's own spelling must not be in it, or the capture would be this repository's idea of
  // the response rather than the server's.
  assert.equal(
    "minimum_mark" in wire || "english_requirement" in wire || "degree_level" in wire,
    false,
    "the wire is camelCase",
  );
  // And every program's citation must be the three keys the route serves, not the frontend's five.
  for (const program of CAPTURED_RESPONSE) {
    assert.deepEqual(Object.keys(program.source).sort(), ["status", "title", "url"]);
  }
});

// The mapping §3.6 rules on, asserted against the capture rather than against a hand-typed pair: every
// served program's `nameEn` becomes the view's `name`, and the served `name` (Chinese) does not.
test("maps the served nameEn onto the view's name, and never the served name", () => {
  for (const program of CAPTURED_RESPONSE) {
    const view = toProgramView(program);
    assert.equal(view.name, program.nameEn, `name of ${program.slug}`);
  }

  // The defect this pins, named directly: a key-for-key adapter produces the Chinese name here. The
  // captured bodies have both keys, so this cannot be satisfied by a program whose `nameEn` is missing.
  const chinese = CAPTURED_RESPONSE.filter((program) => program.nameEn !== program.name);
  assert.ok(chinese.length > 0, "the capture must distinguish the two names");
  for (const program of chinese) {
    assert.notEqual(toProgramView(program).name, program.name, `swapped copy for ${program.slug}`);
  }
});

// Every field is compared against the capture, so the names under test are the server's. The
// expectation is written by hand rather than by a helper that also does the mapping: a helper would be
// the adapter's own guess written twice, which is the symmetry the capture exists to break.
test("maps every served field onto the view field by field", () => {
  const views = CAPTURED_RESPONSE.map(toProgramView);
  assert.deepEqual(
    views,
    CAPTURED_RESPONSE.map((program) => ({
      slug: program.slug,
      university: program.university,
      name: program.nameEn,
      city: program.city,
      degreeLevel: program.degreeLevel,
      field: program.field,
      duration: program.duration,
      minimumMark: program.minimumMark,
      non211MinimumMark: program.non211MinimumMark,
      requiresCognate: program.requiresCognate,
      prerequisites: program.prerequisites,
      englishRequirement: program.englishRequirement,
      source: {
        // The wire's `source` is `{url, title, status}`; these three keys are this side's own, and the
        // values below are the only ones available without inventing something.
        id: program.slug,
        title: program.source.title,
        url: program.source.url,
        // Deliberately null and not a date: the capture carries no verification date, and a value
        // here would be a verification claim this side invented.
        verifiedAt: null,
        // The capture has no `excerpt` either — the seed drops the frontend's manual summary — so the
        // view carries an empty string, which is "nothing to show" rather than a claim about the page.
        excerpt: "",
        status: program.source.status,
      },
      dataStatus: program.dataStatus,
    })),
    "every served program, mapped field by field",
  );
});

// The five fields `api/app/schemas/program.py` records as nullable. All six seeded programs carry a
// value today, so a test over the capture alone cannot notice a `?? ""`; the nulls are built here.
test("carries a null through as null rather than turning it into an empty string", () => {
  const NULLABLE = ["city", "degreeLevel", "field", "duration", "englishRequirement"] as const;
  const view = toProgramView(
    served({
      city: null,
      degreeLevel: null,
      field: null,
      duration: null,
      englishRequirement: null,
    }),
  );

  for (const key of NULLABLE) {
    assert.equal(view[key], null, `${key} stays null`);
    assert.notEqual(view[key], "", `${key} must not be coerced to an empty string`);
    assert.notEqual(view[key], UNKNOWN, `${key} is mapped, not rendered: the marker is the view's job`);
  }
  // The two numbers are a different kind of unknown and were already nullable on this side: a
  // baseline nobody recorded is `null`, which `eligibility.ts` reads as "no threshold to compare
  // against" rather than as a mark of zero.
  assert.equal(toProgramView(served({ minimumMark: null })).minimumMark, null);
  assert.equal(toProgramView(served({ non211MinimumMark: null })).non211MinimumMark, null);
});

test("a null nameEn stays null and is not swapped for the Chinese name", () => {
  // `name_en` is nullable on the wire as well, and this is the case a deliberate `.name` fallback
  // would look reasonable on and be wrong: showing the Chinese name under the frontend's `name` is
  // still showing a name the server did not choose for that field. Unknown stays unknown, and the
  // render site turns it into the marker.
  const program = served({ nameEn: null });
  const view = toProgramView(program);
  assert.equal(view.name, null);
  assert.notEqual(view.name, program.name);
  assert.notEqual(view.name, "");
});

test("the unknown marker is a word, not a blank", () => {
  // The four sites that render one of the nullable fields use this constant. `""` is the value the
  // rule forbids, so the constant is pinned rather than assumed.
  assert.equal(UNKNOWN, "未知");
  assert.notEqual(UNKNOWN.trim(), "");
});

// The view is what `eligibility.ts` walks, and it is nullable in five places. A mapped program that
// drops one of them, or renders the marker into it, is a program the assessment code then reads as a
// claim about the catalogue.
test("a mapped program has every field the assessment code reads", () => {
  const view: Program = toProgramView(served());
  assert.deepEqual(
    Object.keys(view).sort(),
    [
      "city",
      "dataStatus",
      "degreeLevel",
      "duration",
      "englishRequirement",
      "field",
      "minimumMark",
      "name",
      "non211MinimumMark",
      "prerequisites",
      "requiresCognate",
      "slug",
      "source",
      "university",
    ],
    "the view carries exactly the fields the picker and the assessment read",
  );
  // A null-valued field and a marker-valued one are not the same thing, so this is the assertion that
  // would fail if a `?? ""` or `?? UNKNOWN` were reintroduced at the mapping instead of the render.
  assert.deepEqual(view.prerequisites, served().prerequisites);
});

// A status this build has never heard of must not be read as 已核验: `eligibility.ts` stops warning the
// applicant that a conclusion rests on unverified data when it sees that value.
test("an unrecognised status is reported as unverified, never as verified", () => {
  assert.equal(toProgramView(served({ dataStatus: "已核验" })).dataStatus, "已核验");
  assert.equal(toProgramView(served({ dataStatus: "部分核验" })).dataStatus, "待核验");
  assert.equal(toProgramView(served({ dataStatus: "" })).dataStatus, "待核验");
  assert.equal(
    toProgramView(served({ source: { ...served().source, status: "已核验" } })).source.status,
    "已核验",
  );
  assert.equal(
    toProgramView(served({ source: { ...served().source, status: "anything else" } })).source.status,
    "待核验",
  );
});

// The fields the interface cannot do its job without: the slug keys every portfolio row, and the url
// is the link the applicant follows to check the values against the official page.
test("refuses a body whose required fields are missing", () => {
  assert.throws(() => toProgramView(served({ slug: "" })), /条目缺少 slug/);
  assert.throws(() => toProgramView(served({ university: "" })), /条目缺少 university/);
  assert.throws(
    () => toProgramView(served({ source: { ...served().source, url: "" } })),
    /条目缺少 source\.url/,
  );
  assert.throws(
    () => toProgramView(served({ source: { ...served().source, title: "" } })),
    /条目缺少 source\.title/,
  );
});

// The nullable fields are the frontend's own declarations, so this is asserted where `tsc --noEmit`
// runs over it: assigning `null` to one of the five has to be legal, and assigning `null` to a field
// the catalogue always answers has to be illegal.
test("the domain type carries the nullability the wire declares, and only there", () => {
  const nothing: Program = toProgramView(served());
  const widened: Program = {
    ...nothing,
    name: null,
    city: null,
    degreeLevel: null,
    field: null,
    duration: null,
    englishRequirement: null,
  };
  assert.equal(widened.name, null);
  assert.equal(nothing.university, served().university);

  // `@ts-expect-error` rather than a cast: if `university` ever became nullable the line below would
  // stop being an error, and the directive would fail the type-check instead of passing silently.
  // @ts-expect-error university is a required string, as it is on the wire
  const broken: Program = { ...nothing, university: null };
  assert.equal(broken.slug, nothing.slug);
});

// A program with thin values is still a program the applicant can choose, and the order the route
// serves is the order the picker shows.
test("keeps the served order and does not drop a program with thin values", () => {
  const views = CAPTURED_RESPONSE.map(toProgramView);
  assert.deepEqual(
    views.map((view) => view.slug),
    CAPTURED_RESPONSE.map((program) => program.slug),
  );
  assert.equal(toProgramView(served({ duration: null })).slug, served().slug);
});

// ------------------------------------------------------------------------------------------------
// The portfolio half. The rows come back from `GET /api/applications`, which serves the applicant's
// own rows; the payload goes out to `PUT /api/applications`, which replaces the whole portfolio.
// Both are spelled by the route's schema (`ApplicationOut` / `ApplicationIn`), not by the database's
// columns, so the field-by-field expectations below are written as camelCase literals.
// ------------------------------------------------------------------------------------------------

/** One served portfolio row, in the spelling `GET /api/applications` uses. */
const SERVED_ROW: ServedApplication = {
  id: "0f0f0f0f-0000-0000-0000-000000000000",
  programId: "unsw-master-it",
  tier: "冲",
  status: "considering",
  isPrimary: false,
  officialDeadline: null,
  deadlineSourceUrl: null,
  needsReview: false,
  origin: "user",
  program: {
    slug: "unsw-master-it",
    name: "信息技术硕士",
    nameEn: "Master of Information Technology",
    university: "新南威尔士大学",
    city: "悉尼",
    degreeLevel: "授课型硕士",
    dataStatus: "待核验",
  },
  createdAt: "2026-10-07T12:41:51.352633Z",
  updatedAt: "2026-10-07T12:41:51.352633Z",
};

test("maps a served portfolio row onto the item the interface renders", () => {
  const [item] = toPortfolioItems([
    { ...SERVED_ROW, tier: "保", needsReview: true, isPrimary: true, status: "applying" },
  ]);
  assert.deepEqual(item, {
    programSlug: "unsw-master-it",
    // The program the route served alongside the row travels with the item: the two portfolio views
    // render it, so it is part of what this mapping produces rather than a field of the row left behind.
    program: {
      slug: "unsw-master-it",
      name: "信息技术硕士",
      nameEn: "Master of Information Technology",
      university: "新南威尔士大学",
      city: "悉尼",
      degreeLevel: "授课型硕士",
      dataStatus: "待核验",
    },
    tier: "保",
    // The server's portfolio is a list of choices the applicant made, so every row in it is confirmed.
    confirmed: true,
    needsReview: true,
    isPrimary: true,
  });
});

test("a row the server does not flag is not flagged here", () => {
  const [item] = toPortfolioItems([SERVED_ROW]);
  assert.equal(item.needsReview, false);
  assert.equal(item.isPrimary, false);
  // Every field of the item is written from the row rather than left to a default that happens to
  // read the same. This is the assertion that notices a dropped `needsReview`.
  assert.deepEqual(Object.keys(item).sort(), [
    "confirmed",
    "isPrimary",
    "needsReview",
    "program",
    "programSlug",
    "tier",
  ]);
  // The row's program projection travels with the item since M2d, because the two portfolio views
  // render it: they resolved the row through `web/lib/programs.ts` before, and a program that array
  // does not carry reached the card as a bare slug. What the item carries is the copy this adapter
  // made, field for field — a spread of the served object would let a field the route adds later
  // reach the render sites without a decision here.
  assert.deepEqual(item.program, {
    slug: SERVED_ROW.program!.slug,
    name: SERVED_ROW.program!.name,
    nameEn: SERVED_ROW.program!.nameEn,
    university: SERVED_ROW.program!.university,
    city: SERVED_ROW.program!.city,
    degreeLevel: SERVED_ROW.program!.degreeLevel,
    dataStatus: SERVED_ROW.program!.dataStatus,
  });
  // The label the views print is the English name, which is what the wire calls `nameEn`; the served
  // `name` is the Chinese one and is not it.
  assert.equal(toProgramLabel(item.program), SERVED_ROW.program!.nameEn);
  assert.notEqual(toProgramLabel(item.program), SERVED_ROW.program!.name);
});

test("the rows sent back to the route speak the route's own field names", () => {
  const rows = toApplicationRows([
    { programSlug: "unsw-master-it", tier: "冲", confirmed: true, needsReview: false, isPrimary: true },
    { programSlug: "usyd-master-cs", tier: "保", confirmed: true },
  ]);
  assert.deepEqual(rows, [
    { programId: "unsw-master-it", tier: "冲", isPrimary: true, needsReview: false },
    { programId: "usyd-master-cs", tier: "保", isPrimary: false, needsReview: false },
  ]);
  // `origin` and `status` are deliberately absent: the server writes `origin` itself, and a status is
  // not something the confirmation flow has an opinion about. The route refuses unknown keys with a
  // 422, so sending one would fail the whole write rather than being ignored.
  for (const row of rows) {
    const wire = row as unknown as Record<string, unknown>;
    assert.equal("origin" in wire || "status" in wire || "programSlug" in wire, false);
  }
});

test("an applicant who confirms nothing sends an empty portfolio, not no request", () => {
  // An empty list is a real statement — "the applicant holds no programs" — and the route reads it as
  // one. `[]` is therefore the payload for it, which is the opposite of the roadmap path, where an
  // empty `applicableKeys` means something destructive and the caller skips the call instead.
  assert.deepEqual(toApplicationRows([]), []);
  assert.deepEqual(toPortfolioItems([]), []);
});

test("a portfolio item is what the interface passes around", () => {
  // A compile-time claim the runtime one above rests on: the item type is `PortfolioItem`, so a field
  // renamed on either side is a type error rather than an `undefined` at a render site.
  const items: PortfolioItem[] = toPortfolioItems([SERVED_ROW]);
  assert.equal(items[0].tier, "冲");
});

test("toProgramView is pure: the same body maps to an equal view and the input is untouched", () => {
  const program = served();
  const before = JSON.stringify(program);
  assert.deepEqual(toProgramView(program), toProgramView(program));
  assert.equal(JSON.stringify(program), before);
});

test("the citation carries the served url and title", () => {
  for (const program of CAPTURED_RESPONSE) {
    const view = toProgramView(program);
    assert.equal(view.source.url, program.source.url, `url of ${program.slug}`);
    assert.equal(view.source.title, program.source.title, `title of ${program.slug}`);
    assert.equal(wireField(program.source, "url") !== null, true);
  }
});
