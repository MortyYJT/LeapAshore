"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { LoginPrompt, RequireAccount } from "@/components/auth/AuthProvider";
import { SampleTimeline } from "@/components/home/SampleTimeline";
import { DeadlineText } from "@/components/roadmap/DeadlineText";
import { drawnDeadlines, Timeline, type DeadlineMark } from "@/components/roadmap/Timeline";
import { LoadingPanel, Notice } from "@/components/ui";
import { uploadMaterial } from "@/lib/api";
import { beijingToday, deadlineOf } from "@/lib/deadlines";
import { useProfile } from "@/lib/hooks/useProfile";
import { usePortfolio } from "@/lib/hooks/usePortfolio";
import { useRoadmap } from "@/lib/hooks/useRoadmap";
import { intakeAnchor } from "@/lib/roadmap";
import { timelineOf, type Timeline as TimelineModel, type TimelinePhase } from "@/lib/roadmap-timeline";
import { verifiedMark } from "@/lib/taxonomy";

const md = (iso: string) => {
  const d = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  return `${d.getUTCMonth() + 1}月${d.getUTCDate()}日`;
};

/** The one sentence under the title: the fact the applicant most needs today. */
function headline(model: TimelineModel): string {
  if (!model.dated) {
    const current = model.current;
    return current ? `当前在「${current.title}」，还有 ${current.total - current.done} 项。` : "所有步骤都已完成。";
  }
  const late = model.phases.filter((p) => p.overdue);
  if (late.length > 0) {
    const left = late.reduce((n, p) => n + (p.total - p.done), 0);
    return `「${late[0].title}」${late.length > 1 ? `等 ${late.length} 个阶段` : ""}已过建议时间，还有 ${left} 项没完成。`;
  }
  const current = model.current;
  if (!current) return "所有步骤都已完成。";
  const left = current.total - current.done;
  return `当前在「${current.title}」，还有 ${left} 项，建议 ${current.end ? md(current.end) : "入学"} 前完成。`;
}

/**
 * The roadmap (spec application-roadmap): the main interface. In login mode a logged-out visitor sees the
 * sample roadmap and a login prompt; the applicant's own timeline needs an account (openspec account-login).
 */
export default function RoadmapPage() {
  return (
    <RequireAccount
      what="路线图"
      fallback={
        <main className="page">
          <div className="title-row">
            <div>
              <h1>申请路线图</h1>
              <p className="lede">下面是一位示例申请人的路线图。登录后，这里会按你的入学时间和选校组合排出你自己的。</p>
            </div>
          </div>
          <div className="section">
            <SampleTimeline />
          </div>
          <LoginPrompt what="你自己的路线图" />
        </main>
      }
      pending={
        <main className="page">
          <div className="title-row">
            <h1>申请路线图</h1>
          </div>
          <LoadingPanel what="路线图" />
        </main>
      }
    >
      <Roadmap />
    </RequireAccount>
  );
}

function Roadmap() {
  const profile = useProfile();
  const portfolio = usePortfolio();
  const roadmap = useRoadmap(profile.data);
  const [selected, setSelected] = useState<string | null>(null);
  const today = useMemo(() => new Date(), []);
  const drawn = useRef(false);

  const model = useMemo(() => (roadmap.roadmap ? timelineOf(roadmap.roadmap, today) : null), [roadmap.roadmap, today]);
  useEffect(() => {
    if (model && selected === null) setSelected(model.current?.id ?? model.phases[0]?.id ?? null);
  }, [model, selected]);
  useEffect(() => {
    if (model) drawn.current = true;
  });

  // The row's own date wins; otherwise the program's next collected deadline; a past one is 已截止
  // (openspec requirement-dates D3, D4). Decided at render time, so nothing stored can go stale.
  const todayIso = useMemo(() => beijingToday(today), [today]);
  const deadlines: DeadlineMark[] = (portfolio.data ?? []).map((r) => ({
    key: r.programSlug,
    label: `${r.program?.university ?? ""} ${r.program?.nameEn ?? r.programSlug}`.trim(),
    view: deadlineOf({ ...r, deadlines: r.collectedDeadlines }, todayIso),
  }));
  const phase = model?.phases.find((p) => p.id === selected) ?? null;
  const anchor = profile.data ? intakeAnchor(profile.data.intake) : null;
  // Without an intake nothing on the axis has a date, so the page shows one line and the way to fix it,
  // and keeps the current phase's checklist, which can be ticked without dates.
  const undatedPhase = model && !model.dated ? model.current ?? model.phases[0] ?? null : null;

  return (
    <main className="page">
      <div className="title-row">
        <div>
          <h1>申请路线图</h1>
          <p className="lede">{model ? headline(model) : " "}</p>
        </div>
        {anchor && (
          <div className="toolbar">
            <span className="muted">{`${anchor.getUTCFullYear()} 年 ${anchor.getUTCMonth() + 1} 月入学`}</span>
            <Link className="btn btn-secondary" href="/me">
              改入学时间
            </Link>
          </div>
        )}
      </div>

      {(profile.loading || roadmap.loading) && !model && <LoadingPanel what="路线图" />}
      {profile.error && !profile.data && <div className="section"><Notice error>没有读到你的背景（{profile.error}）。</Notice></div>}
      {roadmap.notice && <div className="section"><Notice>{roadmap.notice}</Notice></div>}
      {roadmap.syncError && <div className="section"><Notice error>{roadmap.syncError}</Notice></div>}
      {model && !model.dated && (
        <div className="stagger">
          <section className="panel panel-pad section roadmap-empty" aria-label="还没有入学时间">
            <p style={{ margin: 0 }}>填上入学时间，各阶段就会按它倒推出建议日期。</p>
            <Link className="btn btn-primary" href="/me">
              填入学时间
            </Link>
          </section>
          {undatedPhase && (
            <div className="section">
              <PhaseTasks key={undatedPhase.id} phase={undatedPhase} roadmap={roadmap} />
            </div>
          )}
        </div>
      )}

      {model && model.dated && (
        <div className="stagger">
          <section className="panel section" aria-labelledby="tl-h">
            <div className="panel-head">
              <h2 id="tl-h">从今天到入学</h2>
              <Legend overdue={model.phases.some((p) => p.overdue)} recorded={drawnDeadlines(deadlines).length > 0} />
            </div>
            <div style={{ padding: "20px 24px 12px" }}>
              <Timeline model={model} today={today} deadlines={deadlines} selected={selected} onSelect={setSelected} animate={!drawn.current} />
            </div>
          </section>

          {phase && (
            <div className="grid grid-8-4 section">
              <PhaseTasks key={phase.id} phase={phase} roadmap={roadmap} />
              <aside className="grid" style={{ gap: 16 }}>
                <section className="panel panel-pad" aria-labelledby="dates-h">
                  <h2 id="dates-h" style={{ marginBottom: 12 }}>这一阶段的日期</h2>
                  <dl className="kv">
                    <dt>建议开始</dt>
                    <dd className="num">
                      {phase.start ? md(phase.start) : "未排日期"}
                      <div className="small muted">系统建议 · 非官方日期</div>
                    </dd>
                    <dt>建议完成</dt>
                    <dd className="num">{phase.end ? md(phase.end) : "未排日期"}</dd>
                    <dt>官方截止</dt>
                    <dd>
                      <span className="hollow" />
                      见右侧各项目
                    </dd>
                  </dl>
                  {phase.overdue && <p className="negative small" style={{ margin: "12px 0 0" }}>已过建议时间</p>}
                </section>
                <section className="panel" aria-labelledby="dl-h">
                  <div className="panel-head">
                    <h2 id="dl-h">官方截止日期</h2>
                    <span className="muted num">{deadlines.length} 个项目</span>
                  </div>
                  <div className="rows">
                    {deadlines.length === 0 && (
                      <div className="row">
                        <span className="muted">
                          还没有选项目。<Link href="/tiers">去选校</Link>
                        </span>
                      </div>
                    )}
                    {deadlines.map((d) => (
                      <div className="row deadline-row" data-state={d.view.state} key={d.key} style={{ gridTemplateColumns: "minmax(0, 1fr) auto", gap: 12 }}>
                        <div className="two-line">
                          <Link className="l1" href={`/programs/${encodeURIComponent(d.key)}`}>{d.label}</Link>
                          {d.view.label && d.view.origin === "collected" && <div className="l2">{d.view.label}</div>}
                          {d.view.origin === "entered" && <div className="l2">组合里记录的日期</div>}
                        </div>
                        <div style={{ textAlign: "right" }}>
                          <DeadlineText view={d.view} showLabel={false} />
                        </div>
                      </div>
                    ))}
                  </div>
                </section>
              </aside>
            </div>
          )}
        </div>
      )}
    </main>
  );
}

function Legend({ overdue, recorded }: { overdue: boolean; recorded: boolean }) {
  return (
    <div className="legend" aria-label="图例">
      <span>
        <svg width="12" height="16" aria-hidden="true"><line x1="6" x2="6" y1="0" y2="16" stroke="var(--color-accent)" strokeWidth="1.5" /></svg>
        今天
      </span>
      <span>
        <svg width="16" height="12" aria-hidden="true"><rect width="16" height="12" rx="3" fill="var(--color-primary)" /></svg>
        当前阶段
      </span>
      <span>
        <svg width="10" height="16" aria-hidden="true"><line x1="5" x2="5" y1="0" y2="16" stroke="var(--color-muted)" strokeWidth="1.25" strokeDasharray="3 3" /></svg>
        系统建议 · 非官方日期
      </span>
      {recorded && (
        <span>
          <svg width="10" height="16" aria-hidden="true"><line x1="5" x2="5" y1="0" y2="16" stroke="var(--color-ink)" strokeWidth="2" /></svg>
          官方截止
        </span>
      )}
      <span>
        <span className="hollow" style={{ margin: 0 }} />
        未收录
      </span>
      {overdue && (
        <span>
          <svg width="8" height="8" aria-hidden="true"><circle cx="4" cy="4" r="3.5" fill="var(--color-negative)" /></svg>
          已过建议时间
        </span>
      )}
    </div>
  );
}

function PhaseTasks({ phase, roadmap }: { phase: TimelinePhase; roadmap: ReturnType<typeof useRoadmap> }) {
  const [uploads, setUploads] = useState<Record<string, string>>({});
  async function upload(materialKey: string, file: File | undefined) {
    if (!file) return;
    const taskId = roadmap.taskIdFor(materialKey);
    setUploads((u) => ({ ...u, [materialKey]: `正在上传 ${file.name}…` }));
    try {
      await uploadMaterial(file, { title: file.name, taskId });
      setUploads((u) => ({ ...u, [materialKey]: `已上传 ${file.name}，在「我的背景」的材料库里可以下载、归档和送审。` }));
    } catch (error: unknown) {
      setUploads((u) => ({ ...u, [materialKey]: `上传失败：${error instanceof Error ? error.message : "未知错误"}` }));
    }
  }
  return (
    <section className="panel swap" aria-labelledby="ph-h">
      <div className="panel-head">
        <div>
          <h2 id="ph-h">
            {phase.title}
            {phase.current ? "（当前阶段）" : ""}
          </h2>
          <p className="muted small" style={{ margin: "2px 0 0" }}>
            {phase.detail ? `${phase.detail} ` : ""}清单是系统建议的步骤，标了「依据」的才对应官方要求。
          </p>
        </div>
        <span className="num muted">
          {phase.done}/{phase.total} 项完成
        </span>
      </div>
      {phase.phase.tasks.length === 0 && <div className="task"><span /><span className="muted">这一阶段对你的背景没有要做的步骤。</span><span /></div>}
      {phase.phase.tasks.map((t) => {
        const failed = roadmap.failedTicks.has(t.materialId);
        // A tick needs the server's row for this step. On a first visit the rows are written and read
        // back first, so the box waits rather than taking a click that could not be saved.
        const ready = roadmap.taskIdFor(t.materialId) !== null;
        return (
          <div className={`task${t.done ? " done" : ""}`} key={t.materialId}>
            <input
              type="checkbox"
              id={`t-${t.materialId}`}
              checked={t.done}
              disabled={!ready}
              title={ready ? undefined : "正在准备，稍等一下就能勾选"}
              onChange={(e) => void roadmap.tick(t.materialId, e.target.checked)}
            />
            <div>
              <label className="t" htmlFor={`t-${t.materialId}`}>
                {t.label}
              </label>
              {t.detail && <div className="d">{t.detail}</div>}
              {t.source && (
                <div className="d">
                  依据：
                  <a className="link" href={t.source.url} target="_blank" rel="noreferrer">
                    {t.source.title}
                  </a>
                  {verifiedMark(t.source.status) && <> · {verifiedMark(t.source.status)}</>}
                </div>
              )}
              {failed && <div className="d negative" role="alert">这次勾选没有保存，已恢复原状。</div>}
              {uploads[t.materialId] && <div className="d" role="status">{uploads[t.materialId]}</div>}
            </div>
            <label className="btn btn-secondary btn-small" aria-disabled={!ready}>
              上传
              <input type="file" className="sr-only" disabled={!ready} onChange={(e) => void upload(t.materialId, e.target.files?.[0])} />
            </label>
          </div>
        );
      })}
    </section>
  );
}
