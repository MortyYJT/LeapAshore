"use client";

import { useMemo, useState } from "react";
import { assessAll } from "@/lib/eligibility";
import { PROGRAMS } from "@/lib/programs";
import type { PortfolioItem, PortfolioTier, Profile } from "@/lib/types";

const TIER_LABEL: Record<PortfolioTier, string> = {
  冲: "冲刺",
  稳: "匹配",
  保: "稳妥",
};

const TIER_CLASS: Record<PortfolioTier, string> = {
  冲: "tag-chong",
  稳: "tag-wen",
  保: "tag-bao",
};

interface Props {
  profile: Profile;
  onConfirm: (items: PortfolioItem[]) => void;
  onBack: () => void;
}

export default function PortfolioPicker({ profile, onConfirm, onBack }: Props) {
  const assessments = useMemo(() => assessAll(PROGRAMS, profile), [profile]);
  const [picked, setPicked] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(
      assessments.filter((a) => a.suggestedTier !== null).map((a) => [a.program.slug, true]),
    ),
  );

  const chosenCount = Object.values(picked).filter(Boolean).length;
  const anyUnverified = assessments.some((a) => a.basedOnUnverifiedData);

  function toggle(slug: string) {
    setPicked((prev) => ({ ...prev, [slug]: !prev[slug] }));
  }

  function confirm() {
    const items: PortfolioItem[] = assessments
      .filter((a) => picked[a.program.slug])
      .map((a) => ({
        programSlug: a.program.slug,
        // When the system cannot tier a program, fall back to 'steady' but flag it, so the
        // interface never presents it as a system recommendation.
        tier: (a.suggestedTier ?? "稳") as PortfolioTier,
        confirmed: true,
        needsReview: a.suggestedTier === null,
      }));
    onConfirm(items);
  }

  return (
    <div className="mx-auto w-full max-w-3xl px-5 py-8">
      <header className="mb-6">
        <h1 className="text-2xl font-extrabold">为你筛出的申请组合</h1>
        <p className="mt-2 text-sm leading-relaxed text-[var(--color-ink-soft)]">
          勾掉不想申的，确认后进入申请流程。
        </p>
      </header>

      {anyUnverified && (
        <div className="mb-6 rounded-2xl border-2 border-[var(--color-warn)] bg-[var(--color-warn-soft)] p-4">
          <p className="text-sm leading-relaxed text-[#9a6700]">
            ⚠️ 招生要求尚未逐条核验，提交前请以官网为准。
          </p>
        </div>
      )}

      <div className="grid gap-4">
        {assessments.map((a) => {
          const tier = a.suggestedTier;
          return (
            <article
              key={a.program.slug}
              className="card"
              style={{ borderColor: picked[a.program.slug] ? "var(--color-brand)" : undefined }}
            >
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-lg font-extrabold">{a.program.university}</h2>
                    {tier ? (
                      <span className={`tag ${TIER_CLASS[tier]}`}>{TIER_LABEL[tier]}</span>
                    ) : a.gapStatus === "存在门槛缺口" ? (
                      <span className="tag tag-muted">暂不推荐</span>
                    ) : (
                      <span className="tag tag-warn">待人工核验</span>
                    )}
                    <span
                      className={`tag ${
                        a.gapStatus === "满足基础门槛"
                          ? "tag-bao"
                          : a.gapStatus === "存在门槛缺口"
                            ? "tag-chong"
                            : "tag-warn"
                      }`}
                    >
                      {a.gapStatus}
                    </span>
                  </div>
                  <p className="mt-1 text-sm text-[var(--color-ink-soft)]">
                    {a.program.name} · {a.program.city} · {a.program.duration}
                  </p>
                </div>
                <button
                  className={`btn ${picked[a.program.slug] ? "btn-primary" : "btn-ghost"}`}
                  onClick={() => toggle(a.program.slug)}
                  disabled={a.gapStatus === "存在门槛缺口"}
                >
                  {picked[a.program.slug] ? "已加入" : tier === null ? "仍然加入" : "加入组合"}
                </button>
              </div>

              <ul className="mt-4 grid gap-1.5 text-sm text-[var(--color-ink-soft)]">
                {a.reasons.map((r) => (
                  <li key={r}>· {r}</li>
                ))}
              </ul>

              {a.risks.length > 0 && (
                <div className="mt-3 rounded-xl bg-[var(--color-surface)] p-3">
                  <div className="text-xs font-bold text-[var(--color-ink-soft)]">需要继续确认</div>
                  <ul className="mt-1 grid gap-1 text-sm">
                    {a.risks.map((r) => (
                      <li key={r}>! {r}</li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="mt-3 flex items-center gap-2 text-xs">
                <span className="tag tag-muted">来源 {a.program.source.status}</span>
                <a
                  className="text-[var(--color-brand-dark)] underline"
                  href={a.program.source.url}
                  target="_blank"
                  rel="noreferrer"
                >
                  {a.program.source.title} ↗
                </a>
              </div>
            </article>
          );
        })}
      </div>

      <footer className="sticky bottom-0 mt-8 flex items-center justify-between gap-4 border-t-2 border-[var(--color-line)] bg-[var(--color-surface)] py-4">
        <button className="btn btn-ghost" onClick={onBack}>
          返回修改背景
        </button>
        <button className="btn btn-primary min-w-[200px]" onClick={confirm} disabled={chosenCount === 0}>
          确认组合（{chosenCount} 个）并进入流程
        </button>
      </footer>
    </div>
  );
}
