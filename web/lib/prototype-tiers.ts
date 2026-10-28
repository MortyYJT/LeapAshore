import type { Background, Requirement } from '../prototype-fixtures/data.ts';

export const SAFETY_AVERAGE_MARGIN = 5;
export const REACH_AVERAGE_SHORTFALL = 3;
export const REACH_IELTS_SHORTFALL = 0.5;
export type Tier = '冲刺' | '匹配' | '保底' | '不满足' | '信息不足';
export type Outcome = { status: 'met' | 'short' | 'not-met' | 'unknown'; shortfall?: number };
export function assessRequirement(background: Background, requirement: Requirement): Outcome {
  const actual = background[requirement.kind];
  if (actual === null || requirement.value === null || actual === '' ||
    (typeof actual === 'number' && !Number.isFinite(actual))) return { status: 'unknown' };
  if (requirement.kind === 'major') return { status: actual === requirement.value ? 'met' : 'not-met' };
  if (typeof actual !== 'number' || typeof requirement.value !== 'number' || !Number.isFinite(requirement.value)) return { status: 'unknown' };
  const shortfall = requirement.value - actual;
  return shortfall > 0 ? { status: 'short', shortfall } : { status: 'met' };
}
export function assessProgram(background: Background, requirements: Requirement[]): { tier: Tier; outcomes: Outcome[]; suggestions: string[] } {
  const outcomes = requirements.map(r => assessRequirement(background, r));
  const failed = outcomes.map((outcome, index) => ({ ...outcome, requirement: requirements[index] })).filter(o => o.status === 'short' || o.status === 'not-met');
  const reachable = failed.length === 1 && failed[0].status === 'short' && (
    (failed[0].requirement.kind === 'average' && failed[0].shortfall! <= REACH_AVERAGE_SHORTFALL) ||
    (failed[0].requirement.kind === 'ielts' && failed[0].shortfall! <= REACH_IELTS_SHORTFALL));
  const unknown = requirements.length === 0 || outcomes.some(o => o.status === 'unknown');
  let tier: Tier;
  if (failed.length && !reachable) tier = '不满足';
  else if (unknown) tier = '信息不足';
  else if (reachable) tier = '冲刺';
  else {
    const average = requirements.find(r => r.kind === 'average');
    tier = average && typeof average.value === 'number' && background.average !== null && background.average - average.value >= SAFETY_AVERAGE_MARGIN ? '保底' : '匹配';
  }
  const suggestions = tier === '冲刺' ? [`${failed[0].requirement.label}再提高 ${failed[0].shortfall} 即可进入匹配。`] : [];
  return { tier, outcomes, suggestions };
}
