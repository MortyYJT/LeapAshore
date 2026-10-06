// Deterministic eligibility assessment and portfolio tiering.
//
// Tiering principles (important):
// - Assign an automatic tier only when the system actually has grounds for it.
// - With no grounds, always return 'needs manual review'. Never guess or emit a misleading tier.
// - Grade baselines come from unverified seed data, so the interface must show that status too.

import type { Program, Profile, PortfolioTier } from "./types";

const COGNATE_KEYWORDS = [
  "计算机", "软件", "信息", "数据", "人工智能", "网络", "电子", "自动化",
  "computer", "software", "data", "information", "computing",
];

/** Whether an undergraduate major counts as a cognate background. */
export function isCognate(major: string): boolean {
  const m = major.toLowerCase();
  return COGNATE_KEYWORDS.some((k) => m.includes(k));
}

/** Normalise a GPA on any scale to a 0-100 percentage. */
export function normalizeGpa(gpa: number, scale: number): number {
  if (!scale || scale <= 0) return 0;
  return Math.min(100, Math.round((gpa / scale) * 100));
}

export type GapStatus = "满足基础门槛" | "需要人工核验" | "存在门槛缺口";

export interface ProgramAssessment {
  program: Program;
  /** Suggested tier; null means the system cannot tier this program. */
  suggestedTier: PortfolioTier | null;
  gapStatus: GapStatus;
  /** Human-readable reasons explaining the conclusion. */
  reasons: string[];
  risks: string[];
  /** Whether this conclusion rests on unverified data. */
  basedOnUnverifiedData: boolean;
}

/** Extract the IELTS overall band from the user-entered English score. */
export function parseIelts(score: string): number | null {
  const m = /(?:ielts\s*)?(\d(?:\.\d)?)/i.exec(score);
  return m ? Number(m[1]) : null;
}

export function assessProgram(program: Program, profile: Profile): ProgramAssessment {
  const reasons: string[] = [];
  const risks: string[] = [];
  const unverified = program.dataStatus !== "已核验" || program.source.status !== "已核验";

  if (!profile.gpaScore || profile.gpaScore <= 0 || !profile.gpaScale || profile.gpaScale <= 0) {
    return {
      program,
      suggestedTier: null,
      gapStatus: "需要人工核验",
      reasons: ["尚未提供本科均分，无法进行门槛比较。"],
      risks: ["需要补充均分与满分制。"],
      basedOnUnverifiedData: unverified,
    };
  }

  const gpa = normalizeGpa(profile.gpaScore, profile.gpaScale);
  reasons.push(`均分归一为 ${gpa}/100。`);

  // Two groups are well defined in public guidance: Project 985 and Project 211 institutions, which
  // compare against the program baseline, and every other Chinese institution, which compares against
  // the non-211 baseline when the program records one.
  const tierKnown = profile.domesticTier === "985" || profile.domesticTier === "211";
  const isNon211 = profile.domesticTier === "双非" || profile.domesticTier === "专科";

  let threshold: number | null = null;
  if (tierKnown) {
    threshold = program.minimumMark;
    reasons.push(`按已录入的 ${program.university} 公开基线 ${program.minimumMark ?? "—"}% 比较。`);
  } else if (isNon211 && program.non211MinimumMark !== null) {
    threshold = program.non211MinimumMark;
    reasons.push(
      `该项目录入了中国非 211 院校的单独基线 ${program.non211MinimumMark}%，按此比较。`,
    );
  } else if (profile.schoolOrigin === "海外") {
    risks.push("海外本科的等值换算规则各校不同，需要按学校官方的 country-specific 要求人工核验。");
  } else {
    risks.push("该项目未录入与你的院校层次对应的公开基线，无法自动判定。");
  }

  const cognate = isCognate(profile.major);
  const prerequisiteRisk = program.requiresCognate && !cognate;
  if (prerequisiteRisk) {
    risks.push("该项目要求相关专业背景，当前本科专业可能不满足。");
  } else if (program.prerequisites.length > 0) {
    risks.push(`需逐项核对先修课：${program.prerequisites.join("、")}。`);
  }

  const ielts = parseIelts(profile.englishScore);
  const requiredIelts = /IELTS\s*(\d(?:\.\d)?)/i.exec(program.englishRequirement);
  let englishUnknown = true;
  if (requiredIelts && ielts !== null) {
    if (ielts < Number(requiredIelts[1])) {
      risks.push(`当前 IELTS ${ielts} 低于已录入的总分要求 ${requiredIelts[1]}。`);
      englishUnknown = false;
    } else if (program.englishRequirement.includes("单项") && !/单项/.test(profile.englishScore)) {
      risks.push("已录入要求包含单项分数，但你的成绩未说明单项，需要补充。");
    } else {
      englishUnknown = false;
    }
  } else {
    risks.push("语言要求尚未逐项核验，需按官方页面确认考试类型、总分与单项。");
  }

  if (threshold === null) {
    return {
      program,
      suggestedTier: null,
      gapStatus: "需要人工核验",
      reasons,
      risks,
      basedOnUnverifiedData: unverified,
    };
  }

  const gap = gpa - threshold;
  const hardGap = gap < 0 || prerequisiteRisk;
  const gapStatus: GapStatus = hardGap
    ? "存在门槛缺口"
    : englishUnknown || program.prerequisites.length > 0
      ? "需要人工核验"
      : "满足基础门槛";

  const suggestedTier: PortfolioTier | null = hardGap
    ? null
    : gap >= 12
      ? "保"
      : gap >= 4
        ? "稳"
        : "冲";

  if (suggestedTier === null) {
    reasons.push(`当前均分低于基线 ${threshold}%，不建议纳入申请组合。`);
  } else {
    reasons.push(`与基线相差 ${gap > 0 ? "+" : ""}${gap} 分，建议归入「${suggestedTier}」。`);
  }
  if (unverified) {
    risks.push("本结论建立在「待核验」的项目数据上，提交前必须以官网最新要求复核。");
  }

  return { program, suggestedTier, gapStatus, reasons, risks, basedOnUnverifiedData: unverified };
}

export function assessAll(programs: Program[], profile: Profile): ProgramAssessment[] {
  const order: Record<string, number> = { 保: 0, 稳: 1, 冲: 2 };
  return programs
    .filter(
      (p) =>
        (!profile.targetDegree || p.degreeLevel === profile.targetDegree) &&
        (!profile.targetField || p.field === profile.targetField),
    )
    .map((p) => assessProgram(p, profile))
    .sort((a, b) => {
      const ao = a.suggestedTier ? order[a.suggestedTier] : 9;
      const bo = b.suggestedTier ? order[b.suggestedTier] : 9;
      return ao - bo;
    });
}
