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

/** The requirement fields a program page lists, with whether each is stated. */
export interface RequirementFields extends StatedFields {
  requiresCognate: boolean;
}

/**
 * The requirements a program's page has nothing for, named in the order the page lists them, so the
 * page can say them once (未收录：均分门槛、英语) instead of a row of 未收录 each. The two mark rows fold
 * into 均分门槛 when both are missing.
 */
export function missingRequirements(p: RequirementFields): string[] {
  const missing: string[] = [];
  if (p.minimumMark === null && p.non211MinimumMark === null) missing.push("均分门槛");
  else if (p.minimumMark === null) missing.push("均分门槛（985 / 211）");
  else if (p.non211MinimumMark === null) missing.push("均分门槛（其他院校）");
  if (!p.requiresCognate) missing.push("相关专业背景");
  if (p.prerequisites.length === 0) missing.push("先修课");
  if (p.englishRequirement === null) missing.push("英语");
  if (p.academicRequirement === null) missing.push("学术要求");
  if (p.deadlines.length === 0) missing.push("申请截止");
  return missing;
}

/**
 * Which optional columns of a school's program table any of its programs fills: the duration (CRICOS
 * weeks or a collected duration), the CRICOS total tuition, and the requirement badge. A column empty
 * for every program is left out rather than shown as a column of 未收录.
 */
export function programColumns(
  programs: (StatedFields & { slug: string; duration: string | null })[],
  courses: MasterProgram[],
): { duration: boolean; tuition: boolean; requirements: boolean } {
  const facts = programs.map((p) => cricosFacts(p.slug, courses));
  return {
    duration: programs.some((p, i) => Boolean(facts[i]?.weeks) || p.duration !== null),
    tuition: facts.some((f) => Boolean(f?.tuition)),
    requirements: programs.some(statesARequirement),
  };
}

/**
 * A school's programs narrowed by a search term and a study area, in the page itself. The catalogue's
 * own `q` also matches the school's names, so on a school page it would match every program of a school
 * whose name holds the term ("Technology" at UTS); here only the program's name is searched, without
 * case, and a term of only spaces is no filter.
 */
export function filterSchoolPrograms<T extends { name: string | null; field: string | null }>(
  programs: T[],
  { q, field }: { q: string; field: string },
): T[] {
  const term = q.trim().toLowerCase();
  return programs.filter(
    (p) => (!field || p.field === field) && (!term || (p.name ?? "").toLowerCase().includes(term)),
  );
}

/**
 * The page to show for a page number read from the address, and how many pages there are: a fraction is
 * rounded down, anything that is not a finite number reads as page 1, and a page past the end shows the
 * last one rather than an empty list.
 */
export function clampPage(raw: string | undefined, total: number, size: number): { page: number; pages: number } {
  const pages = Math.max(1, Math.ceil(total / size));
  const asked = Number(raw);
  const page = Number.isFinite(asked) ? Math.floor(asked) : 1;
  return { page: Math.min(pages, Math.max(1, page)), pages };
}
