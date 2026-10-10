import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { institutionTier, eligibilityNote, institutionSlug, searchInstitutions, filterSchools, filterPrograms, paginate, tuitionAmount, singleQuery, schoolQuery, sortSchools, paginateSchools, schoolListHref, type ChineseInstitution, type OverseasInstitution, type MasterProgram } from './prototype-library.ts';
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
test('school region and QS filters match the issue acceptance counts', () => {
  for (const [region, count] of [['英国', 33], ['澳大利亚', 40], ['中国香港', 22]] as const) {
    assert.equal(filterSchools(schools, {region}).length, count);
  }
  assert.equal(filterSchools(schools, {qs: '1-50'}).length, 50);
  assert.equal(filterSchools(schools, {qs: 'unranked'}).length, 46);
  const ukTop = filterSchools(schools, {region: '英国', qs: '1-50'});
  assert.ok(ukTop.length > 0 && ukTop.length < 33);
  assert.ok(ukTop.every(s => s.country === 'United Kingdom' && s.qs_order! <= 50));
  assert.equal(filterSchools(schools, {qs: '1-50,51-100'}).length, 102);
  assert.deepEqual(filterSchools(schools, {qs: '251-300,unranked'}), schools.filter(s => !s.qs_rank || Number(s.qs_rank.replace('=', '')) >= 251));
  assert.equal(filterSchools(schools, {q: '  ＩＭＰＥＲＩＡＬ  ', region: '英国'}).length, 1);
  assert.equal(filterSchools(schools, {q: '帝国理工'}).length, 1);
  assert.equal(filterSchools(schools, {q: 'no such school'}).length, 0);
});
test('school QS buckets use published ranks, keep ties and exclude unknowns', () => {
  const rows = [
    {country: 'Test', qs_order: 49, qs_rank: '=50'},
    {country: 'Test', qs_order: 50, qs_rank: '=50'},
    {country: 'Test', qs_order: 51, qs_rank: '51'},
    {country: 'Test', qs_rank: null},
  ];
  assert.deepEqual(filterSchools(rows, {qs: '1-50'}), rows.slice(0, 2));
  assert.deepEqual(filterSchools(rows, {qs: '51-100'}), rows.slice(2, 3));
  assert.deepEqual(filterSchools(rows, {qs: 'unranked'}), rows.slice(3));
  assert.equal(filterSchools(schools, {qs: 'bogus'}).length, schools.length);
});
test('school sort is stable, puts missing orders last and does not mutate input', () => {
  const sorted = sortSchools([...schools].reverse());
  assert.deepEqual(sorted.slice(0, 3).map(s => s.name_zh), ['麻省理工学院', '帝国理工学院', '斯坦福大学']);
  assert.deepEqual(sorted.slice(0, 3).map(s => s.qs_rank), ['1', '=2', '=2']);
  const rows = [{id: 'missing'}, {id: 'second', qs_order: 2}, {id: 'first', qs_order: 1}, {id: 'missing2'}, {id: 'tie', qs_order: 2}];
  assert.deepEqual(sortSchools(rows).map(s => s.id), ['first', 'second', 'tie', 'missing', 'missing2']);
  assert.equal(rows[0].id, 'missing');
  assert.deepEqual(sortSchools(schools).filter(s => !s.qs_order), schools.filter(s => !s.qs_order));
});
test('school query preserves multiple QS chips, normalizes invalid values and shares links', () => {
  const query = schoolQuery({q: ' 帝国 ', region: ['英国', '美国'], qs: ['1-50', '51-100', '1-50', 'bogus'], page: '2'});
  assert.deepEqual(query, {q: '帝国', region: '英国', qs: '1-50,51-100', page: '2'});
  assert.deepEqual(schoolQuery({region: 'invalid', qs: 'bogus', page: 'Infinity'}), {q: undefined, region: undefined, qs: undefined, page: 'Infinity'});
  const url = new URL(schoolListHref(query, {region: '澳大利亚'}), 'https://example.test');
  assert.equal(url.searchParams.get('q'), '帝国');
  assert.equal(url.searchParams.get('region'), '澳大利亚');
  assert.deepEqual(url.searchParams.getAll('qs'), ['1-50', '51-100']);
  assert.equal(url.searchParams.has('page'), false);
  assert.deepEqual(schoolQuery({q: url.searchParams.get('q')!, region: url.searchParams.get('region')!, qs: url.searchParams.getAll('qs')}), {...query, region: '澳大利亚', page: undefined});
  assert.equal(new URL(schoolListHref(query, {region: undefined, qs: undefined}), 'https://example.test').searchParams.has('qs'), false);
  assert.equal(new URL(schoolListHref(query, {page: '3'}), 'https://example.test').searchParams.get('page'), '3');
});
test('school pagination has 30 rows, clamps pages and reaches all schools exactly once', () => {
  const rows = sortSchools(schools);
  assert.equal(paginateSchools(rows).items.length, 30);
  assert.equal(paginateSchools(rows).pages, 12);
  assert.equal(paginateSchools(rows, '999').items.length, 16);
  const collected = Array.from({length: 12}, (_, i) => paginateSchools(rows, String(i + 1)).items).flat();
  assert.deepEqual(collected, rows);
  for (const page of ['0', '-3', 'NaN', 'Infinity']) assert.equal(paginateSchools(rows, page).page, 1);
  assert.deepEqual(paginateSchools([], '99'), {items: [], total: 0, pages: 1, page: 1});
});
test('school alliance sources remain available for linked chips', () => {
  for (const [name, alliance] of [['帝国理工学院', '罗素大学集团'], ['墨尔本大学', '澳洲八大'], ['哈佛大学', '常春藤联盟']]) {
    assert.ok(schools.find(s => s.name_zh === name)?.alliances?.some(a => a.name === alliance && a.source.startsWith('https://')));
  }
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
