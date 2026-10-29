"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { Button, Loading, Notice, Pill, SourceNote } from "@/components/ui";
import { fetchProgramPage, replaceApplications } from "@/lib/api";
import { usePortfolio } from "@/lib/hooks/usePortfolio";
import { clearDraft, draftChanged, readDraft, removeFromDraft, setPrimary, setStatus, writeDraft } from "@/lib/portfolio-draft";
import { toApplicationRows } from "@/lib/programs-source";
import { APPLICATION_STATUSES, TIER_OF_BAND } from "@/lib/taxonomy";
import type { ApplicationStatus, PortfolioItem, Program } from "@/lib/types";

/**
 * The portfolio (spec application-portfolio): one row per program with its band, whether the system
 * tiered it, its official deadline, its status and the first-choice mark. Edits stay in the draft until
 * the applicant confirms; confirming replaces the stored portfolio whole.
 */
export default function PortfolioPage() {
  const saved = usePortfolio();
  const [draft, setDraft] = useState<PortfolioItem[] | null>(null);
  const [programs, setPrograms] = useState<Map<string, Program>>(new Map());
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedNote, setSavedNote] = useState<string | null>(null);

  useEffect(() => {
    if (draft !== null || saved.loading) return;
    setDraft(readDraft(sessionStorage) ?? saved.data ?? []);
  }, [draft, saved.loading, saved.data]);

  const ids = useMemo(() => (draft ?? []).map((r) => r.programSlug).filter((id) => !programs.has(id)), [draft, programs]);
  useEffect(() => {
    if (ids.length === 0) return;
    fetchProgramPage({ ids: ids.slice(0, 100), limit: 100 })
      .then(({ programs: found }) => setPrograms((prev) => new Map([...prev, ...found.map((p) => [p.slug, p] as const)])))
      .catch(() => undefined); // the rows still render from the portfolio's own program names
  }, [ids]);

  const update = (next: PortfolioItem[]) => {
    setDraft(next);
    setSavedNote(null);
    writeDraft(sessionStorage, next);
  };

  async function confirm() {
    if (!draft) return;
    setSaving(true);
    setSaveError(null);
    try {
      await replaceApplications(toApplicationRows(draft));
      clearDraft(sessionStorage);
      saved.reload();
      setDraft(null);
      setSavedNote(`已保存 ${draft.length} 个项目，路线图会按新组合显示截止日期。`);
    } catch (error: unknown) {
      setSaveError(`组合没有保存（${error instanceof Error ? error.message : "未知错误"}），改动还在，可以再试一次。`);
    } finally {
      setSaving(false);
    }
  }

  function discard() {
    clearDraft(sessionStorage);
    setDraft(saved.data ?? []);
  }

  const rows = draft ?? [];
  const changed = draft !== null && saved.data !== null && draftChanged(draft, saved.data);
  const primary = rows.find((r) => r.isPrimary);

  return (
    <>
      <main className="page">
        <div className="title-row">
          <div>
            <h1>选校组合</h1>
            <p className="lede">
              {rows.length} 个项目 ·{" "}
              {primary ? (
                <>
                  首选 <strong>{primary.program?.university} {primary.program?.nameEn}</strong>
                </>
              ) : (
                "还没有设首选"
              )}
            </p>
          </div>
          <div className="toolbar">
            <Link className="btn btn-secondary" href="/assess/result">
              从测评结果添加
            </Link>
          </div>
        </div>

        {saved.error && !saved.data && <div className="section"><Notice error>没有读到已保存的组合（{saved.error}）。</Notice></div>}
        {draft === null && !saved.error && <div className="section"><Loading what="选校组合" /></div>}

        {draft !== null && (
          <div className="stagger">
            <section className="panel section" aria-label="申请状态分布">
              <div className="strip">
                {APPLICATION_STATUSES.filter((s) => s.value !== "excluded").map((s) => {
                  const n = rows.filter((r) => (r.status ?? "considering") === s.value).length;
                  return (
                    <div key={s.value}>
                      <div className="label">{s.label}</div>
                      <div className={`value num${n === 0 ? " muted" : ""}`}>{n}</div>
                    </div>
                  );
                })}
              </div>
            </section>

            <section className="panel section" aria-labelledby="list-h">
              <h2 id="list-h" className="sr-only">项目列表</h2>
              <table className="stack">
                <thead>
                  <tr>
                    <th>项目</th>
                    <th>档位</th>
                    <th>官方截止</th>
                    <th>申请状态</th>
                    <th>首选</th>
                    <th className="num"><span className="sr-only">操作</span></th>
                  </tr>
                </thead>
                <tbody>
                  {rows.length === 0 && (
                    <tr>
                      <td colSpan={6} className="wide">
                        <div className="empty">
                          还没有选项目。<Link href="/assess/result">从测评结果添加</Link>
                        </div>
                      </td>
                    </tr>
                  )}
                  {rows.map((r, i) => {
                    const program = programs.get(r.programSlug);
                    return (
                      <tr key={r.programSlug}>
                        <td className="wide">
                          <div className="two-line">
                            <Link className="l1" href={`/programs/${encodeURIComponent(r.programSlug)}`}>
                              {r.program?.nameEn ?? program?.name ?? "未知"}
                            </Link>
                            <div className="l2">
                              {r.program?.university ?? program?.university ?? "未知"}
                              {program?.duration ? ` · ${program.duration}` : ""}
                            </div>
                          </div>
                        </td>
                        <td>
                          <span className="toolbar" style={{ gap: 4 }}>
                            <Pill kind="tier">{TIER_OF_BAND[r.tier]}</Pill>
                            {r.needsReview && <Pill kind="outline">未经系统分档</Pill>}
                          </span>
                        </td>
                        <td className="wide">
                          {r.officialDeadline && r.deadlineSourceUrl ? (
                            <a href={r.deadlineSourceUrl} target="_blank" rel="noreferrer" className="num">
                              {r.officialDeadline}
                            </a>
                          ) : (
                            <>
                              <span className="hollow" />
                              未收录{" "}
                              {program && (
                                <a className="muted small" href={program.source.url} target="_blank" rel="noreferrer">
                                  去官网查
                                </a>
                              )}
                            </>
                          )}
                        </td>
                        <td>
                          <label className="sr-only" htmlFor={`status-${i}`}>
                            申请状态
                          </label>
                          <select
                            id={`status-${i}`}
                            className="select"
                            style={{ height: 32, width: 128 }}
                            value={r.status ?? "considering"}
                            onChange={(e) => update(setStatus(rows, r.programSlug, e.target.value as ApplicationStatus))}
                          >
                            {APPLICATION_STATUSES.map((s) => (
                              <option key={s.value} value={s.value}>
                                {s.label}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td>
                          <label className="primary-radio">
                            <input type="radio" name="primary" checked={!!r.isPrimary} onChange={() => update(setPrimary(rows, r.programSlug))} />
                            {r.isPrimary ? "首选" : "设为首选"}
                          </label>
                        </td>
                        <td className="num">
                          <Button variant="text" onClick={() => update(removeFromDraft(rows, r.programSlug))}>
                            移出
                          </Button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </section>
          </div>
        )}

        {(changed || saveError) && (
          <div className="unsaved" role="status">
            <span className={saveError ? "negative" : undefined}>{saveError ?? "组合有改动，还没保存到服务器。"}</span>
            <span className="toolbar">
              <Button variant="text" onClick={discard} disabled={saving}>
                放弃改动
              </Button>
              <Button variant="primary" onClick={confirm} disabled={saving}>
                {saving ? "正在保存…" : `确认 ${rows.length} 个项目`}
              </Button>
            </span>
          </div>
        )}
        {savedNote && !changed && <div className="section"><Notice>{savedNote}</Notice></div>}
      </main>
      <SourceNote>
        确认后，组合写入服务器，路线图按新组合显示截止日期。官方截止日期只有收录了官网来源才显示日期，其余显示为未收录。档位标“未经系统分档”的，是你自己定的档位。
      </SourceNote>
    </>
  );
}
