"use client";

import { FormEvent, useMemo, useState } from "react";

import type { ApiActionItem, ApplicationRoadmap } from "./api-client";


const statusLabels = {
  pending: "待开始",
  in_progress: "进行中",
  completed: "已完成",
  overdue: "已逾期",
} as const;

function displayDate(value?: string | null) {
  if (!value) return "待填写";
  return new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "short", day: "numeric" }).format(new Date(value));
}

function inputDate(value?: string | null) {
  if (!value) return "";
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

export function RoadmapView({
  roadmap,
  onBack,
  onUpdateTask,
}: {
  roadmap: ApplicationRoadmap;
  onBack: () => void;
  onUpdateTask: (taskId: string, payload: { status?: ApiActionItem["status"]; due_at?: string | null; reminder_at?: string | null }) => Promise<void>;
}) {
  const allTasks = useMemo(
    () => [...roadmap.phases.flatMap((phase) => phase.tasks), ...roadmap.program_branches.flatMap((branch) => branch.tasks)],
    [roadmap],
  );
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const selectedTask = allTasks.find((task) => task.id === selectedTaskId) ?? null;
  const progress = roadmap.total_tasks ? Math.round((roadmap.completed_tasks / roadmap.total_tasks) * 100) : 0;

  async function update(payload: { status?: ApiActionItem["status"]; due_at?: string | null; reminder_at?: string | null }) {
    if (!selectedTask) return;
    setBusy(true);
    try {
      await onUpdateTask(selectedTask.id, payload);
    } finally {
      setBusy(false);
    }
  }

  async function saveSchedule(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const due = String(form.get("due_at") ?? "");
    const reminder = String(form.get("reminder_at") ?? "");
    await update({
      due_at: due ? new Date(due).toISOString() : null,
      reminder_at: reminder ? new Date(reminder).toISOString() : null,
    });
  }

  return (
    <section className="product-page roadmap-page">
      <div className="product-page-header">
        <div><p className="eyebrow"><span /> 申请路线图</p><h1>你的申请行动计划</h1><p>{roadmap.intake} · 用依赖关系和建议时间推进材料准备</p></div>
        <button className="outline-button" onClick={onBack}>返回选校方案</button>
      </div>
      <div className="roadmap-summary">
        <div><strong>{progress}%</strong><span>总体进度</span></div>
        <p>系统日期用于规划准备节奏，不是学校官方截止日期。红色节点表示建议时间已经过去。</p>
        <span>{roadmap.completed_tasks}/{roadmap.total_tasks} 项完成</span>
      </div>

      <div className="roadmap-scroll" aria-label="横向申请路线图">
        <ol className="roadmap-track">
          {roadmap.phases.map((phase, index) => (
            <li className={`roadmap-phase phase-${phase.status}`} key={phase.id}>
              <div className="phase-index">{String(index + 1).padStart(2, "0")}</div>
              <article>
                <div className="phase-meta"><span>{statusLabels[phase.status]}</span><time>{displayDate(phase.suggested_at)}</time></div>
                <h2>{phase.title}</h2>
                <p>{phase.detail}</p>
                <div className="phase-tasks">
                  {phase.tasks.map((task) => (
                    <button type="button" key={task.id} onClick={() => setSelectedTaskId(task.id)}>
                      <i className={`task-dot task-${task.status}`} />{task.title}
                    </button>
                  ))}
                </div>
              </article>
            </li>
          ))}
        </ol>
        <div className="submission-branches" aria-label="确定申请项目分支">
          <div className="branch-origin"><span>项目分支</span></div>
          {roadmap.program_branches.length ? roadmap.program_branches.map((branch) => (
            <article className={branch.is_primary ? "program-branch primary" : "program-branch"} key={branch.program_slug}>
              <span>{branch.is_primary ? "★ 首选" : "确定申请"}</span>
              <h3>{branch.university}</h3><p>{branch.program_name}</p>
              <time>{branch.official_deadline ? `官方期限 ${displayDate(branch.official_deadline)}` : "尚未填写官方期限"}</time>
              {branch.tasks.map((task) => <button type="button" key={task.id} onClick={() => setSelectedTaskId(task.id)}>查看提交任务 →</button>)}
            </article>
          )) : <div className="branch-empty"><strong>还没有确定申请项目</strong><span>返回选校方案，把至少一个项目标记为“确定申请”。</span></div>}
        </div>
      </div>

      {selectedTask && (
        <aside className="task-drawer" aria-label="任务详情">
          <button className="drawer-close" onClick={() => setSelectedTaskId(null)} aria-label="关闭任务详情">×</button>
          <p className="step-kicker">{selectedTask.category ?? "申请任务"}</p>
          <h2>{selectedTask.title}</h2><p>{selectedTask.detail}</p>
          <div className="task-status-buttons">
            {(["待开始", "进行中", "已完成"] as const).map((status) => <button type="button" className={selectedTask.status === status ? "active" : ""} disabled={busy} key={status} onClick={() => update({ status })}>{status}</button>)}
          </div>
          <form key={`${selectedTask.id}-${selectedTask.due_at}-${selectedTask.reminder_at}`} onSubmit={saveSchedule}>
            <label>建议完成时间<input name="due_at" type="datetime-local" defaultValue={inputDate(selectedTask.due_at)} /></label>
            <label>提醒时间<input name="reminder_at" type="datetime-local" defaultValue={inputDate(selectedTask.reminder_at)} /></label>
            <button className="primary-button wide" disabled={busy}>保存日期与提醒</button>
          </form>
          <small>{selectedTask.schedule_origin === "official" ? "来自已填写的学校官方期限" : selectedTask.schedule_origin === "user" ? "已由你手动调整" : "系统按入学季倒推建议"}</small>
        </aside>
      )}
    </section>
  );
}
