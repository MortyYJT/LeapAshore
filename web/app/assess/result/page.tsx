"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { Button, Empty, Loading, Notice, SourceNote } from "@/components/ui";
import { fetchAllPrograms, fetchProgramPage } from "@/lib/api";
import { isAssessmentComplete, toApplicant } from "@/lib/assess";
import { useProfile } from "@/lib/hooks/useProfile";
import { usePortfolio } from "@/lib/hooks/usePortfolio";
import { addToDraft, readDraft, removeFromDraft, writeDraft } from "@/lib/portfolio-draft";
import { dataStatusLabel } from "@/lib/taxonomy";
import {
  REACH_AVERAGE_SHORTFALL,
  REACH_IELTS_SHORTFALL,
  SAFETY_AVERAGE_MARGIN,
  tierPrograms,
  type Tier,
  type TierResult,
} from "@/lib/tiers";
import type { PortfolioItem, PortfolioTier, Program } from "@/lib/types";

const SHOWN = 10;
const BAND: Record<Exclude<Tier, "不满足">, PortfolioTier> = { 保底: "保", 稳妥: "稳", 冲刺: "冲" };
const DEFINITION: Record<Tier, string> = {
  保底: `比较的要求全部满足，均分高出门槛 ${SAFETY_AVERAGE_MARGIN} 分以上`,
  稳妥: "比较的要求全部满足",
  冲刺: `只差一项：均分差 ${REACH_AVERAGE_SHORTFALL} 分以内，或雅思总分差 ${REACH_IELTS_SHORTFALL} 以内`,
  不满足: "其余情况；仍可加入组合，档位由你定",
};
const TIER_ORDER: Tier[] = ["保底", "稳妥", "冲刺", "不满足"];

const sign = (n: number) => `${n > 0 ? "+" : n < 0 ? "−" : "±"}${Math.abs(Math.round(n * 10) / 10)}`;

/**
 * The assessment result (spec program-tiering): every program in the target field that has a stated
 * requirement, tiered by how far the official requirements are met. Not an admission chance.
 */
export default function ResultPage() {
  const profile = useProfile();
  const portfolio = usePortfolio();
  const [programs, setPrograms] = useState<Program[] | null>(null);
  const [pending, setPending] = useState<{ programs: Program[]; total: number } | null>(null);
  const [readError, setReadError] = useState<string | null>(null);
  const [draft, setDraft] = useState<PortfolioItem[] | null>(null);
  const [country, setCountry] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const field = profile.data?.targetField ?? null;
  const complete = profile.data ? isAssessmentComplete(profile.data) : false;

  useEffect(() => {
    if (!field || !complete) return;
    let cancelled = false;
    Promise.all([
      fetchAllPrograms({ field, hasRequirements: true }),
      fetchProgramPage({ field, hasRequirements: false, limit: 6 }),
    ])
      .then(([stated, unstated]) => {
        if (cancelled) return;
        setPrograms(stated);
        setPending(unstated);
      })
      .catch((error: unknown) => !cancelled && setReadError(error instanceof Error ? error.message : "读取项目失败"));
    return () => {
      cancelled = true;
    };
  }, [field, complete]);

  // The draft starts as whatever is being edited in this tab, or else the saved portfolio.
  useEffect(() => {
    if (draft !== null || portfolio.loading) return;
    setDraft(readDraft(sessionStorage) ?? portfolio.data ?? []);
  }, [draft, portfolio.loading, portfolio.data]);

  const update = (next: PortfolioItem[]) => {
    setDraft(next);
    writeDraft(sessionStorage, next);
  };

  const tiered = useMemo(() => {
    if (!programs || !profile.data) return null;
    const visible = country ? programs.filter((p) => p.country === country) : programs;
    return tierPrograms(toApplicant(profile.data), visible, null);
  }, [programs, profile.data, country]);
  const countries = useMemo(
    () => [...new Set((programs ?? []).map((p) => p.country).filter((c): c is string => !!c))].sort((a, b) => a.localeCompare(b, "zh")),
    [programs],
  );

  if (profile.loading && !profile.data) return <Page><Loading what="你的背景" /></Page>;
  if (profile.error && !profile.data) return <Page><Notice error>没有读到你的背景（{profile.error}）。<button className="btn btn-text" onClick={profile.reload}>重试</button></Notice></Page>;
  if (!profile.data || !complete) {
    return (
      <Page>
        <Empty>
          背景还没填完，所以没法分档。<Link href="/assess">去完成背景测评</Link>
        </Empty>
      </Page>
    );
  }

  const inDraft = (slug: string) => draft?.find((r) => r.programSlug === slug) ?? null;
  const add = (program: Program, tier: PortfolioTier, needsReview: boolean) =>
    draft && update(addToDraft(draft, { programSlug: program.slug, program: { university: program.university, nameEn: program.name }, tier, needsReview }));
  const remove = (program: Program) => draft && update(removeFromDraft(draft, program.slug));
  const applicant = toApplicant(profile.data);

  return (
    <Page draftCount={draft?.length ?? 0}>
      <section className="panel section" aria-label="你的背景">
        <div className="strip">
          <Fact label="本科院校" value={profile.data.schoolName || "未填"} unit={tierWord(applicant.institution)} />
          <Fact label="专业" value={profile.data.major} />
          <Fact label="均分" value={String(profile.data.gpaScore)} unit={`/ ${profile.data.gpaScale}`} />
          <Fact label="英语" value={profile.data.englishScore} />
          <Fact label="方向" value={profile.data.targetField ?? "未填"} />
        </div>
      </section>
      {applicant.average === null && (
        <p className="muted section" style={{ marginBottom: 0 }}>
          你的均分不是百分制，系统不换算，所以均分门槛都列在“去官网确认”里。
        </p>
      )}
      {readError && <div className="section"><Notice error>项目读取失败（{readError}）。</Notice></div>}
      {!tiered && !readError && <div className="section"><Loading what="项目和要求" /></div>}
      {tiered && (
        <>
          {countries.length > 1 && (
            <div className="section toolbar">
              <label htmlFor="country" className="muted">国家和地区</label>
              <select id="country" className="select" style={{ width: 180 }} value={country} onChange={(e) => setCountry(e.target.value)}>
                <option value="">全部（{programs?.length ?? 0} 个项目）</option>
                {countries.map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            </div>
          )}
          {TIER_ORDER.map((tier) => {
            const rows = tiered.tiers[tier];
            const open = expanded.has(tier);
            return (
              <section className="section" key={tier} aria-labelledby={`t-${tier}`}>
                <div className="section-head">
                  <h2 id={`t-${tier}`}>
                    {tier}
                    <span className="count num">{rows.length}</span>
                  </h2>
                  <span className="muted small">{DEFINITION[tier]}</span>
                </div>
                <div className="panel rows">
                  {rows.length === 0 && <div className="row"><span className="muted">没有项目落在这一档。</span></div>}
                  {(open ? rows : rows.slice(0, SHOWN)).map((r) => (
                    <TierRow
                      key={r.program.slug}
                      result={r}
                      chosen={inDraft(r.program.slug)}
                      band={tier === "不满足" ? null : BAND[tier]}
                      onAdd={(band, review) => add(r.program, band, review)}
                      onRemove={() => remove(r.program)}
                    />
                  ))}
                  {rows.length > SHOWN && (
                    <div className="row">
                      <button className="btn btn-text" onClick={() => setExpanded((s) => new Set(s).add(tier))} hidden={open}>
                        显示全部 {rows.length} 个
                      </button>
                    </div>
                  )}
                </div>
              </section>
            );
          })}
          {tiered.notCollected.length > 0 && (
            <section className="section" aria-labelledby="uncomparable">
              <div className="section-head">
                <h2 id="uncomparable">
                  去官网确认<span className="count num">{tiered.notCollected.length}</span>
                </h2>
                <span className="muted small">收录了要求，但和你的背景比不了（例如只写了文字，或你考的不是雅思）</span>
              </div>
              <div className="panel rows">
                {(expanded.has("confirm") ? tiered.notCollected : tiered.notCollected.slice(0, SHOWN)).map((p) => (
                  <PendingRow key={p.slug} program={p} chosen={inDraft(p.slug)} onAdd={(band) => add(p, band, true)} onRemove={() => remove(p)} />
                ))}
                {tiered.notCollected.length > SHOWN && !expanded.has("confirm") && (
                  <div className="row">
                    <button className="btn btn-text" onClick={() => setExpanded((s) => new Set(s).add("confirm"))}>
                      显示全部 {tiered.notCollected.length} 个
                    </button>
                  </div>
                )}
              </div>
            </section>
          )}
          {pending && (
            <section className="section" aria-labelledby="not-collected">
              <div className="section-head">
                <h2 id="not-collected">
                  要求未收录<span className="count num">{pending.total}</span>
                </h2>
                <Link className="btn btn-text" href={`/programs?field=${encodeURIComponent(field ?? "")}`}>
                  在项目库查看全部
                </Link>
              </div>
              <p className="muted" style={{ margin: "-4px 0 12px" }}>
                这些项目还没有收录录取要求，不参与分档。可以加进组合，档位由你自己定，系统会标明它没有被分档。
              </p>
              <div className="panel rows">
                {pending.programs.length === 0 && <div className="row"><span className="muted">这个方向的项目都已收录要求。</span></div>}
                {pending.programs.map((p) => (
                  <PendingRow key={p.slug} program={p} chosen={inDraft(p.slug)} onAdd={(band) => add(p, band, true)} onRemove={() => remove(p)} />
                ))}
              </div>
            </section>
          )}
        </>
      )}
    </Page>
  );
}

function tierWord(institution: ReturnType<typeof toApplicant>["institution"]): string {
  return { "985": "· 985", "211": "· 211", other: "· 双非", overseas: "· 海外", unknown: "· 层次未知" }[institution];
}

function Page({ children, draftCount }: { children: React.ReactNode; draftCount?: number }) {
  return (
    <>
      <main className="page">
        <div className="title-row">
          <div>
            <h1>测评结果</h1>
            <p className="lede">
              按已收录的官方要求比较你的背景。分档说明满足了几项要求，<strong>不是录取概率</strong>。
            </p>
          </div>
          <div className="toolbar">
            <Link className="btn btn-secondary" href="/assess">
              修改背景
            </Link>
            <Link className="btn btn-primary" href="/portfolio">
              {draftCount ? `去选校（已加 ${draftCount} 个）` : "去选校"}
            </Link>
          </div>
        </div>
        {children}
      </main>
      <SourceNote>
        要求摘自各校官网页面：“自动标注”表示程序已对照官网原文核对，“未核对”表示还没核对过，两者都还没有人工核对，申请前请以官网为准。澳洲项目事实来自 CRICOS（澳大利亚教育部，CC BY 2.5 AU）；院校层次来自教育部《全国高等学校名单》。
      </SourceNote>
    </>
  );
}

function Fact({ label, value, unit }: { label: string; value: string; unit?: string }) {
  return (
    <div>
      <div className="label">{label}</div>
      <div className="value">
        {value} {unit && <span className="unit">{unit}</span>}
      </div>
    </div>
  );
}

function ProgramName({ program }: { program: Program }) {
  return (
    <div className="two-line">
      <Link className="l1" href={`/programs/${encodeURIComponent(program.slug)}`}>
        {program.name ?? "未知"}
      </Link>
      <div className="l2">
        {program.university}
        {program.country ? ` · ${program.country}` : ""}
      </div>
    </div>
  );
}

function TierRow({
  result,
  chosen,
  band,
  onAdd,
  onRemove,
}: {
  result: TierResult;
  chosen: PortfolioItem | null;
  band: PortfolioTier | null;
  onAdd: (band: PortfolioTier, needsReview: boolean) => void;
  onRemove: () => void;
}) {
  const { program, checks, confirm } = result;
  const academic = checks.find((c) => c.kind === "academic");
  const english = checks.find((c) => c.kind === "english");
  return (
    <div className="row tier-row">
      <ProgramName program={program} />
      <div className="cmp">
        {academic && (
          <div>
            均分门槛 <b className="num">{academic.required}</b> · 你 <b className="num">{academic.actual}</b> ·{" "}
            <span className={`num${academic.shortfall > 0 ? " negative" : ""}`}>{sign(-academic.shortfall)}</span>
          </div>
        )}
        {english && (
          <div>
            雅思 <b className="num">{english.required}</b> · 你 <b className="num">{english.actual}</b>
          </div>
        )}
        <div>
          <a className="muted" href={program.source.url} target="_blank" rel="noreferrer">
            官网
          </a>{" "}
          · {dataStatusLabel(program.dataStatus)}
        </div>
      </div>
      <div className="notes">
        {confirm.length > 0 && (
          <>
            <b>去官网确认 {confirm.length} 项</b>：{confirm.map((c) => c.label).join("、")}
          </>
        )}
      </div>
      <div style={{ textAlign: "right" }}>
        {chosen ? (
          <Button small aria-pressed onClick={onRemove}>
            已加入 · {chosen.tier}
          </Button>
        ) : band ? (
          <Button small variant="primary" onClick={() => onAdd(band, false)}>
            加入组合
          </Button>
        ) : (
          <BandPicker onPick={(b) => onAdd(b, true)} />
        )}
      </div>
    </div>
  );
}

function PendingRow({
  program,
  chosen,
  onAdd,
  onRemove,
}: {
  program: Program;
  chosen: PortfolioItem | null;
  onAdd: (band: PortfolioTier) => void;
  onRemove: () => void;
}) {
  return (
    <div className="row pending-row">
      <ProgramName program={program} />
      <div className="muted small hide-phone">{program.duration ?? "学制未收录"}</div>
      <div style={{ textAlign: "right" }}>
        {chosen ? (
          <Button small aria-pressed onClick={onRemove}>
            {chosen.tier} · 未分档
          </Button>
        ) : (
          <BandPicker onPick={onAdd} />
        )}
      </div>
    </div>
  );
}

/** An untiered program is added only after the applicant picks its band (spec application-portfolio). */
function BandPicker({ onPick }: { onPick: (band: PortfolioTier) => void }) {
  const [open, setOpen] = useState(false);
  if (!open)
    return (
      <Button small onClick={() => setOpen(true)}>
        加入，自选档位
      </Button>
    );
  return (
    <div className="seg" role="group" aria-label="选择档位">
      {(["冲", "稳", "保"] as const).map((b) => (
        <button key={b} type="button" onClick={() => onPick(b)}>
          {b}
        </button>
      ))}
    </div>
  );
}
