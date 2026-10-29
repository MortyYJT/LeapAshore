// Joining the library's own files to the backend catalogue (design D3 and D11).
//
// Two joins, both by values both sides already hold rather than by an id one side invented:
// - an Australian program (`cricos-<code>`) to its CRICOS facts (tuition, weeks, narrow field), which the
//   `programs` table has no columns for;
// - a school in the library's 287 to the catalogue rows that carry its name. One school can have several
//   rows (two CRICOS provider codes, or an empty row the importer left for a school whose site refused
//   collection), so a school maps to a list of ids.

import type { CollectedDeadline } from "./deadlines.ts";
import { institutionSlug, type MasterProgram, type OverseasInstitution } from "./prototype-library.ts";

/** One school row as `GET /api/universities` serves it. */
export interface UniversityRow {
  id: string;
  name: string;
  nameEn: string | null;
  country: string;
  programCount: number;
  withRequirementsCount: number;
}

const CRICOS_PREFIX = "cricos-";

/** The CRICOS course code inside a program id, or null for a program that is not a CRICOS course. */
export function cricosCode(programId: string): string | null {
  return programId.startsWith(CRICOS_PREFIX) ? programId.slice(CRICOS_PREFIX.length) : null;
}

export function cricosFacts(programId: string, courses: MasterProgram[]): MasterProgram | null {
  const code = cricosCode(programId);
  if (!code) return null;
  return courses.find((course) => course.code === code) ?? null;
}

/** English names compared without case, a leading "The" or a bracketed short name. */
function englishKey(name: string | null | undefined): string {
  return (name ?? "")
    .toLowerCase()
    .replace(/\(.*?\)/g, "")
    .replace(/^the\s+/, "")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function sameSchool(school: Pick<OverseasInstitution, "name_zh" | "name_en">, row: UniversityRow): boolean {
  if (school.name_zh && row.name === school.name_zh) return true;
  const key = englishKey(school.name_en);
  return key !== "" && key === englishKey(row.nameEn);
}

/** Every catalogue row that is this school. */
export function universityIdsFor(
  school: Pick<OverseasInstitution, "name_zh" | "name_en">,
  rows: UniversityRow[],
): string[] {
  return rows.filter((row) => sameSchool(school, row)).map((row) => row.id);
}

/** The library slug of the school a catalogue row belongs to, or null when the library does not list it. */
export function schoolSlugForUniversity(
  universityId: string,
  rows: UniversityRow[],
  schools: OverseasInstitution[],
): string | null {
  const row = rows.find((r) => r.id === universityId);
  if (!row) return null;
  const school = schools.find((s) => sameSchool(s, row));
  return school ? institutionSlug(school) : null;
}

/** The fields a program states its requirements in, as `GET /api/programs` serves them. */
export interface StatedFields {
  minimumMark: number | null;
  non211MinimumMark: number | null;
  englishRequirement: string | null;
  prerequisites: readonly string[];
  academicRequirement: string | null;
  deadlines: readonly CollectedDeadline[];
}

/**
 * Whether a program states a requirement its page shows: an English line, a 985/211 mark, a mark for
 * other universities, a prerequisite, an academic requirement or an application deadline (past ones
 * too, listed as 已截止). The rule of `has_requirement_data` in `api/app/models/program.py`, so a row's
 * badge agrees with the catalogue filter and the school counts; change both together.
 */
export function statesARequirement(p: StatedFields): boolean {
  return (
    p.minimumMark !== null ||
    p.non211MinimumMark !== null ||
    p.englishRequirement !== null ||
    p.prerequisites.length > 0 ||
    p.academicRequirement !== null ||
    p.deadlines.length > 0
  );
}
