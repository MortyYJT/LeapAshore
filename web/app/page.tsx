"use client";
import Link from "next/link";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { DOCK_QUERY, useAdvisorDock } from "@/components/advisor/AdvisorProvider";
import { RequireAccount, useAuth } from "@/components/auth/AuthProvider";
import { DeadlineTable, editHref, type RowLink } from "@/components/home/DeadlineTable";
import { useApplicationRecords } from "@/components/shell/ApplicationRecords";
import { ConflictNotice, Loading, Notice } from "@/components/ui";
import { RECORD_STATUSES, writeApplicationRecord, type ApplicationRecord } from "@/lib/application-records";
import { beijingToday } from "@/lib/deadlines";
import { demoProgramHref } from "@/lib/demo";
import { useProfile } from "@/lib/hooks/useProfile";
import { useRoadmap } from "@/lib/hooks/useRoadmap";
import { nextSentence, overviewOf, sentenceDate, type NextAction, type Overview } from "@/lib/overview";
import { taskStatusLabel } from "@/lib/roadmap-sync";
import { timelineOf } from "@/lib/roadmap-timeline";
import { StaleVersionError, resolveStaleField } from "@/lib/sync-conflict";

export default function Home() {
  return (
    <main className="page overview">
      <RequireAccount
        what="你的申请"
        fallback={<SignedOut />}
        pending={
          <Frame finding="正在读取登录状态…">
            <Loading what="你的申请" />
          </Frame>
        }
      >
        <Workspace />
      </RequireAccount>
    </main>
  );
}

/** The title, the sentence under it, and the blocks. `demo` marks the title of a page that shows sample data. */
function Frame({ finding, demo = false, children }: { finding: ReactNode; demo?: boolean; children: ReactNode }) {
  return (
    <>
      <header className={`page-head${demo ? " has-note" : ""}`}>
        <div>
          {demo ? (
            <div className="marked">
              <h1>总览</h1>
              <DemoMark />
            </div>
          ) : (
            <h1>总览</h1>
          )}
          <p className="finding">{finding}</p>
        </div>
      </header>
      {children}
    </>
  );
}

/** The dashed tag that says a row is not the visitor's own. */
function DemoMark() {
  return <span className="pill pill-sample">演示</span>;
}

/**
 * For a visitor: the overview drawn for a few programs from the catalogue, labelled as a demo. When
 * the catalogue cannot supply one, the plain block below.
 */
function SignedOut() {
  const { demo, demoPending } = useApplicationRecords();
  if (demoPending) {
    return (
      <Frame finding="正在读取学校库…">
        <Loading what="学校库" />
      </Frame>
    );
  }
  return demo ? <Demo records={demo} /> : <SignedOutBlock />;
}

/** The same axis with today on it, and the way in. No applications are drawn. */
function SignedOutBlock() {
  const { requireLogin } = useAuth();
  const today = beijingToday();
  return (
    <Frame finding="登录后，你的每个申请在这里画成一条线，从今天画到它的截止日期。">
      <section className="block" aria-labelledby="h-deadlines">
        <div className="block-head">
          <h2 id="h-deadlines">截止日期</h2>
        </div>
        <DeadlineTable
          model={overviewOf([], today)}
          today={today}
          labelledBy="h-deadlines"
          empty={
            <div className="lt-empty">
              <p>
                <b>登录后查看你的申请</b>
                用邮箱收一个 6 位验证码就能登录，第一次登录会自动注册。学校库不用登录也能看。
              </p>
              <button type="button" className="btn btn-primary" onClick={() => void requireLogin()}>
                登录
              </button>
              <Link className="btn btn-secondary" href="/schools">
                浏览学校库
              </Link>
            </div>
          }
        />
      </section>
    </Frame>
  );
}

const DEMO_LINK: RowLink = { href: (row) => demoProgramHref(row.record), title: "在学校库里看这个项目和日期的来源" };

/**
 * The overview as a signed-in applicant has it, drawn for catalogue programs (lib/demo.ts). The
 * school, the program and the date of each row are the catalogue's; the status and the materials are
 * made up, and the note under the title says which is which. Nothing here writes: a row leads to the
 * program's public page, and the actions that would save something ask the visitor to sign in.
 */
function Demo({ records }: { records: ApplicationRecord[] }) {
  const { requireLogin } = useAuth();
  const { selected } = useApplicationRecords();
  const today = beijingToday();
  const model = useMemo(() => overviewOf(records, today), [records, today]);
  return (
    <Frame demo finding={<Finding model={model} />}>
      <div className="demo-note" role="note">
        <p id="demo-note">这是演示：项目和截止日期来自学校库，状态和材料是示例。登录后这里是你自己的申请。</p>
        <button type="button" className="btn btn-primary" onClick={() => void requireLogin()}>
          登录
        </button>
      </div>
      <section className="block" aria-labelledby="h-deadlines">
        <div className="block-head">
          <h2 id="h-deadlines">截止日期</h2>
          <p className="block-note">
            <Link href="/schools">浏览学校库</Link>
          </p>
        </div>
        <DeadlineTable model={model} today={today} labelledBy="h-deadlines" selected={selected} link={DEMO_LINK} />
      </section>
      <section className="block" aria-labelledby="h-next">
        <div className="block-head">
          <div className="marked">
            <h2 id="h-next">接下来</h2>
            <DemoMark />
          </div>
        </div>
        <DemoNext actions={model.next} onSignIn={() => void requireLogin()} />
      </section>
    </Frame>
  );
}

/**
 * "接下来" for the demo. The rows and their sentences are the real ones. Asking the advisor puts the
 * question in the composer unsent, as it does for an applicant (sending it is what needs an account);
 * the two actions that would save something open the sign-in dialog instead.
 */
function DemoNext({ actions, onSignIn }: { actions: NextAction[]; onSignIn: () => void }) {
  const advisor = useAdvisorDock();
  return (
    <ol className="next">
      {actions.map((action) => {
        const { row, kind } = action;
        const { record } = row;
        return (
          <li className={`line-${row.line}`} key={record.id}>
            <div className="who">
              <span className="bullet">{row.code}</span>
              <span>{record.school}</span>
            </div>
            <p>{nextSentence(action)}</p>
            {kind === "confirm" ? (
              <Link
                className="btn btn-secondary"
                href={`/advisor?q=${encodeURIComponent(deadlineQuestion(record))}`}
                onClick={(event) => {
                  if (event.metaKey || event.ctrlKey || event.shiftKey || !window.matchMedia(DOCK_QUERY).matches) return;
                  event.preventDefault();
                  advisor.ask(deadlineQuestion(record));
                }}
              >
                让顾问去查
              </Link>
            ) : (
              <button type="button" className="btn btn-secondary" aria-describedby="demo-note" title="演示里不会保存，登录后可用" onClick={onSignIn}>
                {kind === "submit" ? "标记为已提交" : kind === "passed" ? "更新日期" : "更新材料"}
              </button>
            )}
          </li>
        );
      })}
    </ol>
  );
}

function Workspace() {
  const records = useApplicationRecords();
  const today = beijingToday();
  const model = useMemo(() => (records.data ? overviewOf(records.data, today) : null), [records.data, today]);
  const [flash, setFlash] = useState<string | null>(null);

  // The highlight on a row that was just written lasts as long as its animation.
  useEffect(() => {
    if (!flash) return;
    const timer = window.setTimeout(() => setFlash(null), 2000);
    return () => window.clearTimeout(timer);
  }, [flash]);

  // A change the advisor wrote flashes its row too, once the records have been read again.
  const { changedProgram, markChanged } = records;
  useEffect(() => {
    if (!changedProgram || records.loading) return;
    const row = records.data?.find((record) => record.id === changedProgram || record.programId === changedProgram);
    if (row) setFlash(row.id);
    markChanged(null);
  }, [changedProgram, records.loading, records.data, markChanged]);

  if (!model) {
    return records.error ? (
      <Frame finding="没能读取你的申请。">
        <Notice error>{records.error}</Notice>
        <p>
          <button type="button" className="btn btn-secondary" onClick={records.reload}>
            重试
          </button>
        </p>
      </Frame>
    ) : (
      <Frame finding="正在读取你的申请…">
        <Loading what="你的申请" />
      </Frame>
    );
  }

  function replace(saved: ApplicationRecord) {
    records.set((records.data ?? []).map((record) => (record.id === saved.id ? saved : record)));
    setFlash(saved.id);
  }

  return (
    <Frame finding={<Finding model={model} />}>
      {records.error && <Notice error>没能更新，下面是上次读到的内容：{records.error}</Notice>}
      <section className="block" aria-labelledby="h-deadlines">
        <div className="block-head">
          <h2 id="h-deadlines">截止日期</h2>
          {model.rows.length > 0 && (
            <p className="block-note">
              <Link href="/applications">全部申请</Link>
            </p>
          )}
        </div>
        <DeadlineTable
          model={model}
          today={today}
          labelledBy="h-deadlines"
          selected={records.selected}
          flash={flash}
          empty={
            <div className="lt-empty">
              {model.total ? (
                <p>
                  <b>没有在准备或已提交的申请</b>
                  已有结果和已放弃的申请在「我的申请」里。
                </p>
              ) : (
                <p>
                  <b>添加第一个申请</b>
                  它会画成一条线，从今天画到截止日期。日期还不知道也可以先加。
                </p>
              )}
              <Link className="btn btn-primary" href="/applications?add=1">
                添加申请项目
              </Link>
              <Link className="btn btn-secondary" href="/schools">
                浏览学校库
              </Link>
            </div>
          }
        />
      </section>
      {model.rows.length > 0 && (
        <>
          <section className="block" aria-labelledby="h-next">
            <div className="block-head">
              <h2 id="h-next">接下来</h2>
            </div>
            <NextActions actions={model.next} onSaved={replace} />
          </section>
          <Tasks />
        </>
      )}
    </Frame>
  );
}

/** The sentence under the title: how many, the nearest date, and what is still unknown. */
function Finding({ model }: { model: Overview }) {
  const { rows, sentCount, nearest, unknown, closed, total } = model;
  if (!total) return <>还没有申请。</>;
  if (!rows.length) return <>{closed} 个申请都已有结果或已放弃，没有要跟进的截止日期。</>;
  return (
    <>
      {rows.length} 个申请{sentCount > 0 && `，${sentCount} 个已提交`}。
      {nearest &&
        (nearest.days === 0 ? (
          <>
            最近的是{nearest.record.school}，<b>今天截止</b>。
          </>
        ) : (
          <>
            最近的是{nearest.record.school}，{sentenceDate(nearest.record.deadline!, nearest.days!)}截止，<b>还有 {nearest.days} 天</b>。
          </>
        ))}
      {unknown.length > 0 &&
        (unknown.length > 2
          ? `${unknown.length} 个申请的截止日期还没确认。`
          : `${unknown.map((row) => row.record.school).join("、")}的截止日期还没确认。`)}
      {closed > 0 && `另有 ${closed} 个已有结果或已放弃，没有列出。`}
    </>
  );
}

function deadlineQuestion(record: ApplicationRecord): string {
  return `${record.school} ${record.name} 的申请截止日期是哪天？`;
}

function statusLabel(status: string): string {
  return RECORD_STATUSES.find(([value]) => value === status)?.[1] ?? status;
}

/**
 * One row per open application that needs something, most pressing first. Three of the four actions
 * lead to where the thing is done; "标记为已提交" writes the status here, and a save the server refuses
 * because the record changed on another device is settled in place (lib/sync-conflict.ts).
 */
function NextActions({ actions, onSaved }: { actions: NextAction[]; onSaved: (record: ApplicationRecord) => void }) {
  const advisor = useAdvisorDock();
  const [busy, setBusy] = useState<string | null>(null);
  const [failed, setFailed] = useState<{ id: string; message: string } | null>(null);
  const [conflict, setConflict] = useState<{ id: string; current: ApplicationRecord } | null>(null);

  async function markSubmitted(record: ApplicationRecord, base: ApplicationRecord = record) {
    setBusy(record.id);
    setFailed(null);
    setConflict(null);
    try {
      const saved = await writeApplicationRecord(record.id, { status: "submitted", baseVersion: base.version });
      if (saved) onSaved(saved);
    } catch (error) {
      if (error instanceof StaleVersionError) {
        const current = error.current as ApplicationRecord;
        const answer = resolveStaleField(record.status, "submitted", current.status);
        // The other device already marked it, or changed something else: no question to ask.
        if (answer === "adopt") onSaved(current);
        else if (answer === "retry") return await markSubmitted(record, current);
        else setConflict({ id: record.id, current });
      } else setFailed({ id: record.id, message: error instanceof Error ? error.message : "保存失败" });
    } finally {
      setBusy(null);
    }
  }

  if (!actions.length) {
    return (
      <ol className="next">
        <li className="is-plain">没有在准备的申请，暂时没有要做的事。</li>
      </ol>
    );
  }
  // One primary button on the screen at most: the first unknown date.
  const primary = actions.find((action) => action.kind === "confirm")?.row.record.id;
  return (
    <ol className="next">
      {actions.map((action) => {
        const { row, kind } = action;
        const { record } = row;
        return (
          <li className={`line-${row.line}`} key={record.id}>
            <div className="who">
              <span className="bullet">{row.code}</span>
              <span>{record.school}</span>
            </div>
            <p>{nextSentence(action)}</p>
            {kind === "confirm" ? (
              // The question goes into the composer unsent: in the dock where there is one, and through
              // the link itself on a phone, where the advisor is its own page.
              <Link
                className={`btn ${record.id === primary ? "btn-primary" : "btn-secondary"}`}
                href={`/advisor?q=${encodeURIComponent(deadlineQuestion(record))}`}
                onClick={(event) => {
                  if (event.metaKey || event.ctrlKey || event.shiftKey || !window.matchMedia(DOCK_QUERY).matches) return;
                  event.preventDefault();
                  advisor.ask(deadlineQuestion(record));
                }}
              >
                让顾问去查
              </Link>
            ) : kind === "submit" ? (
              <button type="button" className="btn btn-secondary" disabled={busy !== null} onClick={() => void markSubmitted(record)}>
                {busy === record.id ? "正在保存…" : "标记为已提交"}
              </button>
            ) : (
              <Link className="btn btn-secondary" href={kind === "passed" ? editHref(row) : "/materials"}>
                {kind === "passed" ? "更新日期" : "更新材料"}
              </Link>
            )}
            {failed?.id === record.id && <Notice error>没有保存：{failed.message}</Notice>}
            {conflict?.id === record.id && (
              <ConflictNotice
                busy={busy !== null}
                onKeepMine={() => void markSubmitted(record, conflict.current)}
                onTakeTheirs={() => {
                  setConflict(null);
                  onSaved(conflict.current);
                }}
              >
                这个申请已在其他设备上改为「{statusLabel(conflict.current.status)}」，这次没有标记为已提交。
              </ConflictNotice>
            )}
          </li>
        );
      })}
    </ol>
  );
}

/** The current roadmap phase's tasks, ticked here as on the roadmap. */
function Tasks() {
  const profile = useProfile();
  const roadmap = useRoadmap(profile.data);
  const timeline = roadmap.roadmap ? timelineOf(roadmap.roadmap, new Date()) : null;
  const tasks = timeline?.current?.phase.tasks ?? [];
  const totals = timeline?.phases.reduce(
    (sum, phase) => ({ done: sum.done + phase.done, total: sum.total + phase.total }),
    { done: 0, total: 0 },
  );
  return (
    <section className="block" aria-labelledby="h-tasks">
      <div className="block-head">
        <h2 id="h-tasks">准备任务</h2>
        <p className="block-note">
          {!!totals?.total && (
            <span className="block-count" aria-live="polite">
              {totals.done}/{totals.total} 项完成
            </span>
          )}{" "}
          <Link href="/roadmap">全部任务</Link>
        </p>
      </div>
      {tasks.length ? (
        <div className="task-rows">
          {tasks.slice(0, 4).map((task) => (
            <div key={task.materialId}>
              <label className={`task-row${task.done ? " done" : ""}`}>
                <input
                  type="checkbox"
                  checked={task.done}
                  disabled={roadmap.taskIdFor(task.materialId) === null}
                  onChange={(event) => void roadmap.tick(task.materialId, event.target.checked)}
                />
                <span>{task.label}</span>
              </label>
              {roadmap.failedTicks.has(task.materialId) && <Notice error>保存失败，请重试。</Notice>}
              {roadmap.tickConflicts.has(task.materialId) && (
                <ConflictNotice
                  onKeepMine={() => roadmap.settleTick(task.materialId, true)}
                  onTakeTheirs={() => roadmap.settleTick(task.materialId, false)}
                >
                  这一步已在其他设备上改为「{taskStatusLabel(roadmap.tickConflicts.get(task.materialId)!.theirs)}」，这次勾选没有保存。
                </ConflictNotice>
              )}
            </div>
          ))}
        </div>
      ) : (
        <p className="muted">{roadmap.loading ? "正在读取任务…" : "完善申请背景后，路线图会给出准备任务。"}</p>
      )}
      {profile.error && <Notice error>无法读取申请背景：{profile.error}</Notice>}
      {roadmap.notice && <Notice>{roadmap.notice}</Notice>}
      {roadmap.syncError && <Notice error>{roadmap.syncError}</Notice>}
    </section>
  );
}
