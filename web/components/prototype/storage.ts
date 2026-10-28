import { attribution, courses, requirements, type Background } from '../../prototype-fixtures/data';
import { assessProgram } from '../../lib/prototype-tiers';
export const storageKey = 'offerpilot-prototype-background';
export function readBackground(): Background | null {
  try {
    const raw = sessionStorage.getItem(storageKey);
    if (!raw) return null;
    const value = JSON.parse(raw);
    if (typeof value !== 'object' || value === null) return null;
    return {
      institution: typeof value.institution === 'string' ? value.institution : '',
      institutionTier: ['985', '211', '其他'].includes(value.institutionTier) ? value.institutionTier : null,
      average: typeof value.average === 'number' && value.average >= 0 && value.average <= 100 ? value.average : null,
      ielts: typeof value.ielts === 'number' && value.ielts >= 0 && value.ielts <= 9 ? value.ielts : null,
      major: typeof value.major === 'string' && value.major.trim() ? value.major : null,
    };
  } catch { return null; }
}
export function backgroundSummary() {
  const b = readBackground();
  if (!b) return 'OfferPilot 静态原型：尚未填写背景，结果未知。';
  const groups = courses.map(course => `${course['Course Name']}：${assessProgram(b, requirements(course, b.institutionTier)).tier}`);
  return `OfferPilot 静态原型背景摘要\n院校：${b.institution || '未知'}（${b.institutionTier ?? '未知'}）\n加权均分：${b.average ?? '未知'}\n专业：${b.major ?? '未知'}\n雅思总分：${b.ielts ?? '未知'}\n分档依据为示例数据，不是录取概率。\n${groups.join('\n')}\n${attribution}`;
}
