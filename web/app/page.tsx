"use client";
import Link from "next/link";
import { RequireAccount } from "@/components/auth/AuthProvider";
import { LoadingPanel, Notice, TaskProgress } from "@/components/ui";
import { useProfile } from "@/lib/hooks/useProfile";
import { useRoadmap } from "@/lib/hooks/useRoadmap";
import { useResource } from "@/lib/hooks/useResource";
import { timelineOf } from "@/lib/roadmap-timeline";
import {
  attentionRecords,
  deadlineLabel,
  loadApplicationRecords,
  type ApplicationRecord,
} from "@/lib/application-records";
export default function Home() {
  return (
    <main className="page dashboard">
      <div className="workspace-crumb">我的工作台 / 总览</div>
      <h1>把申请，一步步推进。</h1>
      <p className="lede">集中管理硕士申请的截止日期、材料和准备进度。</p>
      <RequireAccount what="申请工作台">
        <Workspace />
      </RequireAccount>
    </main>
  );
}
function Workspace() {
  const records = useResource(loadApplicationRecords);
  const profile = useProfile();
  const roadmap = useRoadmap(profile.data);
  const model = roadmap.roadmap
    ? timelineOf(roadmap.roadmap, new Date())
    : null;
  const attention = attentionRecords(records.data ?? []);
  const tasks = model?.current?.phase.tasks ?? [];
  const totals = model?.phases.reduce(
    (sum, phase) => ({ done: sum.done + phase.done, total: sum.total + phase.total }),
    { done: 0, total: 0 },
  );
  return (
    <>
      {records.loading && !records.data ? (
        <LoadingPanel what="申请工作台" />
      ) : records.error ? (
        <Notice error>{records.error}</Notice>
      ) : records.data?.length === 0 ? (
        <section className="workspace-onboarding section">
          <h2>从第一份申请开始</h2>
          <p className="muted">
            添加目标项目，把截止日期、申请材料和准备任务放在一起。
          </p>
          <div className="toolbar">
            <Link className="btn btn-primary" href="/applications?add=1">
              添加申请项目
            </Link>
            <Link className="btn btn-text" href="/schools">
              浏览学校库 →
            </Link>
          </div>
        </section>
      ) : (
        <>
          <section className="workspace-attention section">
            <div className="dashboard-tasks-heading">
              <h2>最近截止</h2>
              <Link href="/applications">全部申请 →</Link>
            </div>
            {attention.dated.length ? (
              attention.dated
                .slice(0, 3)
                .map((record) => (
                  <ApplicationAttention key={record.id} record={record} />
                ))
            ) : (
              <p className="muted">暂无准备中且已填写日期的申请。</p>
            )}
          </section>
          {attention.undated.length > 0 && (
            <section className="section">
              <h2>日期待确认</h2>
              {attention.undated.slice(0, 2).map((record) => (
                <ApplicationAttention key={record.id} record={record} />
              ))}
            </section>
          )}
          <section className="section">
            <div className="dashboard-tasks-heading">
              <h2>接下来要做</h2>
              <div className="toolbar">
                {!!totals?.total && <span className="num muted" aria-live="polite">{totals.done}/{totals.total} 项完成</span>}
                <Link href="/roadmap">全部任务 →</Link>
              </div>
            </div>
            {!!totals?.total && (
              <div className="dashboard-task-progress">
                <TaskProgress {...totals} label="路线图完成进度" />
              </div>
            )}
            {tasks.length ? (
              <div className="dashboard-tasks">
                {tasks.slice(0, 4).map((task) => (
                  <div key={task.materialId}>
                    <label
                      className={`dashboard-task${task.done ? " done" : ""}`}
                    >
                      <input
                        type="checkbox"
                        checked={task.done}
                        disabled={roadmap.taskIdFor(task.materialId) === null}
                        onChange={(event) =>
                          void roadmap.tick(
                            task.materialId,
                            event.target.checked,
                          )
                        }
                      />
                      <span>{task.label}</span>
                    </label>
                    {roadmap.failedTicks.has(task.materialId) && (
                      <Notice error>保存失败，请重试。</Notice>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <p className="muted">
                {roadmap.loading
                  ? "正在读取任务…"
                  : "完善申请背景后，路线图会给出准备任务。"}
              </p>
            )}
          </section>
        </>
      )}
      {profile.error && (
        <Notice error>无法读取申请背景：{profile.error}</Notice>
      )}
      {roadmap.notice && <Notice>{roadmap.notice}</Notice>}
      {roadmap.syncError && <Notice error>{roadmap.syncError}</Notice>}
      <section className="workspace-advisor section">
        <form action="/advisor" className="workspace-advisor-form">
          <label className="sr-only" htmlFor="home-advisor-question">
            向 AI 顾问提问
          </label>
          <textarea
            id="home-advisor-question"
            name="q"
            required
            maxLength={4000}
            placeholder="需要帮忙？例如：帮我梳理这些项目要准备的材料"
          />
          <div className="application-toolbar">
            <span className="small muted">AI 顾问 · 围绕你的申请提供帮助</span>
            <button className="btn btn-secondary" type="submit">
              询问 AI 顾问 →
            </button>
          </div>
        </form>
      </section>
    </>
  );
}
function ApplicationAttention({ record }: { record: ApplicationRecord }) {
  return (
    <Link className="workspace-application-row" href="/applications">
      <div>
        <div className="small muted">
          {record.school}
          {record.round ? ` · ${record.round}` : ""}
        </div>
        <div>{record.name}</div>
        <span className="small muted">
          {record.materialsReady ? "材料已就绪（自查）" : "材料准备中"}
        </span>
      </div>
      <div className="workspace-deadline">
        <span>{deadlineLabel(record)}</span>
        <span className="small muted">
          {record.checkedAt
            ? "已自行核对"
            : record.deadlineOrigin === "collected"
              ? "学校库采集 · 请复核"
              : "待自行核对"}
        </span>
      </div>
    </Link>
  );
}
