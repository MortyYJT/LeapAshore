"use client";

import Link from "next/link";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { LoginPrompt, RequireAccount } from "@/components/auth/AuthProvider";
import { DeadlineText } from "@/components/roadmap/DeadlineText";
import { Button, LoadingPanel, Notice, Pill } from "@/components/ui";
import { fetchProgramPage, replaceApplications } from "@/lib/api";
import { beijingToday, deadlineOf } from "@/lib/deadlines";
import { loadPortfolio, usePortfolio } from "@/lib/hooks/usePortfolio";
import {
  baseOf,
  clearDraft,
  draftChanged,
  draftDifferences,
  readDraft,
  readDraftBase,
  removeFromDraft,
  setPrimary,
  setStatus,
  writeDraft,
  writeDraftBase,
} from "@/lib/portfolio-draft";
import { toApplicationRows, toPortfolioItems, type ServedApplication } from "@/lib/programs-source";
import { StaleVersionError } from "@/lib/sync-conflict";
import { APPLICATION_STATUSES, TIER_OF_BAND } from "@/lib/taxonomy";
import type { ApplicationStatus, PortfolioItem, Program } from "@/lib/types";

/**
 * The portfolio (spec application-portfolio): one row per program with its band, whether the system
 * tiered it, its official deadline, its status and the first-choice mark. Edits stay in the draft until
 * the applicant confirms; confirming replaces the stored portfolio whole.
 */
export default function PortfolioPage() {
  return (
    <RequireAccount
      what="选校组合"
      fallback={
        <main className="page">
          <div className="title-row">
            <h1>选校组合</h1>
          </div>
          <LoginPrompt what="你的选校组合" />
        </main>
      }
      pending={
        <main className="page">
          <div className="title-row">
            <h1>选校组合</h1>
          </div>
          <LoadingPanel what="选校组合" />
        </main>
      }
    >
      <Portfolio />
    </RequireAccount>
  );
}

function Portfolio() {
  const saved = usePortfolio();
  const [draft, setDraft] = useState<PortfolioItem[] | null>(null);
  const today = useMemo(() => beijingToday(), []);
  const [programs, setPrograms] = useState<Map<string, Program>>(new Map());
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedNote, setSavedNote] = useState<string | null>(null);
  // True after a confirm was refused because another device changed the portfolio; see `confirm`.
  const [conflict, setConflict] = useState(false);
  const tbody = useRef<HTMLTableSectionElement>(null);
  const beforeRemoval = useRef<Map<string, number> | null>(null);
  const rowMotion = useRef<Animation[]>([]);

  useEffect(() => {
    if (draft !== null || saved.loading) return;
    setDraft(readDraft(sessionStorage) ?? saved.data ?? []);
  }, [draft, saved.loading, saved.data]);

  const ids = useMemo(
    () =>
      (draft ?? []).map((r) => r.programSlug).filter((id) => !programs.has(id)),
    [draft, programs],
  );
  useEffect(() => {
    if (ids.length === 0) return;
    fetchProgramPage({ ids: ids.slice(0, 100), limit: 100 })
      .then(({ programs: found }) =>
        setPrograms(
          (prev) =>
            new Map([...prev, ...found.map((p) => [p.slug, p] as const)]),
        ),
      )
      .catch(() => undefined); // the rows still render from the portfolio's own program names
  }, [ids]);

  useLayoutEffect(() => {
    const before = beforeRemoval.current;
    beforeRemoval.current = null;
    if (!before || !tbody.current || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const style = getComputedStyle(tbody.current);
    const duration = parseFloat(style.getPropertyValue("--motion-normal"));
    const easing = style.getPropertyValue("--motion-ease").trim();
    // Read the new positions before starting any animation.
    const movement = Array.from(tbody.current.rows).flatMap((row) => {
      const old = before.get(row.dataset.program ?? "");
      if (old === undefined) return [];
      const offset = old - row.getBoundingClientRect().top;
      return Math.abs(offset) >= 1 ? [{ row, offset }] : [];
    });
    rowMotion.current = movement.map(({ row, offset }) => row.animate(
      [{ translate: `0 ${offset}px` }, { translate: "none" }],
      { duration, easing },
    ));
  }, [draft]);

  useEffect(() => {
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    const cancel = () => {
      for (const animation of rowMotion.current) animation.cancel();
      rowMotion.current = [];
    };
    const preferenceChanged = () => { if (reduced.matches) cancel(); };
    reduced.addEventListener("change", preferenceChanged);
    return () => {
      reduced.removeEventListener("change", preferenceChanged);
      cancel();
    };
  }, []);

  function remove(slug: string) {
    if (!draft || saving) return;
    if (tbody.current && tbody.current.rows.length <= 40 &&
        !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      beforeRemoval.current = new Map(
        Array.from(tbody.current.rows, (row) => [row.dataset.program ?? "", row.getBoundingClientRect().top]),
      );
      for (const animation of rowMotion.current) animation.cancel();
    }
    update(removeFromDraft(draft, slug));
  }

  const update = (next: PortfolioItem[]) => {
    setDraft(next);
    setSavedNote(null);
    // The saved portfolio is stated with the first write, as the base the confirm is checked against.
    writeDraft(sessionStorage, next, saved.data);
  };

  async function confirm() {
    if (!draft || saving) return;
    setSaving(true);
    setSaveError(null);
    try {
      await replaceApplications(
        toApplicationRows(draft),
        readDraftBase(sessionStorage) ?? baseOf(saved.data ?? []),
      );
      setConflict(false);
      clearDraft(sessionStorage);
      try {
        const confirmed = await loadPortfolio();
        saved.set(confirmed);
        setDraft(confirmed);
        setSavedNote(`已保存 ${draft.length} 个项目，路线图会按新组合显示截止日期。`);
      } catch {
        setSavedNote(`已保存 ${draft.length} 个项目。暂时无法刷新服务器上的组合显示。`);
        saved.reload();
      }
    } catch (error: unknown) {
      if (error instanceof StaleVersionError) {
        // Another device changed the portfolio after this draft was made. Nothing was written. The
        // server's rows become the saved portfolio on screen and the draft's base, so the two buttons
        // below are the choice: confirm again to save this draft over them, or discard it for theirs.
        const theirs = toPortfolioItems(error.current as ServedApplication[]);
        saved.set(theirs);
        if (!draftChanged(draft, theirs)) {
          // The server already holds exactly this draft (an earlier confirm landed): it is saved.
          clearDraft(sessionStorage);
          setDraft(theirs);
          setConflict(false);
          setSavedNote(`已保存 ${draft.length} 个项目，路线图会按新组合显示截止日期。`);
        } else {
          writeDraftBase(sessionStorage, baseOf(theirs));
          setConflict(true);
          setSaveError(`组合已在其他设备上修改，这次没有保存。${portfolioDifferences(draft, theirs)}`);
        }
      } else {
        setConflict(false);
        setSaveError(
          `组合没有保存（${error instanceof Error ? error.message : "未知错误"}），改动还在，可以再试一次。`,
        );
      }
    } finally {
      setSaving(false);
    }
  }

  function discard() {
    clearDraft(sessionStorage);
    setDraft(saved.data ?? []);
    setConflict(false);
    setSaveError(null);
  }

  const rows = [...(draft ?? [])].sort(
    (a, b) =>
      ["冲", "稳", "保"].indexOf(a.tier) - ["冲", "稳", "保"].indexOf(b.tier),
  );
  const changed =
    !savedNote && draft !== null && saved.data !== null && draftChanged(draft, saved.data);
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
                  首选{" "}
                  <strong>
                    {primary.program?.university} {primary.program?.nameEn}
                  </strong>
                </>
              ) : (
                "还没有设首选"
              )}
            </p>
          </div>
          <div className="toolbar">
            <Link className="btn btn-secondary" href="/tiers">
              从分档结果添加
            </Link>
          </div>
        </div>

        {saved.error && !saved.data && (
          <div className="section">
            <Notice error>没有读到已保存的组合（{saved.error}）。</Notice>
          </div>
        )}
        {draft === null && !saved.error && <LoadingPanel what="选校组合" />}

        {draft !== null && (
          <div className="stagger">
            <section className="panel section" aria-label="申请状态分布">
              <div className="strip">
                {APPLICATION_STATUSES.filter((s) => s.value !== "excluded").map(
                  (s) => {
                    const n = rows.filter(
                      (r) => (r.status ?? "considering") === s.value,
                    ).length;
                    return (
                      <div key={s.value}>
                        <div className="label">{s.label}</div>
                        <div className={`value num${n === 0 ? " muted" : ""}`}>
                          {n}
                        </div>
                      </div>
                    );
                  },
                )}
              </div>
            </section>

            <section className="panel section" aria-labelledby="list-h">
              <h2 id="list-h" className="sr-only">
                项目列表
              </h2>
              <table className="stack">
                <thead>
                  <tr>
                    <th>项目</th>
                    <th>档位</th>
                    <th>官方截止</th>
                    <th>申请状态</th>
                    <th>首选</th>
                    <th className="num">
                      <span className="sr-only">操作</span>
                    </th>
                  </tr>
                </thead>
                <tbody ref={tbody}>
                  {rows.length === 0 && (
                    <tr>
                      <td colSpan={6} className="wide">
                        <div className="empty">
                          还没有选项目。
                          <Link href="/tiers">从分档结果添加</Link>
                        </div>
                      </td>
                    </tr>
                  )}
                  {rows.map((r, i) => {
                    const program = programs.get(r.programSlug);
                    const deadline = deadlineOf(
                      {
                        ...r,
                        deadlines: r.collectedDeadlines ?? program?.deadlines,
                      },
                      today,
                    );
                    return (
                      <tr
                        key={r.programSlug}
                        data-program={r.programSlug}
                        className={
                          i === 0 || rows[i - 1].tier !== r.tier
                            ? "portfolio-group-start"
                            : undefined
                        }
                      >
                        <td className="wide">
                          {(i === 0 || rows[i - 1].tier !== r.tier) && (
                            <div className="portfolio-group-label">
                              {r.tier === "保" ? "保底" : TIER_OF_BAND[r.tier]}{" "}
                              · {rows.filter((x) => x.tier === r.tier).length}{" "}
                              个项目
                            </div>
                          )}
                          <div className="two-line">
                            <Link
                              className="l1"
                              href={`/programs/${encodeURIComponent(r.programSlug)}`}
                            >
                              {r.program?.nameEn ?? program?.name ?? "未知"}
                            </Link>
                            <div className="l2">
                              {r.program?.university ??
                                program?.university ??
                                "未知"}
                              {program?.duration
                                ? ` · ${program.duration}`
                                : ""}
                            </div>
                          </div>
                        </td>
                        <td>
                          <span className="toolbar" style={{ gap: 4 }}>
                            <Pill kind="tier">{TIER_OF_BAND[r.tier]}</Pill>
                            {r.needsReview && (
                              <Pill kind="outline">未经系统分档</Pill>
                            )}
                          </span>
                        </td>
                        <td className="wide">
                          {deadline.state !== "unknown" ? (
                            <DeadlineText view={deadline} />
                          ) : (
                            <>
                              <DeadlineText view={deadline} />{" "}
                              {program && (
                                <a
                                  className="muted small"
                                  href={program.source.url}
                                  target="_blank"
                                  rel="noreferrer"
                                >
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
                            disabled={saving}
                            className="select"
                            style={{ height: 32, width: 128 }}
                            value={r.status ?? "considering"}
                            onChange={(e) =>
                              update(
                                setStatus(
                                  rows,
                                  r.programSlug,
                                  e.target.value as ApplicationStatus,
                                ),
                              )
                            }
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
                            <input
                              type="radio"
                              name="primary"
                              disabled={saving}
                              checked={!!r.isPrimary}
                              onChange={() =>
                                update(setPrimary(rows, r.programSlug))
                              }
                            />
                            {r.isPrimary ? "首选" : "设为首选"}
                          </label>
                        </td>
                        <td className="num">
                          <Button
                            variant="text"
                            disabled={saving}
                            onClick={() => remove(r.programSlug)}
                          >
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
            <span className={saveError ? "negative" : undefined}>
              {saveError ?? "组合有改动，还没保存到服务器。"}
            </span>
            <span className="toolbar">
              <Button variant="text" onClick={discard} disabled={saving}>
                {conflict ? "使用服务器上的组合" : "放弃改动"}
              </Button>
              <Button variant="primary" onClick={confirm} disabled={saving}>
                {saving ? "正在保存…" : conflict ? `保留我的 ${rows.length} 个项目` : `确认 ${rows.length} 个项目`}
              </Button>
            </span>
          </div>
        )}
        {savedNote && !changed && (
          <div className="section">
            <Notice>{savedNote}</Notice>
          </div>
        )}
      </main>
    </>
  );
}

/** What keeping this draft would do to the portfolio the server holds, in the applicant's words. */
function portfolioDifferences(mine: PortfolioItem[], theirs: PortfolioItem[]): string {
  const names = new Map([...theirs, ...mine].map((row) => [row.programSlug, row.program?.nameEn ?? row.programSlug]));
  const list = (slugs: string[]) => slugs.map((slug) => names.get(slug)).join("、");
  const { onlyMine, onlyTheirs, changed } = draftDifferences(mine, theirs);
  return [
    onlyTheirs.length ? `保留我的会移除服务器上的：${list(onlyTheirs)}。` : "",
    onlyMine.length ? `会加入：${list(onlyMine)}。` : "",
    changed.length ? `会把这些项目的档位、状态或首选改回你这里的：${list(changed)}。` : "",
  ].join("");
}
