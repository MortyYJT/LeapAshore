"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { isAssessmentComplete, toApplicant } from "@/lib/assess";
import { useProfile } from "@/lib/hooks/useProfile";
import { usePortfolio } from "@/lib/hooks/usePortfolio";
import { addToDraft, readDraft, removeFromDraft, writeDraft } from "@/lib/portfolio-draft";
import { tierProgram } from "@/lib/tiers";
import type { PortfolioItem, PortfolioTier, Program } from "@/lib/types";

const BAND: Record<string, PortfolioTier> = { 保底: "保", 稳妥: "稳", 冲刺: "冲" };

/** How the program compares with the applicant's background, and adding it to the draft portfolio. */
export function ProgramActions({ program }: { program: Program }) {
  const profile = useProfile();
  const portfolio = usePortfolio();
  const [draft, setDraft] = useState<PortfolioItem[] | null>(null);
  const [picking, setPicking] = useState(false);

  useEffect(() => {
    if (draft !== null || portfolio.loading) return;
    setDraft(readDraft(sessionStorage) ?? portfolio.data ?? []);
  }, [draft, portfolio.loading, portfolio.data]);

  const complete = profile.data ? isAssessmentComplete(profile.data) : false;
  const result = profile.data && complete ? tierProgram(toApplicant(profile.data), program) : null;
  const band = result?.tier && result.tier !== "不满足" ? BAND[result.tier] : null;
  const chosen = draft?.find((r) => r.programSlug === program.slug) ?? null;
  const update = (next: PortfolioItem[]) => {
    setDraft(next);
    writeDraft(sessionStorage, next);
  };
  const add = (tier: PortfolioTier, needsReview: boolean) =>
    draft && update(addToDraft(draft, { programSlug: program.slug, program: { university: program.university, nameEn: program.name }, tier, needsReview }));

  return (
    <section className="panel panel-pad" aria-labelledby="fit-h">
      <h2 id="fit-h" style={{ marginBottom: 8 }}>和你的背景比</h2>
      {!profile.data && profile.loading && <p className="muted" style={{ margin: 0 }}>正在读取你的背景…</p>}
      {profile.data && !complete && (
        <p className="muted" style={{ margin: 0 }}>
          背景还没填完。<Link href="/assess">完成背景测评</Link>后，这里会按收录的要求比较。
        </p>
      )}
      {result && (
        <>
          <p style={{ margin: "0 0 4px", fontSize: 30, lineHeight: "36px", fontWeight: 600 }}>{result.tier ?? "未分档"}</p>
          <p className="muted" style={{ margin: "0 0 12px" }}>
            {result.tier ? "按已收录的要求比较，不是录取概率。" : "没有能和你的背景比较的要求，所以不分档。"}
          </p>
          {result.confirm.map((c) => (
            <p className="small" key={c.kind} style={{ margin: "6px 0 0" }}>
              <span className="pill pill-neutral">去官网确认</span> {c.label}
            </p>
          ))}
        </>
      )}
      <div className="toolbar" style={{ marginTop: 16 }}>
        {chosen ? (
          <>
            <button type="button" className="btn btn-secondary" aria-pressed onClick={() => draft && update(removeFromDraft(draft, program.slug))}>
              已加入 · {chosen.tier}
            </button>
            <Link className="btn btn-text" href="/portfolio">去确认组合</Link>
          </>
        ) : band ? (
          <button type="button" className="btn btn-primary" disabled={!draft} onClick={() => add(band, false)}>
            加入选校组合
          </button>
        ) : picking ? (
          <div className="seg" role="group" aria-label="选择档位">
            {(["冲", "稳", "保"] as const).map((b) => (
              <button key={b} type="button" onClick={() => add(b, true)}>{b}</button>
            ))}
          </div>
        ) : (
          <button type="button" className="btn btn-primary" disabled={!draft} onClick={() => setPicking(true)}>
            加入，自选档位
          </button>
        )}
      </div>
    </section>
  );
}
