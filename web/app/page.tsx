"use client";
import Link from "next/link";
import { RequireAccount } from "@/components/auth/AuthProvider";
import { LoadingPanel, Notice } from "@/components/ui";
import { useProfile } from "@/lib/hooks/useProfile";
import { useRoadmap } from "@/lib/hooks/useRoadmap";
import { timelineOf } from "@/lib/roadmap-timeline";
import { intakeAnchor } from "@/lib/roadmap";
export default function Home() {
  return (
    <main className="page dashboard">
      <div className="workspace-crumb">我的工作台 / 总览</div>
      <h1>你好，欢迎回来</h1>
      <RequireAccount what="申请总览">
        <Dashboard />
      </RequireAccount>
    </main>
  );
}
function Dashboard() {
  const profile = useProfile();
  const roadmap = useRoadmap(profile.data);
  const model = roadmap.roadmap
    ? timelineOf(roadmap.roadmap, new Date())
    : null;
  const phase = model?.current;
  const tasks = phase?.phase.tasks ?? [];
  const total = model?.phases.length ?? 0;
  const pending = tasks.filter((t) => !t.done).length;
  const currentStage = model?.current
    ? model.phases.findIndex((p) => p.current) + 1
    : total;

  const anchor = profile.data ? intakeAnchor(profile.data.intake) : null;
  return (
    <>
      <p className="lede">
        {anchor
          ? `${anchor.getUTCFullYear()} 年 ${anchor.getUTCMonth() + 1} 月入学 · `
          : ""}
        查看你的申请准备情况
      </p>
      {(profile.loading || roadmap.loading) && !model ? (
        <LoadingPanel what="申请进度" />
      ) : profile.error ? (
        <Notice error>无法读取申请资料：{profile.error}</Notice>
      ) : model ? (
        <>
          <div className="dashboard-metrics">
            <section className="metric-card">
              <div className="muted">申请进度</div>
              <div className="metric-value">
                {currentStage} / {total} <span>阶段</span>
              </div>
            </section>
            <section className="metric-card">
              <div className="muted">待完成事项</div>
              <div className="metric-value">
                {pending} <span>项</span>
              </div>
            </section>
          </div>
          <section className="dashboard-progress">
            <h2>申请进度</h2>
            <div
              className="dashboard-progress-track"
              role="progressbar"
              aria-label="当前申请阶段位置"
              aria-valuemin={0}
              aria-valuemax={total}
              aria-valuenow={currentStage}
            >
              <div
                style={{
                  width: `${total ? (currentStage / total) * 100 : 0}%`,
                }}
              />
            </div>
            <p className="muted">当前阶段：{phase?.title ?? "全部完成"}</p>
          </section>
          <div className="dashboard-tasks-heading">
            <h2>接下来要做</h2>
            <Link href="/roadmap">全部任务 →</Link>
          </div>
          <div className="dashboard-tasks">
            {tasks.map((t) => (
              <div key={t.materialId}>
                <label className={`dashboard-task${t.done ? " done" : ""}`}>
                  <input
                    type="checkbox"
                    checked={t.done}
                    disabled={roadmap.taskIdFor(t.materialId) === null}
                    onChange={(e) =>
                      void roadmap.tick(t.materialId, e.target.checked)
                    }
                  />
                  <span>{t.label}</span>
                </label>
                {roadmap.failedTicks.has(t.materialId) && (
                  <Notice error>保存失败，请重试。</Notice>
                )}
              </div>
            ))}
            {!phase && <Notice>所有申请步骤已完成。</Notice>}
          </div>
        </>
      ) : (
        <Notice>
          完善申请背景后，这里会显示你的申请进度。
          <Link href="/me">填写背景 →</Link>
        </Notice>
      )}
      {roadmap.notice && <Notice>{roadmap.notice}</Notice>}
      {roadmap.syncError && <Notice error>{roadmap.syncError}</Notice>}
    </>
  );
}
