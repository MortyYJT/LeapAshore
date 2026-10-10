import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { institutionTier, eligibilityNote, institutionSlug, searchInstitutions, filterSchools, filterPrograms, paginate, tuitionAmount, singleQuery, type ChineseInstitution, type OverseasInstitution, type MasterProgram } from './prototype-library.ts';
const fixture = (name: string) => JSON.parse(readFileSync(new URL(`../prototype-fixtures/${name}.json`, import.meta.url), 'utf8'));
const cn: ChineseInstitution[] = fixture('cn-institutions').institutions;
const schools: OverseasInstitution[] = fixture('overseas-institutions').institutions;
const programs: MasterProgram[] = fixture('cricos-au-masters').courses;
test('tier prioritizes 985, preserves pending 211 mappings and unknown selection', () => {
  for (const [name, tier] of [['清华大学', '985'], ['苏州大学', '211'], ['中国石油大学（华东）', '211']]) assert.equal(institutionTier(cn.find((s: {name: string}) => s.name === name) ?? null), tier);
  assert.equal(institutionTier(null), null);
  assert.equal(institutionTier({tags: []}), '其他');
  const oil = cn.find((s: {name: string}) => s.name === '中国石油大学（华东）');
  assert.ok(oil?.tags);
  assert.ok(oil.tags.some((t: {verification: string; mapping_note?: string}) => t.verification === '待核验' && t.mapping_note));
});
test('non-bachelor institutions keep eligibility unknown', () => {
  for (const level of ['专科', '成人']) assert.equal(eligibilityNote({level}), '专科 / 成人院校，硕士申请资格待核验');
  assert.equal(eligibilityNote({level: '本科'}), null);
});
test('slugs are stable, support Chinese fallback and unique across the complete library', () => {
  assert.equal(institutionSlug({name_en: 'The University of Melbourne'}), 'the-university-of-melbourne');
  assert.equal(institutionSlug({name_zh: '澳门大学'}), '澳门大学');
  assert.equal(new Set(schools.map(institutionSlug)).size, 346);
});
test('name search trims whitespace and finds every Chinese institution', () => {
  assert.equal(searchInstitutions(cn, '').length, 3167);
  assert.equal(searchInstitutions(cn, ' 清华 ')[0].name, '清华大学');
  assert.equal(searchInstitutions(cn, 'no such school').length, 0);
});
test('school filters preserve region counts and search both names', () => {
  assert.equal(filterSchools(schools, {}).length, 346);
  for (const [country, count] of [['Australia',40], ['Hong Kong SAR',22], ['Macau SAR',10]]) assert.equal(filterSchools(schools, {country: String(country)}).length, count);
  assert.equal(filterSchools(schools, {q: 'MELBOURNE', country: 'Australia'}).length, 1);
  assert.equal(filterSchools([{name_zh:'澳门大学', country:'Macau SAR'}], {q:'澳门'}).length, 1);
});
test('programme filters combine school, field, total tuition and duration without treating unknown as zero', () => {
  const first = programs[0];
  assert.equal(filterPrograms(programs, {}).length, 2920);
  const rows = filterPrograms(programs, {school:first.provider, field:first.field, min:'104000', max:'104000', duration:String(first.weeks)});
  assert.ok(rows.some(r => r.code === first.code));
  assert.ok(rows.every(r => r.provider === first.provider && r.field === first.field && tuitionAmount(r.tuition) === 104000 && r.weeks === first.weeks));
  assert.equal(tuitionAmount(null), null);
  assert.equal(tuitionAmount(''), null);
  assert.equal(tuitionAmount('未知'), null);
  assert.equal(filterPrograms([{...first, tuition:null}], {max:'1000000'}).length, 0);
});
test('pagination can reach every programme and clamps malformed pages', () => {
  const collected = [];
  for (let page=1; page<=Math.ceil(programs.length/24); page++) collected.push(...paginate(programs, String(page)).items);
  assert.equal(new Set(collected.map(r => r.code)).size, 2920);
  for (const page of ['0','-1','abc','Infinity']) assert.equal(paginate(programs, page).page, 1);
  assert.equal(paginate([], '99').page, 1);
  assert.equal(paginate(programs,'999999').items.length,16);
});

test('repeated URL filters select the first value and preserve undefined filters', () => {
  assert.deepEqual(singleQuery({school:['00002J','other'],q:undefined,page:'2'}), {school:'00002J',q:undefined,page:'2'});
});
test('the nine original requirement samples all exist in the complete course library', () => {
  const samples = fixture('cricos-courses').courses;
  assert.equal(samples.length,9);
  assert.ok(samples.every((s: {'CRICOS Course Code':string}) => programs.some(p => p.code === s['CRICOS Course Code'])));
  assert.equal(programs.length-samples.length,2911);
  const providers = new Set(schools.flatMap(s => s.cricos_codes || []));
  assert.ok(programs.every(p => providers.has(p.provider)));
});
