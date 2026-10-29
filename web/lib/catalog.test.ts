import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  cricosCode,
  cricosFacts,
  schoolSlugForUniversity,
  statesARequirement,
  universityIdsFor,
  type UniversityRow,
} from "./catalog.ts";
import type { MasterProgram, OverseasInstitution } from "./prototype-library.ts";

const courses: MasterProgram[] = JSON.parse(
  readFileSync(new URL("../prototype-fixtures/cricos-au-masters.json", import.meta.url), "utf8"),
).courses;
const schools: OverseasInstitution[] = JSON.parse(
  readFileSync(new URL("../prototype-fixtures/overseas-institutions.json", import.meta.url), "utf8"),
).institutions;

const row = (overrides: Partial<UniversityRow>): UniversityRow => ({
  id: "x", name: "", nameEn: null, country: "澳大利亚", programCount: 0, withRequirementsCount: 0, ...overrides,
});

test("an Australian program finds its CRICOS facts by course code", () => {
  assert.equal(cricosCode("cricos-0100139"), "0100139");
  const facts = cricosFacts("cricos-0100139", courses);
  assert.equal(facts?.code, "0100139");
  assert.equal(facts?.name, "Master of Business Analytics");
});

test("a program from any other country has no CRICOS facts, rather than a neighbour's", () => {
  assert.equal(cricosCode("massachusetts-institute-master-in-city-planning-mcp-0754ec"), null);
  assert.equal(cricosFacts("massachusetts-institute-master-in-city-planning-mcp-0754ec", courses), null);
  assert.equal(cricosFacts("cricos-NOSUCH", courses), null);
});

test("a school gathers every catalogue row that carries its name", () => {
  const melbourne = schools.find((s) => s.name_zh === "墨尔本大学");
  assert.ok(melbourne);
  const rows = [
    row({ id: "university-of-melbourne", name: "墨尔本大学" }),
    row({ id: "cricos-00116K", name: "墨尔本大学", programCount: 215 }),
    row({ id: "cricos-00124K", name: "维多利亚大学（澳大利亚）" }),
  ];
  assert.deepEqual(universityIdsFor(melbourne, rows).sort(), ["cricos-00116K", "university-of-melbourne"]);
});

test("a school whose Chinese names differ is still found by its English name", () => {
  const school = { name_zh: "莫纳什大学", name_en: "Monash University" } as OverseasInstitution;
  const rows = [row({ id: "monash", name: "蒙纳士大学", nameEn: "Monash University" })];
  assert.deepEqual(universityIdsFor(school, rows), ["monash"]);
});

test("a program row links back to its school's page in the library", () => {
  const sydney = schools.find((s) => s.name_zh === "悉尼大学");
  assert.ok(sydney);
  const rows = [row({ id: "usyd", name: "悉尼大学", nameEn: "The University of Sydney" })];
  assert.equal(schoolSlugForUniversity("usyd", rows, schools), "the-university-of-sydney");
  assert.equal(schoolSlugForUniversity("no-such-row", rows, schools), null);
});

test("a program states a requirement by the backend's has_requirement_data rule", () => {
  const none = {
    minimumMark: null, non211MinimumMark: null, englishRequirement: null, prerequisites: [] as string[],
    academicRequirement: null, deadlines: [] as { label: string | null; date: string; sourceUrl: string }[],
  };
  assert.equal(statesARequirement(none), false);
  assert.equal(statesARequirement({ ...none, englishRequirement: "IELTS 6.5" }), true);
  assert.equal(statesARequirement({ ...none, minimumMark: 80 }), true);
  assert.equal(statesARequirement({ ...none, non211MinimumMark: 85 }), true);
  assert.equal(statesARequirement({ ...none, prerequisites: ["Calculus"] }), true);
  assert.equal(statesARequirement({ ...none, academicRequirement: "A 2:1 honours degree" }), true);
  // A past deadline still counts: the page lists it, labelled 已截止.
  assert.equal(statesARequirement({ ...none, deadlines: [{ label: "Round 1", date: "2026-01-15", sourceUrl: "https://example.edu" }] }), true);
});
