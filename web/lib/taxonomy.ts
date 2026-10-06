// Shared option lists for the profile fields.
//
// These live here rather than inside a component because onboarding and the profile editor both need
// them, and two copies would drift apart.

import type { DegreeLevel, EducationLevel, StudyArea } from "./types";

export const EDUCATION_OPTIONS: { value: EducationLevel; hint: string }[] = [
  { value: "高中", hint: "申请本科" },
  { value: "本科", hint: "申请硕士" },
  { value: "硕士", hint: "申请二硕或博士" },
  { value: "其他", hint: "" },
];

export const DEGREE_OPTIONS: { value: DegreeLevel; hint: string }[] = [
  { value: "授课型硕士", hint: "以课程为主，最常见" },
  { value: "研究型硕士", hint: "需要研究计划与导师" },
  { value: "本科", hint: "高中毕业后直接申请" },
  { value: "博士", hint: "需要研究计划与导师" },
];

export const STUDY_AREAS: StudyArea[] = [
  "计算机与数据",
  "商科与金融",
  "工程",
  "教育与社会科学",
  "生命科学",
  "医学与健康",
  "法律与犯罪学",
  "自然科学与数学",
  "人文与语言",
  "建筑规划与设计",
  "传媒艺术与音乐",
  "环境与农业",
];

export const INTAKE_OPTIONS = ["2027 S1", "2027 S2", "2028 S1", "2028 S2"];

export const GPA_SCALE_OPTIONS: { value: number; label: string }[] = [
  { value: 100, label: "百分制" },
  { value: 4, label: "4.0 制" },
  { value: 4.3, label: "4.3 制" },
  { value: 5, label: "5.0 制" },
  { value: 7, label: "7.0 制" },
];

export const BUDGET_OPTIONS: { value: number; label: string }[] = [
  { value: 200000, label: "20 万以下 / 年" },
  { value: 300000, label: "20–30 万 / 年" },
  { value: 400000, label: "30–40 万 / 年" },
  { value: 500000, label: "40–50 万 / 年" },
  { value: 800000, label: "50 万以上 / 年" },
];

export function labelOf<T extends string | number>(
  options: { value: T; label: string }[],
  value: T | null,
): string {
  if (value === null) return "";
  return options.find((o) => o.value === value)?.label ?? String(value);
}
