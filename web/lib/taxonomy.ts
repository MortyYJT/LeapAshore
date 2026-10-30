// Shared option lists for the profile fields.
//
// These live here rather than inside a component because onboarding and the profile editor both need
// them, and two copies would drift apart.

import type {
  ApplicationStatus,
  DegreeLevel,
  EducationLevel,
  PortfolioTier,
  StudyArea,
} from "./types";

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

// Stored values and interface words are kept apart (PRD §7.7 rule 5): the API and the database keep the
// left-hand value, and every screen shows the right-hand words through the maps below.

/** The six application statuses, in the order a row moves through them. */
export const APPLICATION_STATUSES: { value: ApplicationStatus; label: string }[] = [
  { value: "considering", label: "考虑中" },
  { value: "applying", label: "申请中" },
  { value: "submitted", label: "已提交" },
  { value: "offered", label: "已获 offer" },
  { value: "rejected", label: "被拒" },
  { value: "excluded", label: "不考虑" },
];

/** A status this build does not know reads as the column's default, never as a later stage. */
export function applicationStatusLabel(status: string | null | undefined): string {
  return APPLICATION_STATUSES.find((s) => s.value === status)?.label ?? "考虑中";
}

/**
 * The mark a stored data status earns on screen: 已核对 for a page a person checked against the official
 * site, and nothing otherwise. Unchecked and machine-checked data are the default and carry no label;
 * a status this build does not know is never shown as checked.
 */
export function verifiedMark(status: string | null | undefined): string | null {
  return status === "已核验" ? "已核对" : null;
}

/** The stored one-character band and the tier name the interface shows for it. */
export const TIER_OF_BAND: Record<PortfolioTier, string> = { 保: "保底", 稳: "稳妥", 冲: "冲刺" };

/** A missing value, wherever it would otherwise render as an empty string or a zero. */
export const NOT_COLLECTED = "未收录";
