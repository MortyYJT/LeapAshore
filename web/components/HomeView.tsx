"use client";

import { UNKNOWN, toProgramLabel } from "@/lib/programs-source";
import { roadmapProgress } from "@/lib/roadmap";
import type { PortfolioItem, Profile, Roadmap } from "@/lib/types";

const TIER_CLASS: Record<string, string> = { 冲: "tag-chong", 稳: "tag-wen", 保: "tag-bao" };

interface Props {
  profile: Profile;
  roadmap: Roadmap;
  portfolio: PortfolioItem[];
  onGoFlow: () => void;
}

export default function HomeView({ profile, roadmap, portfolio, onGoFlow }: Props) {
  const { done, total } = roadmapProgress(roadmap);
  const current =
    roadmap.phases.find((p) => p.status === "overdue") ??
    roadmap.phases.find((p) => p.status === "in_progress") ??
    roadmap.phases.find((p) => p.status === "pending");

  const schoolLabel =
    profile.schoolOrigin === "海外"
      ? profile.overseasBand ?? "海外院校"
      : profile.domesticTier
        ? `${profile.domesticTier}${profile.schoolName ? ` · ${profile.schoolName}` : ""}`
        : "未填写";

  return (
    <div className="grid gap-6">
      <section className="card">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-extrabold">你的申请进度</h1>
            <p className="mt-1 text-sm text-[var(--color-ink-soft)]">
              目标 {profile.intake} 入学 · {profile.targetDegree} · {profile.targetField}
            </p>
          </div>
          <div className="text-right">
            <div className="text-3xl font-extrabold text-[var(--color-brand-dark)]">
              {done}/{total}
            </div>
            <div className="text-xs text-[var(--color-ink-soft)]">材料项已完成</div>
          </div>
        </div>

        <div className="progress-track mt-4">
          <div className="progress-fill" style={{ width: `${total ? (done / total) * 100 : 0}%` }} />
        </div>

        {current && (
          <div className="mt-5 rounded-xl bg-[var(--color-surface)] p-4">
            <div className="text-xs font-bold text-[var(--color-ink-soft)]">现在应该做</div>
            <div className="mt-1 text-lg font-extrabold">{current.title}</div>
            <p className="mt-1 text-sm text-[var(--color-ink-soft)]">{current.detail}</p>
            <button className="btn btn-primary mt-3" onClick={onGoFlow}>
              进入流程进度
            </button>
          </div>
        )}
      </section>

      <section className="grid gap-4 md:grid-cols-2">
        <article className="card" data-testid="home-portfolio">
          <h2 className="text-sm font-bold text-[var(--color-ink-soft)]">申请组合</h2>
          {portfolio.length === 0 ? (
            <p className="mt-2 text-sm text-[var(--color-ink-soft)]">还没有选定项目。</p>
          ) : (
            <ul className="mt-3 grid gap-2">
              {/*
                The program comes off the row the server sent, not out of `web/lib/programs.ts`: a
                program the constants array does not carry used to render as its bare slug. A row the
                route could not resolve renders the marker for both halves rather than a blank, which
                is what a `""` would say — that the program has no institution, or no name.
              */}
              {portfolio.map((item) => {
                const university = item.program?.university ?? UNKNOWN;
                const name = toProgramLabel(item.program) ?? UNKNOWN;
                return (
                  <li key={item.programSlug} className="flex items-center gap-2 text-sm">
                    <span className={`tag ${TIER_CLASS[item.tier]}`}>{item.tier}</span>
                    <span className="font-semibold">{`${university} · ${name}`}</span>
                  </li>
                );
              })}
            </ul>
          )}
        </article>

        <article className="card">
          <h2 className="text-sm font-bold text-[var(--color-ink-soft)]">申请档案</h2>
          <dl className="mt-3 grid gap-1.5 text-sm">
            <div className="flex justify-between gap-4">
              <dt className="text-[var(--color-ink-soft)]">院校</dt>
              <dd className="font-semibold">{schoolLabel}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-[var(--color-ink-soft)]">专业</dt>
              <dd className="font-semibold">{profile.major || "未填写"}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-[var(--color-ink-soft)]">均分</dt>
              <dd className="font-semibold">
                {profile.gpaScore ? `${profile.gpaScore} / ${profile.gpaScale}` : "未填写"}
              </dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-[var(--color-ink-soft)]">语言</dt>
              <dd className="font-semibold">{profile.englishScore || "未提供"}</dd>
            </div>
          </dl>
        </article>
      </section>
    </div>
  );
}
