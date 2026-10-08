"use client";

import { UNKNOWN, toProgramLabel } from "@/lib/programs-source";
import { PHASE_DEFS } from "@/lib/roadmap";
import type { PortfolioItem, Roadmap, RoadmapPhase } from "@/lib/types";

const STATUS_META: Record<
  RoadmapPhase["status"],
  { label: string; color: string; bg: string }
> = {
  pending: { label: "待开始", color: "var(--color-ink-soft)", bg: "var(--color-line)" },
  in_progress: { label: "进行中", color: "#9a6700", bg: "var(--color-warn-soft)" },
  completed: { label: "已完成", color: "var(--color-brand-dark)", bg: "var(--color-brand-soft)" },
  overdue: { label: "已逾期", color: "#c9184a", bg: "#ffe0e6" },
};

const TIER_CLASS: Record<string, string> = { 冲: "tag-chong", 稳: "tag-wen", 保: "tag-bao" };

interface Props {
  roadmap: Roadmap;
  portfolio: PortfolioItem[];
  selectedPhase: string;
  onSelectPhase: (id: string) => void;
  onToggleMaterial: (materialId: string, checked: boolean) => void;
  /**
   * Upload a file for one requirement.
   *
   * The requirement travels as the material's own key rather than as a task id: `buildRoadmap` builds
   * these rows from the served definition and never sees the applicant's task rows, so the id the
   * server needs is resolved in `page.tsx`, which is where those rows already are. A material whose
   * requirement has no stored task row yet still uploads — the file is stored without one, which is a
   * fact about the roadmap rather than a reason to refuse the applicant's file.
   */
  onUploadMaterial: (materialId: string, file: File) => void;
}

/** The file types the upload route accepts, so the picker does not offer what it would refuse. */
const ACCEPTED_UPLOADS = ".pdf,.png,.jpg,.jpeg,.docx";

export default function FlowView({
  roadmap,
  portfolio,
  selectedPhase,
  onSelectPhase,
  onToggleMaterial,
  onUploadMaterial,
}: Props) {
  void PHASE_DEFS;
  const phase = roadmap.phases.find((p) => p.id === selectedPhase) ?? roadmap.phases[0];
  const doneTotal = roadmap.phases.reduce((n, p) => n + p.tasks.filter((t) => t.done).length, 0);
  const allTotal = roadmap.phases.reduce((n, p) => n + p.tasks.length, 0);
  const overdueCount = roadmap.phases.filter((p) => p.status === "overdue").length;

  return (
    <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
      {/* 左：流程图 */}
      <section>
        <div className="mb-4 flex items-baseline justify-between">
          <h2 className="text-lg font-extrabold">申请流程</h2>
          <span className="text-sm font-bold text-[var(--color-brand-dark)]">
            {doneTotal}/{allTotal} 项材料
          </span>
        </div>

        {overdueCount > 0 && (
          <div className="mb-4 rounded-xl border-2 border-[var(--color-danger)] bg-[var(--color-danger-soft)] p-3">
            <p className="text-sm leading-relaxed text-[var(--color-danger)]">
              有 {overdueCount} 个阶段的建议时间已过。已经过了不等于来不及，但前期准备要压缩，
              并以官网实际截止日期为准。
            </p>
          </div>
        )}

        <ol className="relative">
          {roadmap.phases.map((p, i) => {
            const meta = STATUS_META[p.status];
            const done = p.tasks.filter((t) => t.done).length;
            const active = p.id === phase.id;
            return (
              <li key={p.id} className="relative pb-3 pl-8">
                {/* 连接线 */}
                {i < roadmap.phases.length - 1 && (
                  <span
                    className="absolute left-[11px] top-6 h-full w-0.5"
                    style={{ background: p.status === "completed" ? "var(--color-brand)" : "var(--color-line)" }}
                  />
                )}
                {/* 节点圆点 */}
                <span
                  className="absolute left-0 top-4 flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold text-white"
                  style={{
                    background:
                      p.status === "completed"
                        ? "var(--color-brand)"
                        : p.status === "overdue"
                          ? "var(--color-danger)"
                          : p.status === "in_progress"
                            ? "var(--color-warn)"
                            : "#cbd2d9",
                  }}
                >
                  {p.status === "completed" ? "✓" : i + 1}
                </span>
                <button
                  onClick={() => onSelectPhase(p.id)}
                  className="w-full rounded-2xl border-2 bg-white p-4 text-left transition-all"
                  style={{
                    borderColor: active ? "var(--color-brand)" : "var(--color-line)",
                    boxShadow: active ? "0 2px 0 var(--color-brand)" : "0 2px 0 var(--color-line)",
                  }}
                >
                  <div className="flex items-center justify-between gap-2">
                    <strong className="text-[15px]">{p.title}</strong>
                    <span
                      className="tag"
                      style={{ color: meta.color, background: meta.bg }}
                    >
                      {meta.label}
                    </span>
                  </div>
                  <div className="mt-1 text-xs text-[var(--color-ink-soft)]">
                    建议 {p.suggestedAt} · 材料 {done}/{p.tasks.length}
                  </div>
                </button>
              </li>
            );
          })}
        </ol>

        {portfolio.length > 0 && (
          <div className="mt-6 rounded-2xl border-2 border-dashed border-[var(--color-line)] p-4">
            <div className="text-xs font-bold text-[var(--color-ink-soft)]">
              申请项目分支（{portfolio.length} 个）
            </div>
            {/*
              The branch list is where this view and the portfolio meet: the phases above are roadmap
              data and name no program, so the only program copy on this screen comes from the row the
              server sent. It used to be resolved against `web/lib/programs.ts`, which printed a bare
              slug for anything the constants array does not carry.
            */}
            <ul className="mt-2 grid gap-2 text-sm" data-testid="flow-program-branches">
              {portfolio.map((item) => {
                const university = item.program?.university ?? UNKNOWN;
                const name = toProgramLabel(item.program) ?? UNKNOWN;
                return (
                  <li key={item.programSlug} className="flex items-start gap-2">
                    {item.needsReview ? (
                      <span className="tag tag-muted">自选</span>
                    ) : (
                      <span className={`tag ${TIER_CLASS[item.tier]}`}>{item.tier}</span>
                    )}
                    <span className="leading-snug">
                      <strong>{university}</strong>
                      <span className="block text-xs text-[var(--color-ink-soft)]">{name}</span>
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </section>

      {/* 右：节点详情 */}
      <section>
        <div className="card">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-xl font-extrabold">{phase.title}</h2>
              <p className="mt-1 text-sm text-[var(--color-ink-soft)]">{phase.detail}</p>
            </div>
            <span
              className="tag"
              style={{
                color: STATUS_META[phase.status].color,
                background: STATUS_META[phase.status].bg,
              }}
            >
              {STATUS_META[phase.status].label}
            </span>
          </div>

          <div className="mt-5 grid grid-cols-2 gap-3 text-sm">
            <div className="rounded-xl bg-[var(--color-surface)] p-3">
              <div className="text-xs text-[var(--color-ink-soft)]">建议开始</div>
              <div className="font-bold">{phase.suggestedAt}</div>
              <div className="mt-0.5 text-[11px] text-[var(--color-ink-soft)]">系统倒推 · 非官方日期</div>
            </div>
            <div className="rounded-xl bg-[var(--color-surface)] p-3">
              <div className="text-xs text-[var(--color-ink-soft)]">官方截止日期</div>
              <div className="font-bold text-[var(--color-ink-soft)]">未录入</div>
              <div className="mt-0.5 text-[11px] text-[var(--color-ink-soft)]">
                以官网为准
              </div>
            </div>
          </div>

          <h3 className="mt-6 text-sm font-bold text-[var(--color-ink-soft)]">
            要准备的材料（{phase.tasks.filter((t) => t.done).length}/{phase.tasks.length}）
          </h3>
          <ul className="mt-3 grid gap-2">
            {phase.tasks.map((t) => (
              // Two controls, so the row is a container rather than one label: a label may not contain
              // another, and nesting the upload picker inside the tick's label makes a click on either
              // one fire both.
              <li
                key={t.materialId}
                className="flex items-start gap-2 rounded-xl border-2 border-[var(--color-line)] transition-colors hover:bg-[var(--color-surface)]"
              >
                <label className="flex flex-1 cursor-pointer items-start gap-3 p-3">
                  <input
                    type="checkbox"
                    className="mt-1 h-5 w-5 accent-[var(--color-brand)]"
                    checked={t.done}
                    onChange={(event) => onToggleMaterial(t.materialId, event.target.checked)}
                  />
                  <span>
                    <span
                      className={`text-sm font-bold ${t.done ? "text-[var(--color-ink-soft)] line-through" : ""}`}
                    >
                      {t.label}
                    </span>
                    <span className="mt-0.5 block text-xs leading-relaxed text-[var(--color-ink-soft)]">
                      {t.detail}
                    </span>
                  </span>
                </label>
                <label
                  className="m-2 shrink-0 cursor-pointer rounded-lg border-2 border-[var(--color-line)] px-2 py-1 text-xs font-bold whitespace-nowrap"
                  data-testid="upload-material"
                >
                  上传材料
                  <input
                    className="hidden"
                    type="file"
                    accept={ACCEPTED_UPLOADS}
                    onChange={(event) => {
                      const file = event.target.files?.[0];
                      if (file) onUploadMaterial(t.materialId, file);
                      // Cleared so picking the same file again still fires a change event.
                      event.target.value = "";
                    }}
                  />
                </label>
              </li>
            ))}
          </ul>
        </div>
      </section>
    </div>
  );
}
