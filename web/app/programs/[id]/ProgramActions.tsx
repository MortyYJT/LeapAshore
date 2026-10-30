"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth/AuthProvider";
import { Loading } from "@/components/ui";
import { hasBasics, toApplicant } from "@/lib/assess";
import { useProfile } from "@/lib/hooks/useProfile";
import { usePortfolio } from "@/lib/hooks/usePortfolio";
import { addToDraft, readDraft, removeFromDraft, writeDraft } from "@/lib/portfolio-draft";
import { tierProgram } from "@/lib/tiers";
import type { PortfolioItem, PortfolioTier, Program } from "@/lib/types";

const BAND: Record<string, PortfolioTier> = { 保底: "保", 稳妥: "稳", 冲刺: "冲" };

/**
 * How the program compares with the applicant's background, and adding it to the draft portfolio.
 *
 * In login mode a logged-out visitor sees the 加入选校组合 button only; pressing it opens the login dialog,
 * and once logged in the inner component mounts with the session and finishes the add (openspec
 * account-login D11): with the band the tiers give, or by opening the band picker when they give none.
 */
export function ProgramActions({ program }: { program: Program }) {
  const { ready, gated, requireLogin } = useAuth();
  const [resume, setResume] = useState(false);
  if (!ready) return null;
  if (gated) {
    return (
      <section className="panel panel-pad" aria-labelledby="fit-h">
        <h2 id="fit-h" style={{ marginBottom: 8 }}>和你的背景比</h2>
        <p className="muted" style={{ margin: 0 }}>登录后，这里会按收录的要求和你的背景比较。</p>
        <div className="toolbar" style={{ marginTop: 16 }}>
          <button type="button" className="btn btn-primary" onClick={() => void requireLogin().then((ok) => ok && setResume(true))}>
            加入选校组合
          </button>
        </div>
      </section>
    );
  }
  return <Actions program={program} resumeAdd={resume} />;
}

function Actions({ program, resumeAdd }: { program: Program; resumeAdd: boolean }) {
  const profile = useProfile();
  const portfolio = usePortfolio();
  const [draft, setDraft] = useState<PortfolioItem[] | null>(null);
  const [picking, setPicking] = useState(false);
  const [pendingAdd, setPendingAdd] = useState(resumeAdd);

  useEffect(() => {
    if (draft !== null || portfolio.loading) return;
    setDraft(readDraft(sessionStorage) ?? portfolio.data ?? []);
  }, [draft, portfolio.loading, portfolio.data]);

  const complete = profile.data ? hasBasics(profile.data) : false;
  const result = profile.data && complete ? tierProgram(toApplicant(profile.data), program) : null;
  const band = result?.tier && result.tier !== "不满足" ? BAND[result.tier] : null;
  const chosen = draft?.find((r) => r.programSlug === program.slug) ?? null;
  const update = (next: PortfolioItem[]) => {
    setDraft(next);
    writeDraft(sessionStorage, next);
  };
  const add = (tier: PortfolioTier, needsReview: boolean) =>
    draft && update(addToDraft(draft, { programSlug: program.slug, program: { university: program.university, nameEn: program.name }, tier, needsReview }));

  // The add pressed before logging in, finished once the draft and the profile have loaded.
  useEffect(() => {
    if (!pendingAdd || draft === null || profile.loading) return;
    setPendingAdd(false);
    if (chosen) return;
    if (band) add(band, false);
    else setPicking(true);
  });

  return (
    <section className="panel panel-pad" aria-labelledby="fit-h">
      <h2 id="fit-h" style={{ marginBottom: 8 }}>和你的背景比</h2>
      {!profile.data && profile.loading && <Loading what="你的背景" />}
      {profile.data && !complete && (
        <p className="muted" style={{ margin: 0 }}>
          分档要的四项信息还没填全。<Link href="/tiers">先补信息</Link>后，这里会按收录的要求比较。
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
