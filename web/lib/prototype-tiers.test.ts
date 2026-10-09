import { test } from 'node:test';
import assert from 'node:assert/strict';
import { assessProgram, assessRequirement, SAFETY_AVERAGE_MARGIN, REACH_AVERAGE_SHORTFALL, REACH_IELTS_SHORTFALL } from './prototype-tiers.ts';
import type { Background, Requirement } from '../prototype-fixtures/data.ts';
const base: Background = { institution: '示例大学', institutionTier: '985', average: 85, ielts: 7, major: '计算机' };
const rules: Requirement[] = [
  { kind: 'average', label: '均分', value: 80, quote: '示例', source: '#', verification: '待核验' },
  { kind: 'ielts', label: '雅思', value: 7, quote: '示例', source: '#', verification: '待核验' },
  { kind: 'major', label: '专业', value: '计算机', quote: '示例', source: '#', verification: '待核验' },
];
test('named thresholds', () => {
  assert.equal(SAFETY_AVERAGE_MARGIN, 5); assert.equal(REACH_AVERAGE_SHORTFALL, 3); assert.equal(REACH_IELTS_SHORTFALL, 0.5);
});
test('safety at exactly five above; match below boundary', () => {
  assert.equal(assessProgram(base, rules).tier, '保底');
  assert.equal(assessProgram({ ...base, average: 84.99 }, rules).tier, '匹配');
  assert.equal(assessProgram({ ...base, average: 80 }, rules).tier, '匹配');
});
test('reach at exactly three points short; reject beyond', () => {
  assert.equal(assessProgram({ ...base, average: 77 }, rules).tier, '冲刺');
  assert.equal(assessProgram({ ...base, average: 76.99 }, rules).tier, '不满足');
});
test('reach at exactly half an IELTS point short; reject beyond', () => {
  const result = assessProgram({ ...base, ielts: 6.5 }, rules);
  assert.equal(result.tier, '冲刺'); assert.match(result.suggestions[0], /0.5.*匹配/);
  assert.equal(assessProgram({ ...base, ielts: 6.49 }, rules).tier, '不满足');
});
test('two failed requirements and wrong major cannot be reach', () => {
  assert.equal(assessProgram({ ...base, average: 79, ielts: 6.5 }, rules).tier, '不满足');
  assert.equal(assessProgram({ ...base, major: '商科' }, rules).tier, '不满足');
});
test('one unknown prevents match or safety, including with a small shortfall', () => {
  assert.equal(assessProgram({ ...base, major: null }, rules).tier, '信息不足');
  assert.equal(assessProgram({ ...base, major: null, average: 79 }, rules).tier, '信息不足');
  assert.equal(assessProgram(base, rules.map(r => r.kind === 'major' ? { ...r, value: null } : r)).tier, '信息不足');
});
test('known disqualifications take precedence over unknown', () => {
  assert.equal(assessProgram({ ...base, average: 70, major: null }, rules).tier, '不满足');
  assert.equal(assessProgram({ ...base, average: 79, ielts: 6.5, major: null }, rules).tier, '不满足');
});
test('requirement outcomes preserve unknown, shortfall and not met', () => {
  assert.deepEqual(assessRequirement({ ...base, ielts: 6.5 }, rules[1]), { status: 'short', shortfall: 0.5 });
  assert.equal(assessRequirement({ ...base, major: '教育' }, rules[2]).status, 'not-met');
  assert.equal(assessRequirement({ ...base, average: NaN }, rules[0]).status, 'unknown');
  assert.equal(assessRequirement({ ...base, major: '' }, rules[2]).status, 'unknown');
});
test('empty requirement set is unknown, never a match', () => {
  assert.equal(assessProgram(base, []).tier, '信息不足');
});

test('shortfalls just outside boundaries must not round into reach', () => {
  assert.equal(assessProgram({ ...base, average: 76.99999 }, rules).tier, '不满足');
  assert.equal(assessProgram({ ...base, ielts: 6.49999 }, rules).tier, '不满足');
});
