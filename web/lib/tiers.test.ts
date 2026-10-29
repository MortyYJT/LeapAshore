import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  REACH_AVERAGE_SHORTFALL,
  REACH_IELTS_SHORTFALL,
  SAFETY_AVERAGE_MARGIN,
  parseIeltsOverall,
  tierProgram,
  tierPrograms,
  type Applicant,
} from './tiers.ts';
import type { Program } from './types.ts';

function program(overrides: Partial<Program> = {}): Program {
  return {
    slug: 'example-msc', university: '示例大学', name: 'MSc Example', city: null, degreeLevel: '授课型硕士',
    field: '计算机与数据', duration: null, minimumMark: 75, non211MinimumMark: null, requiresCognate: false,
    prerequisites: [], englishRequirement: 'IELTS 6.5，单项不低于 6.0', academicRequirement: null, academicSourceUrl: null, deadlines: [],
    source: { id: 's', title: 't', url: 'https://example.edu/msc', excerpt: '', verifiedAt: null, status: '待核验' },
    dataStatus: '待核验',
    universityId: null,
    country: null,
    ...overrides,
  };
}

const applicant: Applicant = { average: 85, ielts: 7, institution: '985' };

test('the thresholds are named constants', () => {
  assert.equal(SAFETY_AVERAGE_MARGIN, 5);
  assert.equal(REACH_AVERAGE_SHORTFALL, 3);
  assert.equal(REACH_IELTS_SHORTFALL, 0.5);
});

test('a clear margin is a safety; a smaller one is steady', () => {
  assert.equal(tierProgram(applicant, program()).tier, '保底');
  assert.equal(tierProgram({ ...applicant, average: 79.9 }, program()).tier, '稳妥');
  assert.equal(tierProgram({ ...applicant, average: 80 }, program()).tier, '保底');
});

test('a small shortfall on the average or the IELTS overall is a reach', () => {
  assert.equal(tierProgram({ ...applicant, average: 73 }, program()).tier, '冲刺');
  assert.equal(tierProgram({ ...applicant, average: 72 }, program()).tier, '冲刺');
  assert.equal(tierProgram({ ...applicant, average: 71.9 }, program()).tier, '不满足');
  assert.equal(tierProgram({ ...applicant, ielts: 6 }, program()).tier, '冲刺');
  assert.equal(tierProgram({ ...applicant, ielts: 5.5 }, program()).tier, '不满足');
});

test('two shortfalls are not met', () => {
  assert.equal(tierProgram({ ...applicant, average: 73, ielts: 6 }, program()).tier, '不满足');
});

test('a program with nothing comparable is not tiered', () => {
  const result = tierProgram(applicant, program({ minimumMark: null, englishRequirement: null }));
  assert.equal(result.tier, null);
});

test('a text-only English requirement is flagged, not judged', () => {
  const result = tierProgram(applicant, program({ englishRequirement: '雅思要求见学院页面' }));
  assert.equal(result.tier, '保底');
  assert.deepEqual(result.confirm, [{ kind: 'english', label: '语言要求', url: 'https://example.edu/msc' }]);
});

test('a recommended score is shown, never compared', () => {
  const result = tierProgram({ ...applicant, ielts: 6 }, program({ englishRequirement: '建议雅思 7.5（非最低要求）' }));
  assert.equal(result.tier, '保底');
  assert.equal(result.confirm[0].kind, 'english');
});

test('an overseas or unknown institution is not compared on the academic threshold', () => {
  for (const institution of ['overseas', 'unknown'] as const) {
    const result = tierProgram({ ...applicant, institution }, program());
    assert.equal(result.tier, '稳妥', institution); // only the IELTS was compared
    assert.equal(result.confirm[0].kind, 'academic');
  }
});

test('a 双非 school is compared on the non-211 threshold only', () => {
  const withBoth = program({ minimumMark: 80, non211MinimumMark: 85 });
  assert.equal(tierProgram({ ...applicant, institution: 'other', average: 88 }, withBoth).tier, '稳妥');
  assert.equal(tierProgram({ ...applicant, institution: 'other', average: 83 }, withBoth).tier, '冲刺');
  const only211 = program({ minimumMark: 80, non211MinimumMark: null });
  const result = tierProgram({ ...applicant, institution: 'other', average: 99 }, only211);
  assert.equal(result.confirm[0].kind, 'academic');
  assert.equal(result.tier, '稳妥'); // the 985/211 threshold is never applied to a 双非 school
});

test('a missing score on the applicant side is not a shortfall', () => {
  const result = tierProgram({ ...applicant, ielts: null }, program());
  assert.equal(result.tier, '保底');
  assert.equal(result.confirm[0].kind, 'english');
});

test('IELTS overall is read only from the minimum form', () => {
  assert.equal(parseIeltsOverall('IELTS 6.5，单项不低于 6.0'), 6.5);
  assert.equal(parseIeltsOverall('IELTS 7.0；TOEFL iBT 100'), 7);
  assert.equal(parseIeltsOverall('建议雅思 7.5（非最低要求）'), null);
  assert.equal(parseIeltsOverall('TOEFL iBT 90'), null);
  assert.equal(parseIeltsOverall(null), null);
});

test('the result page groups tiers and counts what is not collected in the target field', () => {
  const programs = [
    program({ slug: 'a' }),
    program({ slug: 'b', minimumMark: null, englishRequirement: null }),
    program({ slug: 'c', minimumMark: null, englishRequirement: null, field: '商科与金融' }),
  ];
  const grouped = tierPrograms(applicant, programs, '计算机与数据');
  assert.deepEqual(grouped.tiers['保底'].map(r => r.program.slug), ['a']);
  assert.deepEqual(grouped.notCollected.map(p => p.slug), ['b']);
  assert.equal(grouped.notCollectedCount, 1);
  assert.equal('信息不足' in grouped.tiers, false);
});
