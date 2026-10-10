export type InstitutionTag = { tag: string; verification: string; mapping_note?: string };
export type ChineseInstitution = { code: string; name: string; province: string; city?: string | null; level: string; authority: string; note?: string; tags?: InstitutionTag[] };
export type OverseasInstitution = { name_en?: string | null; name_zh?: string | null; name_zh_kind?: string; qs_order?: number; country: string; city?: string; website?: string; sources: string[]; selection_basis: string[]; cricos_codes?: string[]; hk_category?: string; mo_category?: string; in_cn_library: boolean };
export type MasterProgram = { provider: string; institution: string; code: string; name: string; field: string; narrow: string; weeks: number | null; tuition: string | null; total_cost: string | null };
export type Query = Record<string, string | undefined>;
export function institutionTier(institution: {tags?: InstitutionTag[]} | null): '985' | '211' | '其他' | null {
  if (!institution) return null;
  return institution.tags?.some(t => t.tag === '985') ? '985' : institution.tags?.some(t => t.tag === '211') ? '211' : '其他';
}
export function eligibilityNote(institution: {level: string}) {
  return ['专科', '成人'].includes(institution.level) ? '专科 / 成人院校，硕士申请资格待核验' : null;
}
export function institutionSlug(school: {name_en?: string | null; name_zh?: string | null}) {
  return (school.name_en || school.name_zh || '').normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, '-').replace(/^-+|-+$/g, '');
}
export function searchInstitutions<T extends {name: string}>(rows: T[], query: string) {
  return rows.filter(row => row.name.toLowerCase().includes(query.trim().toLowerCase()));
}
export function filterSchools<T extends {name_en?: string | null; name_zh?: string | null; country: string}>(rows: T[], query: Query) {
  const q = query.q?.trim().toLowerCase() || '';
  return rows.filter(row => (!query.country || row.country === query.country) && (!q || [row.name_en, row.name_zh].some(name => name?.toLowerCase().includes(q))));
}
export function tuitionAmount(value: string | null) {
  if (!value || !/\d/.test(value)) return null;
  const amount = Number(value.replace(/[^\d.]/g, ''));
  return Number.isFinite(amount) ? amount : null;
}
export function filterPrograms<T extends MasterProgram>(rows: T[], query: Query) {
  const bound = (v?: string) => v?.trim() && Number.isFinite(Number(v)) && Number(v) >= 0 ? Number(v) : null;
  const min = bound(query.min), max = bound(query.max), duration = bound(query.duration);
  return rows.filter(row => {
    const tuition = tuitionAmount(row.tuition);
    return (!query.school || row.provider === query.school) && (!query.field || row.field === query.field) &&
      (duration === null || row.weeks === duration) && (min === null || (tuition !== null && tuition >= min)) && (max === null || (tuition !== null && tuition <= max));
  });
}
export function paginate<T>(rows: T[], rawPage = '1', size = 24) {
  const pages = Math.max(1, Math.ceil(rows.length / size));
  const n = Number(rawPage);
  const page = Number.isFinite(n) ? Math.max(1, Math.min(pages, Math.floor(n))) : 1;
  return { items: rows.slice((page-1)*size, page*size), page, pages, total: rows.length };
}
export function singleQuery(query: Record<string, string | string[] | undefined>): Query {
  return Object.fromEntries(Object.entries(query).map(([key, value]) => [key, Array.isArray(value) ? value[0] : value]));
}
