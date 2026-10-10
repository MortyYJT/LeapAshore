export type InstitutionTag = { tag: string; verification: string; mapping_note?: string };
export type ChineseInstitution = { code: string; name: string; province: string; city?: string | null; level: string; authority: string; note?: string; tags?: InstitutionTag[] };
export type OverseasInstitution = { name_en?: string | null; name_zh?: string | null; name_zh_kind?: string; qs_order?: number | null; qs_rank?: string | null; region_zh?: string; alliances?: {name: string; source: string}[]; country: string; city?: string; website?: string; sources: string[]; selection_basis: string[]; cricos_codes?: string[]; hk_category?: string; mo_category?: string; in_cn_library: boolean };
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
export const schoolRegions = ['中国香港', '新加坡', '英国', '美国', '澳大利亚', '中国澳门', '中国大陆', '马来西亚', '欧洲', '加拿大', '新西兰', '日本', '韩国', '其他'];
export const schoolQsRanges = [
  ['1-50', 'Top 1–50'], ['51-100', '51–100'], ['101-150', '101–150'],
  ['151-200', '151–200'], ['201-250', '201–250'], ['251-300', '251–300'],
  ['unranked', '未进入前 300'],
] as const;
const normalizeName = (value: string) => value.normalize('NFKC').trim().toLowerCase();
function qsSelections(value?: string) {
  const values = new Set(value?.split(',') ?? []);
  return schoolQsRanges.map(([key]) => key).filter(key => values.has(key));
}
export function schoolQuery(query: Record<string, string | string[] | undefined>): Query {
  const single = singleQuery(query);
  const qs = qsSelections(Array.isArray(query.qs) ? query.qs.join(',') : query.qs);
  return {q: single.q?.trim() || undefined, region: schoolRegions.includes(single.region || '') ? single.region : undefined, qs: qs.join(',') || undefined, page: single.page};
}
export function schoolListHref(query: Query, changes: Query = {}) {
  const next: Query = {...query, page: undefined, ...changes};
  const params = new URLSearchParams();
  for (const key of ['q', 'region', 'page']) if (next[key]) params.set(key, next[key]!);
  for (const qs of qsSelections(next.qs)) params.append('qs', qs);
  return `/prototype/schools${params.size ? `?${params}` : ''}`;
}
export function filterSchools<T extends {name_en?: string | null; name_zh?: string | null; country: string; region_zh?: string; qs_rank?: string | null}>(rows: T[], query: Query) {
  const q = normalizeName(query.q || '');
  const ranges = qsSelections(query.qs);
  return rows.filter(row => {
    const rank = row.qs_rank && /^=?\d+$/.test(row.qs_rank) ? Number(row.qs_rank.replace('=', '')) : null;
    return (!query.country || row.country === query.country) && (!query.region || row.region_zh === query.region) &&
      (!q || [row.name_en, row.name_zh].some(name => name && normalizeName(name).includes(q))) &&
      (!ranges.length || ranges.some(range => {
        if (range === 'unranked') return rank === null || rank > 300;
        const [min, max] = range.split('-').map(Number);
        return rank !== null && rank >= min && rank <= max;
      }));
  });
}
export function sortSchools<T extends {qs_order?: number | null}>(rows: T[]): T[] {
  return [...rows].sort((a, b) => (a.qs_order ?? Infinity) - (b.qs_order ?? Infinity));
}
export function paginateSchools<T>(rows: T[], rawPage = '1') {
  return paginate(rows, rawPage, 30);
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
