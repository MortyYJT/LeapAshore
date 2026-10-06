"use client";

import { useMemo, useState } from "react";
import {
  DOMESTIC_TIER_OPTIONS,
  OVERSEAS_BAND_OPTIONS,
  recognizeDomesticSchool,
  type SchoolMatch,
} from "@/lib/schools";
import {
  BUDGET_OPTIONS,
  DEGREE_OPTIONS,
  EDUCATION_OPTIONS,
  GPA_SCALE_OPTIONS,
  INTAKE_OPTIONS,
  STUDY_AREAS,
} from "@/lib/taxonomy";
import type { DomesticTier, OverseasBand, Profile, SchoolOrigin } from "@/lib/types";

const STEP_TITLES = [
  "你现在的学历是？",
  "你的学校在哪里？",
  "你的本科院校",
  "你读的是什么专业？",
  "你的成绩情况",
  "你想申请什么学位？",
  "你想申请哪个方向？",
  "你的语言成绩",
  "每年预算大概多少？",
  "计划什么时候入学？",
];

interface Props {
  initialProfile: Profile;
  onComplete: (profile: Profile) => void;
  onCancel?: () => void;
}

export default function Onboarding({ initialProfile, onComplete }: Props) {
  const [step, setStep] = useState(0);
  const [p, setP] = useState<Profile>(initialProfile);
  /** Two input modes for the school step: type a name for detection, or pick a tier directly. */
  const [schoolMode, setSchoolMode] = useState<"name" | "tier">("name");

  const total = STEP_TITLES.length;
  const patch = (v: Partial<Profile>) => setP((prev) => ({ ...prev, ...v }));

  const match: SchoolMatch | null = useMemo(
    () => (p.schoolOrigin === "国内" && p.schoolName ? recognizeDomesticSchool(p.schoolName) : null),
    [p.schoolOrigin, p.schoolName],
  );

  const canNext = (() => {
    switch (step) {
      case 0:
        return p.educationLevel !== null;
      case 1:
        return p.schoolOrigin !== null;
      case 2:
        return p.schoolOrigin === "海外"
          ? p.overseasBand !== null
          : schoolMode === "name"
            ? p.schoolName.trim().length >= 2
            : p.domesticTier !== null;
      case 3:
        return p.major.trim().length >= 2;
      case 4:
        return p.gpaScore !== null && p.gpaScore > 0;
      case 5:
        return p.targetDegree !== null;
      case 6:
        return p.targetField !== null;
      case 7:
        return true; // 语言成绩可以留空（界面会提示这会降低判定精度）
      case 8:
        return p.annualBudgetCny !== null;
      default:
        return true;
    }
  })();

  function next() {
    // Write the detected tier back into the profile. Without it every later check degrades.
    if (step === 2 && p.schoolOrigin === "国内" && schoolMode === "name" && match) {
      patch({ domesticTier: match.tier, schoolName: match.name });
    }
    if (step < total - 1) {
      setStep(step + 1);
      return;
    }
    onComplete(p);
  }

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-2xl flex-col px-5 py-6">
      {/* 顶部：x/y + 绿色进度条 */}
      <header className="flex items-center gap-3">
        <span className="min-w-[52px] text-sm font-extrabold text-[var(--color-brand-dark)]">
          {step + 1}/{total}
        </span>
        <div className="progress-track">
          <div className="progress-fill" style={{ width: `${((step + 1) / total) * 100}%` }} />
        </div>
      </header>

      <main className="flex flex-1 flex-col justify-center py-10">
        <h1 className="mb-8 text-2xl font-extrabold leading-snug">{STEP_TITLES[step]}</h1>

        {step === 0 && (
          <div className="grid gap-3">
            {EDUCATION_OPTIONS.map((o) => (
              <button
                key={o.value}
                className={`option ${p.educationLevel === o.value ? "selected" : ""}`}
                onClick={() => {
                  patch({ educationLevel: o.value });
                  setStep(1);
                }}
              >
                <span>
                  {o.value}
                  {o.hint && <span className="hint">{o.hint}</span>}
                </span>
              </button>
            ))}
          </div>
        )}

        {step === 1 && (
          <div className="grid gap-3">
            {(["国内", "海外"] as SchoolOrigin[]).map((v) => (
              <button
                key={v}
                className={`option ${p.schoolOrigin === v ? "selected" : ""}`}
                onClick={() => {
                  patch({ schoolOrigin: v });
                  setStep(2);
                }}
              >
                <span>
                  {v === "国内" ? "国内院校" : "海外院校"}
                  <span className="hint">
                    {v === "国内" ? "按 985 / 211 / 双一流等层次判定" : "按 QS 区间自报"}
                  </span>
                </span>
              </button>
            ))}
          </div>
        )}

        {step === 2 && p.schoolOrigin === "海外" && (
          <div className="grid gap-3">
            {OVERSEAS_BAND_OPTIONS.map((o) => (
              <button
                key={o.value}
                className={`option ${p.overseasBand === o.value ? "selected" : ""}`}
                onClick={() => patch({ overseasBand: o.value as OverseasBand })}
              >
                {o.label}
              </button>
            ))}
            <p className="mt-2 text-sm leading-relaxed text-[var(--color-ink-soft)]">
              排名每年变化，系统不做自动判断，具体换算以学校官方要求为准。
            </p>
          </div>
        )}

        {step === 2 && p.schoolOrigin === "国内" && (
          <div>
            {schoolMode === "name" ? (
              <>
                <input
                  autoFocus
                  className="w-full rounded-xl border-2 border-[var(--color-line)] p-4 text-lg outline-none focus:border-[var(--color-brand)]"
                  placeholder="例如：北京邮电大学"
                  value={p.schoolName}
                  onChange={(e) => patch({ schoolName: e.target.value })}
                />
                {p.schoolName.trim().length >= 2 && (
                  <div className="mt-4">
                    {match ? (
                      <div className="card border-[var(--color-brand)] bg-[var(--color-brand-soft)]">
                        <div className="text-sm font-bold text-[var(--color-brand-dark)]">已自动识别</div>
                        <div className="mt-1 text-lg font-extrabold">
                          {match.name} · {match.tier}
                        </div>
                        <div className="mt-1 text-xs text-[var(--color-ink-soft)]">
                          依据教育部 985 / 211 公开名单，匹配方式：
                          {match.matchedBy === "alias"
                            ? "简称"
                            : match.matchedBy === "partial"
                              ? "校名 + 院系后缀"
                              : "校名"}
                        </div>
                      </div>
                    ) : (
                      <div className="card border-[var(--color-warn)] bg-[var(--color-warn-soft)]">
                        <div className="text-sm font-bold text-[#9a6700]">没有匹配到公开名单</div>
                        <p className="mt-1 text-sm text-[var(--color-ink-soft)]">
                          可能是双一流新增院校、港澳台或海外院校。请直接选择层次，避免系统猜错。
                        </p>
                        <button className="btn btn-ghost mt-3" onClick={() => setSchoolMode("tier")}>
                          手动选择层次
                        </button>
                      </div>
                    )}
                  </div>
                )}
                <button
                  className="mt-6 text-sm font-semibold text-[var(--color-ink-soft)] underline"
                  onClick={() => setSchoolMode("tier")}
                >
                  不想填校名？直接选层次
                </button>
              </>
            ) : (
              <div className="grid gap-3">
                {DOMESTIC_TIER_OPTIONS.map((o) => (
                  <button
                    key={o.value}
                    className={`option ${p.domesticTier === o.value ? "selected" : ""}`}
                    onClick={() => patch({ domesticTier: o.value as DomesticTier })}
                  >
                    <span>
                      {o.label}
                      {o.hint && <span className="hint">{o.hint}</span>}
                    </span>
                  </button>
                ))}
                <button
                  className="mt-2 text-sm font-semibold text-[var(--color-ink-soft)] underline"
                  onClick={() => setSchoolMode("name")}
                >
                  返回：填写校名自动识别
                </button>
              </div>
            )}
          </div>
        )}

        {step === 3 && (
          <div>
            <input
              autoFocus
              className="w-full rounded-xl border-2 border-[var(--color-line)] p-4 text-lg outline-none focus:border-[var(--color-brand)]"
              placeholder="例如：软件工程 / 市场营销 / 英语"
              value={p.major}
              onChange={(e) => patch({ major: e.target.value })}
            />
            <p className="mt-3 text-sm text-[var(--color-ink-soft)]">
              专业会影响「是否属于相关背景」的判断，部分项目要求本科为对应学科。
            </p>
          </div>
        )}

        {step === 4 && (
          <div className="grid gap-5">
            <div className="flex gap-3">
              <input
                autoFocus
                type="number"
                className="flex-1 rounded-xl border-2 border-[var(--color-line)] p-4 text-lg outline-none focus:border-[var(--color-brand)]"
                placeholder="均分 / GPA"
                value={p.gpaScore ?? ""}
                onChange={(e) => patch({ gpaScore: e.target.value === "" ? null : Number(e.target.value) })}
              />
              <select
                className="w-40 rounded-xl border-2 border-[var(--color-line)] p-4 text-base outline-none focus:border-[var(--color-brand)]"
                value={p.gpaScale ?? 100}
                onChange={(e) => patch({ gpaScale: Number(e.target.value) })}
              >
                {GPA_SCALE_OPTIONS.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </select>
            </div>
            {p.gpaScore !== null && p.gpaScore > 0 && p.gpaScale ? (
              <div className="card">
                <div className="text-sm text-[var(--color-ink-soft)]">归一化结果</div>
                <div className="text-2xl font-extrabold text-[var(--color-brand-dark)]">
                  {Math.min(100, Math.round((p.gpaScore / p.gpaScale) * 100))} / 100
                </div>
                <p className="mt-1 text-xs text-[var(--color-ink-soft)]">
                  各校对等值换算口径不同，这里只是便于比较的归一值，不是官方换算结论。
                </p>
              </div>
            ) : null}
          </div>
        )}

        {step === 5 && (
          <div className="grid gap-3">
            {DEGREE_OPTIONS.map((o) => (
              <button
                key={o.value}
                className={`option ${p.targetDegree === o.value ? "selected" : ""}`}
                onClick={() => patch({ targetDegree: o.value })}
              >
                <span>
                  {o.value}
                  <span className="hint">{o.hint}</span>
                </span>
              </button>
            ))}
          </div>
        )}

        {step === 6 && (
          <div className="grid grid-cols-2 gap-3">
            {STUDY_AREAS.map((a) => (
              <button
                key={a}
                className={`option !justify-center !px-3 text-center text-sm ${
                  p.targetField === a ? "selected" : ""
                }`}
                onClick={() => patch({ targetField: a })}
              >
                {a}
              </button>
            ))}
          </div>
        )}

        {step === 7 && (
          <div>
            <input
              autoFocus
              className="w-full rounded-xl border-2 border-[var(--color-line)] p-4 text-lg outline-none focus:border-[var(--color-brand)]"
              placeholder="例如：IELTS 6.5 / 托福 90 / 还没考"
              value={p.englishScore}
              onChange={(e) => patch({ englishScore: e.target.value })}
            />
            <p className="mt-3 text-sm leading-relaxed text-[var(--color-ink-soft)]">
              留空也可以继续。但没有语言成绩时，系统会把相关项目标记为
              <strong>「需要人工核验」</strong>，而不会替你猜。
            </p>
          </div>
        )}

        {step === 8 && (
          <div className="grid gap-3">
            {BUDGET_OPTIONS.map((o) => (
              <button
                key={o.value}
                className={`option ${p.annualBudgetCny === o.value ? "selected" : ""}`}
                onClick={() => patch({ annualBudgetCny: o.value })}
              >
                {o.label}
              </button>
            ))}
          </div>
        )}

        {step === 9 && (
          <div className="grid gap-3">
            {INTAKE_OPTIONS.map((v) => (
              <button
                key={v}
                className={`option ${p.intake === v ? "selected" : ""}`}
                onClick={() => patch({ intake: v })}
              >
                {v}
              </button>
            ))}
          </div>
        )}
      </main>

      <footer className="flex items-center justify-between gap-4 border-t-2 border-[var(--color-line)] pt-5">
        <button
          className="btn btn-ghost"
          onClick={() => setStep(Math.max(0, step - 1))}
          disabled={step === 0}
        >
          返回
        </button>
        <button className="btn btn-primary min-w-[160px]" onClick={next} disabled={!canNext}>
          {step === total - 1 ? "生成我的方案" : "继续"}
        </button>
      </footer>
    </div>
  );
}
