"use client";

import { useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";

import type { DeadlineView } from "@/lib/deadlines";
import type { Timeline as TimelineModel, TimelinePhase } from "@/lib/roadmap-timeline";

/** One portfolio program's deadline as `deadlineOf` chose it: open, closed (已截止) or not recorded. */
export interface DeadlineMark {
  key: string;
  label: string;
  view: DeadlineView;
}

/** The deadlines drawn on the axis: open ones only. A closed one is listed, never drawn (D3). */
export function drawnDeadlines(deadlines: DeadlineMark[]): DeadlineMark[] {
  return deadlines.filter((d) => d.view.state === "upcoming" && d.view.date && d.view.url);
}

interface Props {
  model: TimelineModel;
  today: Date;
  deadlines: DeadlineMark[];
  selected: string | null;
  onSelect: (phaseId: string) => void;
  /** Draw the entrance once, on the first render of the page. */
  animate: boolean;
  /**
   * The deadlines row and the 未收录 lane, on by default. The home page's sample has no portfolio, so it
   * turns them off rather than show a row of zeros and an empty lane.
   */
  showDeadlines?: boolean;
}

const DAY = 86_400_000;
const C = {
  ink: "var(--color-ink)",
  muted: "var(--color-muted)",
  accent: "var(--color-accent)",
  primary: "var(--color-primary)",
  track: "var(--color-track)",
  lane: "var(--color-lane)",
  done: "var(--color-done)",
  active: "var(--color-active)",
  surface: "var(--color-surface)",
  negative: "var(--color-negative)",
};

const utc = (iso: string) => new Date(`${iso.slice(0, 10)}T00:00:00Z`);
const md = (d: Date) => `${d.getUTCMonth() + 1}月${d.getUTCDate()}日`;

function onKey(event: KeyboardEvent, run: () => void) {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    run();
  }
}

// The widths the two layouts are drawn at before the box is measured; the SVG scales to its box.
const NOMINAL_WIDE = 640;
const NOMINAL_NARROW = 358;

/**
 * The roadmap's time axis (design D8): the dated phases from the earlier of today and the first phase
 * to the intake, drawn as SVG from data. Below 640px it turns vertical so its labels keep 14px.
 *
 * It used to draw nothing until it had measured its box, so the server sent an empty frame and the home
 * page's sample stayed blank until the scripts had loaded and run. Now the server and the first render
 * draw both layouts at a nominal width, CSS shows the one the screen width calls for (`.tl-wide`,
 * `.tl-narrow`), and the measured layout replaces them before the first paint after hydration.
 */
export function Timeline(props: Props) {
  const host = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState<{ width: number; phone: boolean } | null>(null);

  useLayoutEffect(() => {
    const el = host.current;
    if (!el) return;
    // Vertical below a 640px screen (design D8); a narrow box on a wide screen keeps the axis.
    const query = window.matchMedia("(max-width: 639px)");
    const measure = () => setBox({ width: Math.floor(el.clientWidth), phone: query.matches });
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    query.addEventListener("change", measure);
    return () => {
      observer.disconnect();
      query.removeEventListener("change", measure);
    };
  }, []);

  // The wide layout stays first so that, once measured, React keeps the same node and the entrance
  // animation the server's HTML started is not restarted.
  return (
    <div ref={host} style={{ minHeight: 120 }}>
      {(!box || !box.phone) && (
        <div className="tl-wide">
          <Horizontal {...props} width={box?.width || NOMINAL_WIDE} />
        </div>
      )}
      {(!box || box.phone) && (
        <div className="tl-narrow">
          <Vertical {...props} width={box?.width || NOMINAL_NARROW} />
        </div>
      )}
    </div>
  );
}

function phaseLabel(p: TimelinePhase): string {
  const start = p.start ? `建议 ${md(utc(p.start))} 开始，` : "";
  return `${p.title}，${start}${p.done}/${p.total} 项完成${p.overdue ? "，已过建议时间" : ""}${p.current ? "，当前阶段" : ""}`;
}

function Horizontal({ model, today, deadlines, selected, onSelect, animate, showDeadlines = true, width: W }: Props & { width: number }) {
  const compact = W < 760;
  const LABEL = compact ? 136 : 196, LANE = showDeadlines ? (compact ? 84 : 104) : 0, TOP = 58, PITCH = 44, BAR = 22;
  const x0 = LABEL + 8, x1 = W - LANE - 16;
  const first = model.phases[0]?.start ? utc(model.phases[0].start) : today;
  // From the start of today's day, so a deadline dated today is still on the axis.
  const start = new Date(Math.min(first.getTime(), utc(today.toISOString()).getTime()));
  const end = model.anchor ? utc(model.anchor) : today;
  const span = Math.max(DAY, end.getTime() - start.getTime());
  const xs = (d: Date) => x0 + ((d.getTime() - start.getTime()) / span) * (x1 - x0);
  // Open deadlines inside the axis are drawn; one past the intake is listed beside, not off the edge.
  const recorded = drawnDeadlines(deadlines).filter((d) => {
    const t = utc(d.view.date!).getTime();
    return t >= start.getTime() && t <= end.getTime();
  });
  const pending = deadlines.filter((d) => d.view.state === "unknown");
  const closed = deadlines.filter((d) => d.view.state === "closed");
  const rows = model.phases.length + (showDeadlines ? 1 : 0);
  const H = TOP + rows * PITCH + 8;

  const months: Date[] = [];
  for (let d = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + 1, 1)); d <= end; d = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1))) {
    months.push(d);
  }
  const monthPx = (x1 - x0) / Math.max(1, span / (30.4 * DAY));
  const step = Math.max(1, Math.ceil(64 / monthPx));
  const tx = xs(today);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} className={`timeline-svg${animate ? " tl-animate" : ""}`} role="group" aria-label="申请路线图时间轴">
      {showDeadlines && (
        <>
          <rect x={W - LANE} y={TOP - 8} width={LANE} height={H - TOP + 8} rx={14} fill={C.lane} />
          <text x={W - LANE / 2} y={TOP - 16} textAnchor="middle" fontSize={12} fill={C.muted}>{compact ? "未收录" : "未收录的截止"}</text>
        </>
      )}
      {months.map((m, i) => (
        <g key={m.toISOString()}>
          <line x1={xs(m)} x2={xs(m)} y1={TOP - 8} y2={H - 8} stroke={C.track} strokeWidth={1} />
          {i % step === 0 && (
            <text x={xs(m) + 4} y={TOP - 16} fontSize={12} fill={C.muted}>
              {m.getUTCMonth() === 0 ? `${m.getUTCFullYear()}年1月` : `${m.getUTCMonth() + 1}月`}
            </text>
          )}
        </g>
      ))}
      {model.phases.map((p, i) => {
        const y = TOP + i * PITCH;
        const bx = p.start ? xs(utc(p.start)) : x0;
        const bw = p.start && p.end ? Math.max(6, xs(utc(p.end)) - bx) : 6;
        const fill = p.current ? C.primary : p.complete ? C.done : C.track;
        const isSelected = p.id === selected;
        const select = () => onSelect(p.id);
        return (
          <g key={p.id} className="phase-hit" tabIndex={0} role="button" aria-pressed={isSelected} aria-label={phaseLabel(p)} onClick={select} onKeyDown={(e) => onKey(e, select)}>
            <rect className="hit-bg" x={0} y={y - 2} width={W - LANE - 4} height={PITCH - 4} rx={6} fill="transparent" />
            {isSelected && <rect x={0} y={y - 2} width={LABEL - 4} height={PITCH - 4} rx={10} fill={C.active} />}
            <text x={10} y={y + 15} fontSize={14} fontWeight={500} fill={C.ink}>{p.title}</text>
            <text x={10} y={y + 32} fontSize={12} fill={C.muted}>{p.start ? `建议 ${md(utc(p.start))} 起` : "未排日期"}</text>
            <rect className="tl-bar" style={{ ["--i" as string]: i }} x={bx} y={y + (PITCH - 4 - BAR) / 2} width={bw} height={BAR} rx={bw < 40 ? 5 : 11} fill={fill} />
            {/* The suggested start is dashed: the system made it up. */}
            <line x1={bx} x2={bx} y1={y - 1} y2={y + PITCH - 5} stroke={C.muted} strokeWidth={1.25} strokeDasharray="3 3" />
            {bw > 40 && (
              <text className="tl-fade num" style={{ ["--i" as string]: i }} x={bx + 10} y={y + (PITCH - 4) / 2 + 4} fontSize={12} fill={p.current ? "#ffffff" : C.ink}>
                {p.done}/{p.total}
              </text>
            )}
            {p.overdue && <circle cx={bx + bw - 8} cy={y + (PITCH - 4) / 2} r={3.5} fill={C.negative} />}
          </g>
        );
      })}
      {showDeadlines && <g>
        <text x={10} y={TOP + model.phases.length * PITCH + 15} fontSize={14} fontWeight={500} fill={C.ink}>各项目官方截止</text>
        <text x={10} y={TOP + model.phases.length * PITCH + 32} fontSize={12} fill={C.muted}>
          {deadlines.length - pending.length - closed.length} 个待截止 · {closed.length} 个已截止 · {pending.length} 个未收录
        </text>
        {recorded.map((d) => {
          const x = xs(utc(d.view.date!));
          return (
            <a key={d.key} className="deadline-mark" href={d.view.url!} target="_blank" rel="noreferrer" aria-label={`${d.label} 官方截止 ${d.view.date}`}>
              <line x1={x} x2={x} y1={TOP + model.phases.length * PITCH} y2={TOP + model.phases.length * PITCH + PITCH - 6} stroke={C.ink} strokeWidth={2} />
              <circle cx={x} cy={TOP + model.phases.length * PITCH + (PITCH - 4) / 2} r={5} fill={C.ink} />
            </a>
          );
        })}
        {pending.length > 0 && (
          <g aria-label={`${pending.length} 个项目的官方截止未收录`}>
            <circle cx={W - LANE + 22} cy={TOP + model.phases.length * PITCH + (PITCH - 4) / 2} r={6} fill={C.surface} stroke={C.muted} strokeWidth={1.5} />
            <text x={W - LANE + 34} y={TOP + model.phases.length * PITCH + (PITCH - 4) / 2 + 4} fontSize={12} fill={C.ink}>未收录 {pending.length}</text>
          </g>
        )}
      </g>}
      {model.dated && tx >= x0 - 1 && tx <= x1 + 1 && (
        <g>
          <line className="tl-today" x1={tx} x2={tx} y1={TOP - 50} y2={H - 8} stroke={C.accent} strokeWidth={1.5} strokeLinecap="round" />
          <text x={tx + 6} y={TOP - 40} fontSize={12} fontWeight={500} fill={C.ink}>今天 {md(today)}</text>
        </g>
      )}
    </svg>
  );
}

/** Below 640px: time runs down, one row per phase, so labels keep 14px instead of shrinking. */
function Vertical({ model, today, deadlines, selected, onSelect, animate, showDeadlines = true, width: W }: Props & { width: number }) {
  const ROW = 64, TRACK_X = 18, TOP = 8;
  const todayIso = today.toISOString().slice(0, 10);
  const rows = model.phases.length;
  const H = TOP + rows * ROW + (showDeadlines ? 64 : 8);
  const pending = deadlines.filter((d) => d.view.state === "unknown").length;
  const closed = deadlines.filter((d) => d.view.state === "closed").length;
  const open = deadlines.length - pending - closed;
  // Today sits inside the phase whose span holds it, at its share of that span.
  let todayY: number | null = null;
  model.phases.forEach((p, i) => {
    if (p.start && p.end && todayIso >= p.start && todayIso < p.end) {
      const share = (utc(todayIso).getTime() - utc(p.start).getTime()) / Math.max(DAY, utc(p.end).getTime() - utc(p.start).getTime());
      todayY = TOP + i * ROW + share * ROW;
    }
  });
  if (todayY === null && model.dated && model.phases[0]?.start && todayIso < model.phases[0].start) todayY = TOP;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} className={`timeline-svg${animate ? " tl-animate" : ""}`} role="group" aria-label="申请路线图时间轴">
      <line x1={TRACK_X} x2={TRACK_X} y1={TOP} y2={TOP + rows * ROW} stroke={C.track} strokeWidth={6} strokeLinecap="round" />
      {model.phases.map((p, i) => {
        const y = TOP + i * ROW;
        const isSelected = p.id === selected;
        const select = () => onSelect(p.id);
        return (
          <g key={p.id} className="phase-hit" tabIndex={0} role="button" aria-pressed={isSelected} aria-label={phaseLabel(p)} onClick={select} onKeyDown={(e) => onKey(e, select)}>
            <rect className="hit-bg" x={0} y={y + 2} width={W} height={ROW - 4} rx={10} fill={isSelected ? C.active : "transparent"} />
            <rect className="tl-bar" style={{ ["--i" as string]: i }} x={TRACK_X - 3} y={y + 6} width={6} height={ROW - 12} rx={3} fill={p.current ? C.primary : p.complete ? C.done : C.track} />
            <line x1={TRACK_X - 10} x2={TRACK_X + 10} y1={y + 6} y2={y + 6} stroke={C.muted} strokeWidth={1.25} strokeDasharray="3 3" />
            <text x={40} y={y + 26} fontSize={14} fontWeight={500} fill={C.ink}>{p.title}</text>
            <text x={40} y={y + 46} fontSize={12} fill={C.muted}>
              {p.start ? `建议 ${md(utc(p.start))} 起` : "未排日期"} · {p.done}/{p.total}
              {p.overdue ? " · 已过建议时间" : ""}
            </text>
            {p.overdue && <circle cx={W - 14} cy={y + ROW / 2} r={3.5} fill={C.negative} />}
          </g>
        );
      })}
      {todayY !== null && (
        <g>
          <line className="tl-today" x1={4} x2={W - 4} y1={todayY} y2={todayY} stroke={C.accent} strokeWidth={1.5} strokeLinecap="round" />
          <text x={W - 6} y={(todayY as number) - 6} textAnchor="end" fontSize={12} fontWeight={500} fill={C.ink}>今天</text>
        </g>
      )}
      {showDeadlines && <g>
        <circle cx={TRACK_X} cy={TOP + rows * ROW + 26} r={6} fill={C.surface} stroke={C.muted} strokeWidth={1.5} />
        <text x={40} y={TOP + rows * ROW + 24} fontSize={14} fontWeight={500} fill={C.ink}>各项目官方截止</text>
        <text x={40} y={TOP + rows * ROW + 44} fontSize={12} fill={C.muted}>{open} 个待截止 · {closed} 个已截止 · {pending} 个未收录</text>
      </g>}
    </svg>
  );
}
