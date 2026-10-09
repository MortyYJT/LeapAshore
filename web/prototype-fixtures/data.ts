import cricos from './cricos-courses.json';

export type Verification = '待核验' | '机器核对' | '人工已核验';
export type Requirement = {
  kind: 'average' | 'ielts' | 'major';
  label: string;
  value: number | string | null;
  quote: string;
  source: '#';
  verification: Verification;
};
export type InstitutionTier = '985' | '211' | '其他';
export type Background = {
  institution: string;
  institutionTier: InstitutionTier | null;
  average: number | null;
  major: string | null;
  ielts: number | null;
};
export const courses = cricos.courses;
export type Course = (typeof courses)[number];
export const attribution = '数据来源：CRICOS（澳大利亚教育部），CC BY 2.5 AU';
export const fields = ['计算机与信息技术', '商科', '教育'];
export const chineseRules: Record<InstitutionTier, number> = { '985': 0, '211': 2, '其他': 5 };
const averages = [85, 80, 78, 75, 83, 82, 76, 80, 77];
const languages = [7, 6.5, 6.5, 7.5, 7, 6.5, 6.5, 6.5, 7.5];
export function requirements(course: Course, institutionTier: InstitutionTier | null = '985'): Requirement[] {
  const index = courses.indexOf(course);
  const average = institutionTier ? averages[index] + chineseRules[institutionTier] : null;
  const major = course['Field of Education 1 Broad Field'].startsWith('02') ? fields[0] : course['Field of Education 1 Broad Field'].startsWith('08') ? fields[1] : fields[2];
  return [
    { kind: 'average', label: '本科加权均分', value: average, quote: '示例：本科加权均分应达到所列门槛；211 院校加 2 分，其他院校加 5 分。', source: '#', verification: '待核验' },
    { kind: 'ielts', label: '雅思总分', value: languages[index], quote: '示例：雅思总分应达到所列门槛。', source: '#', verification: '机器核对' },
    { kind: 'major', label: '本科专业领域', value: index === 5 ? null : major, quote: index === 5 ? '示例：专业领域要求尚未录入。' : '示例：本科专业须属于所列领域。', source: '#', verification: '人工已核验' },
  ];
}
export const conversations = [
  { title: '项目库证据', question: '这个项目的雅思要求是多少？', answer: '示例项目要求雅思总分 7。下方引文展示项目库证据；这不是已核实的真实招生要求。', quote: '示例：雅思总分应达到 7。', links: ['示例出处'], verification: '待核验' },
  { title: '网络检索', question: '去澳大利亚前怎样找住宿？', answer: '示例回答：可以先了解校内住宿和租房选择，再由顾问协助核实具体信息。', quote: '来自网络检索，未经官方核验，仅供参考', links: ['示例出处：检索结果一', '示例出处：检索结果二'], verification: '待核验' },
  { title: '暂时无法回答', question: '我的特殊转学经历如何认定？', answer: '现有资料不足以回答。问题已在此演示中记入待补问题，你可以联系顾问进一步讨论。', quote: '记入待补问题', links: [], verification: '待核验' },
] as const;
export const leads = [
  { name: '示例学生甲', contact: '微信：DEMO_A', time: '2026-10-10 16:30', background: '211 / 均分 82 / 雅思 6.5', channel: '留资表单' },
  { name: '示例学生乙', contact: '微信：DEMO_B', time: '2026-10-10 14:00', background: '985 / 均分 88 / 雅思 7', channel: '预约咨询' },
  { name: '示例学生丙', contact: '微信：DEMO_C', time: '2026-10-09 10:00', background: '其他 / 均分未知 / 雅思未知', channel: '留资表单' },
];
export const pendingQuestions = ['我的特殊转学经历如何认定？', '跨专业申请需要哪些补充材料？'];
export const slots = ['示例时段：周一 10:00', '示例时段：周三 14:00', '示例时段：周五 16:00'];
export const applicationStates = ['未提交', '已提交', '已获 offer', '被拒'];
export const sampleApplications = courses.slice(0, 4).map((course, index) => ({ code: course['CRICOS Course Code'], state: applicationStates[index] }));
