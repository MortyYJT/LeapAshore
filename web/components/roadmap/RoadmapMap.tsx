import type { CSSProperties } from "react";

import { dateLabel } from "@/lib/overview";
import { laneWhen, layoutTall, stretchLabel, stretchWhen, type MapLane, type MapStretch, type RoadmapMap as MapModel } from "@/lib/roadmap-map";

interface Props {
  map: MapModel;
  /** Today as `YYYY-MM-DD`, the day the map was built for. */
  today: string;
  /** What the end of the line is called: the intake in words, or null without one. */
  intake: string | null;
  /** The stretch whose stations the list under the map shows. */
  selected: string | null;
  onSelect: (phaseId: string) => void;
  /** The application picked in the rail; the other lines step back. */
  picked?: string | null;
}

function vars(values: Record<string, number>): CSSProperties {
  return Object.fromEntries(Object.entries(values).map(([name, value]) => [`--${name}`, value])) as CSSProperties;
}

/**
 * What is written beside a stretch's name after its count: 「时间很紧」 for a stretch with too little
 * time left, else when it is suggested to start (lib/roadmap-map.ts, stretchWhen).
 */
function When({ stretch, today }: { stretch: MapStretch; today: string }) {
  if (stretch.phase.tight) return <span className="rm-flag">时间很紧</span>;
  const note = stretchWhen(stretch.phase, today);
  return note ? <span className="when num">{note}</span> : null;
}

function count(stretch: MapStretch): string | null {
  return stretch.phase.total ? `${stretch.phase.done}/${stretch.phase.total}` : null;
}

function laneWords(lane: MapLane): string {
  const { record } = lane.row;
  const state = lane.kind === "unknown" ? "截止日期待确认" : `${record.deadline} 截止`;
  return `${record.school} ${record.name}，${state}${lane.row.sent ? "，已提交" : ""}`;
}

/**
 * The roadmap's line map (lib/roadmap-map.ts). The preparation is the ink line: a stretch per phase
 * over its suggested window, a station per task. Each application is a line of its own colour from
 * today's bar to a terminus on its deadline; the terminus is hollow until the application is
 * submitted, when the line is retired. (The overview also fills it once the materials are ticked as
 * ready; here "filled" is kept for one meaning, done.)
 *
 * A stretch is a button: choosing one shows its stations as a list under the map, where they are
 * ticked. The stations on the map are a picture of that list and take no click. Both layouts are
 * rendered, left to right and top to bottom, and app/roadmap.css shows the one the frame's width
 * calls for, so the server's HTML already holds the drawing.
 */
export function RoadmapMap(props: Props) {
  return (
    <div className="rm-frame">
      <Wide {...props} />
      <Tall {...props} />
    </div>
  );
}

function Wide({ map, today, intake, selected, onSelect, picked = null }: Props) {
  const last = map.stretches.length - 1;
  const hasPicked = picked !== null && map.lanes.some((lane) => lane.row.record.id === picked);
  return (
    <div className="rm-wide" role="group" aria-label="准备路线" style={map.today === null ? undefined : vars({ today: map.today, soon: map.soonEnd ?? map.today })}>
      {map.today !== null && (
        <div className="rm-axis" aria-hidden="true">
          {map.ticks.map(
            (tick) =>
              tick.label && (
                <span className="rm-month" style={vars({ p: tick.position })} key={tick.date}>
                  {tick.label}
                </span>
              ),
          )}
          <span className={`rm-now num${map.todayLabel === "before" ? " is-before" : ""}`} style={vars({ p: map.today })}>
            今天 {dateLabel(today, today)}
          </span>
        </div>
      )}
      <div className={`rm-body${map.lanes.length ? " has-lanes" : ""}`}>
        {map.today !== null && (
          <div className="rm-under" aria-hidden="true">
            {map.ticks.map((tick) => (
              <i style={vars({ p: tick.position })} key={tick.date} />
            ))}
            <i className="now" style={vars({ p: map.today })} />
          </div>
        )}
        <div className={`rm-steps${intake ? " has-end" : ""}${map.stretches[0]?.label === "above" ? " starts-above" : ""}`}>
          {map.stretches.map((stretch, index) => {
            return (
              <button
                type="button"
                className={`rm-step is-${stretch.state} name-${stretch.label}${stretch.lead !== null ? " has-lead" : ""}`}
                style={vars({
                  p0: stretch.start,
                  p1: stretch.end,
                  n: Math.max(1, stretch.stations.length - stretch.onDrop),
                  ...(stretch.lead !== null ? { q0: stretch.lead } : {}),
                })}
                aria-pressed={stretch.phase.id === selected}
                aria-label={stretchLabel(stretch)}
                onClick={() => onSelect(stretch.phase.id)}
                key={stretch.phase.id}
              >
                <span className="rm-ln" />
                {/* From the end of the stretch before to today, where this one was planned: a thin lead. */}
                {stretch.lead !== null && <span className="rm-lead" />}
                {/* The drop from the stretch before, turning at 45 degrees; it is this stretch's start, or its lead's. */}
                {index > 0 && (
                  <svg className="rm-join" viewBox="-10 -4 20 48" aria-hidden="true" focusable="false">
                    <path d="M-7 0H-6L0 6V34L6 40H7" />
                  </svg>
                )}
                {stretch.stations.map((station, at) => (
                  <span
                    className={`rm-stn${at < stretch.onDrop ? " is-drop" : ""}${station.done ? " on" : ""}`}
                    style={
                      at < stretch.onDrop
                        ? vars({ g: (at + 0.5) / stretch.onDrop })
                        : vars({ f: (at - stretch.onDrop + 0.5) / (stretch.stations.length - stretch.onDrop) })
                    }
                    title={`${station.label}${station.done ? "（已做完）" : ""}`}
                    key={station.id}
                  />
                ))}
                {index === last && intake && (
                  <>
                    <span className="rm-end" />
                    <span className="rm-endlbl">{intake}</span>
                  </>
                )}
                <span className="rm-lbl">
                  <b>{stretch.phase.title}</b>
                  {count(stretch) && <span className="num">{count(stretch)}</span>}
                  <When stretch={stretch} today={today} />
                </span>
              </button>
            );
          })}
        </div>
        {map.lanes.length > 0 && (
          <div className={`rm-lanes${hasPicked ? " has-sel" : ""}${map.todayLabel === "before" ? " is-late" : ""}`}>
            <div className="rm-lanes-body" role="list" aria-label="各项目的截止日期">
              <div className="rm-zone" aria-hidden="true">
                <span>两周内</span>
              </div>
              <div className="rm-origin" aria-hidden="true" />
              {map.lanes.map((lane) => {
                const { row } = lane;
                return (
                  <div
                    className={`rm-lane line-${row.line} is-${lane.kind} tag-${lane.label}${row.sent ? " is-sent" : ""}${row.soon ? " is-soon" : ""}${row.record.id === picked ? " is-sel" : ""}`}
                    style={vars({ p1: lane.end })}
                    data-record={row.record.id}
                    role="listitem"
                    aria-label={laneWords(lane)}
                    key={row.record.id}
                  >
                    <span className="rm-run" />
                    {lane.kind !== "beyond" && <span className="rm-term" />}
                    <span className="rm-tag" aria-hidden="true">
                      <span className="bullet">{row.code}</span>
                      <span className="when">{laneWhen(lane, today)}</span>
                      {row.sent && <span className="note">已提交</span>}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Tall({ map, today, intake, selected, onSelect, picked = null }: Props) {
  const tall = layoutTall(map);
  const x = tall.journeyX;
  const apart = map.lanes.filter((lane) => lane.kind === "unknown");
  const hasPicked = picked !== null && map.lanes.some((lane) => lane.row.record.id === picked);
  const dim = (id: string) => (hasPicked && id !== picked ? " is-dim" : "");
  const thin = tall.lanes.length > 8;
  return (
    <div className="rm-tall" role="group" aria-label="准备路线">
      <div style={{ position: "relative", height: tall.height }}>
        {tall.stretches.map(({ stretch, y0, y1 }) => {
          const note = stretch.phase.tight ? null : stretchWhen(stretch.phase, today);
          return (
            <button
              type="button"
              className={`rm-tstep is-${stretch.state}`}
              style={{ left: x - 12, top: y0 + 1, height: y1 - y0 - 2 }}
              aria-pressed={stretch.phase.id === selected}
              aria-label={stretchLabel(stretch)}
              onClick={() => onSelect(stretch.phase.id)}
              key={stretch.phase.id}
            >
              <b>{stretch.phase.title}</b>
              <span className="meta">
                {count(stretch) && <span className="num">{count(stretch)}</span>}
                {count(stretch) && (note || stretch.phase.tight) && " · "}
                {stretch.phase.tight ? <span className="rm-flag">时间很紧</span> : note && <span className="when num">{note}</span>}
              </span>
            </button>
          );
        })}
        <svg aria-hidden="true" focusable="false">
          {tall.lanes.map(({ lane, x: at, y0, y1, leader }) => {
            const { row } = lane;
            const state = `line-${row.line}${row.sent ? " is-sent" : ""}${dim(row.record.id)}`;
            return (
              <g key={row.record.id}>
                <path className={`lead ${state}`} d={leader} />
                <path className={`ln ${state}${thin ? " is-thin" : ""}`} d={`M${at} ${y0}V${y1}`} />
                {lane.kind !== "beyond" && (
                  <circle className={`term ${state}`} cx={at} cy={y1} r={thin ? 3.5 : 4} />
                )}
              </g>
            );
          })}
          {tall.stretches.map(({ stretch, y0, y1, lead, stations }, index) => {
            return (
              <g key={stretch.phase.id}>
                {lead !== null && <path className="jl" d={`M${x} ${lead}V${y0}`} />}
                <path className="j" d={`M${x} ${y0}V${y1}`} />
                {index > 0 && <path className="jt" d={`M${x - 7} ${lead ?? y0}H${x + 7}`} />}
                {stations.map(({ station, y }) => (
                  <circle className={`js${station.done ? " on" : ""}`} cx={x} cy={y} r={4.5} key={station.id} />
                ))}
              </g>
            );
          })}
          {intake && <circle className="je" cx={x} cy={tall.intakeY} r={6.5} />}
          {tall.todayY !== null && (
            <rect className="now" x={tall.todayX[0]} y={tall.todayY - 5} width={tall.todayX[1] - tall.todayX[0]} height={10} rx={5} />
          )}
        </svg>
        {tall.todayY !== null && (
          <span className="rm-nowlbl num" style={{ top: tall.todayY, right: `calc(100% - ${tall.labelRight}px)` }} aria-hidden="true">
            今天 {dateLabel(today, today)}
          </span>
        )}
        {tall.lanes.map(({ lane, labelY }) => (
          <span
            className={`rm-tag line-${lane.row.line}${lane.row.soon ? " is-soon" : ""}${lane.row.sent ? " is-sent" : ""}${dim(lane.row.record.id)}`}
            style={{ top: labelY, right: `calc(100% - ${tall.labelRight}px)` }}
            title={laneWords(lane)}
            key={lane.row.record.id}
          >
            <span className="bullet">{lane.row.code}</span>
            <span className="when">{laneWhen(lane, today)}</span>
          </span>
        ))}
        {intake && (
          <span className="rm-tend" style={{ top: tall.intakeY, left: x + 16 }}>
            {intake}
          </span>
        )}
      </div>
      {apart.length > 0 && (
        <p className="rm-apart">
          截止日期待确认
          {apart.map((lane) => (
            <span className={`bullet line-${lane.row.line}`} title={`${lane.row.record.school} ${lane.row.record.name}`} key={lane.row.record.id}>
              {lane.row.code}
            </span>
          ))}
        </p>
      )}
    </div>
  );
}
