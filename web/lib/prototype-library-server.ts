import 'server-only';
import cn from '../prototype-fixtures/cn-institutions.json';
import overseas from '../prototype-fixtures/overseas-institutions.json';
import masters from '../prototype-fixtures/cricos-au-masters.json';
import { courses, requirements } from '../prototype-fixtures/data';
import { institutionSlug, type ChineseInstitution, type OverseasInstitution, type MasterProgram } from './prototype-library';
export const chineseInstitutions: ChineseInstitution[] = cn.institutions;
export const overseasInstitutions: OverseasInstitution[] = overseas.institutions;
export const masterPrograms: MasterProgram[] = masters.courses;
export const chineseSources = { source: cn.source, url: cn.source_url, tags: cn.tag_sources };
export function schoolForProvider(provider: string) { return overseasInstitutions.find(s => s.cricos_codes?.includes(provider)); }
export function schoolHref(provider: string) {
  const school = schoolForProvider(provider);
  return school ? `/prototype/schools/${encodeURIComponent(institutionSlug(school))}` : `/prototype/schools/${provider}`;
}
export function sampleRequirements(code: string) {
  const sample = courses.find(c => c['CRICOS Course Code'] === code);
  return sample ? requirements(sample) : null;
}
