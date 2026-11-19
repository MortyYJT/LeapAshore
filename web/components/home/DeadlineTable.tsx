import Link from "next/link";
import type { CSSProperties, ReactNode } from "react";

import { Icon } from "@/components/shell/Icon";
import { RECORD_STATUSES } from "@/lib/application-records";
import { dateLabel, type Overview, type OverviewRow } from "@/lib/overview";

/** Where a line of unknown length ends: far enough to read as a line, short enough to claim no date. */
const UNKNOWN_POSITION = 0.42;

/** `--p` is the share of the axis a line covers; app/overview.css turns it into a width. */
function at(position: number): CSSProperties {
  return { "--p": position } as CSSProperties;
}

/** The form on 我的申请 for one record, where its date, round, status and materials are edited. */
export function editHref(row: OverviewRow): string {
  return `/applications?edit=${encodeURIComponent(row.record.id)}`;
}

/**
 * The deadline table: one line per application on a shared linear axis that starts at today's bar.
 *
 * What a row draws follows what is known. A date ahead is a line to a stop, filled once the applicant
 * has ticked the materials as ready; a date past the end of the axis is a line that runs off it, with
 * no stop. No date is a dotted line to a dashed stop. A date that has passed has no line at all. A
 * submitted application's line is retired grey. `empty` replaces the rows when
 * there are none, so the axis is still drawn.
 */
export function DeadlineTable({
  model,
  today,
  labelledBy,
  selected = null,
  flash = null,
  empty,
}: {
  model: Overview;
  today: string;
  labelledBy: string;
  selected?: string | null;
  flash?: string | null;
  empty?: ReactNode;
}) {
  const picked = selected && model.rows.some((row) => row.record.id === selected) ? selected : null;
  return (
    <div className="lt-frame">
      <div className={`lt${picked ? " has-sel" : ""}${model.rows.length ? "" : " is-empty"}`} role="table" aria-labelledby={labelledBy}>
        <div className="lt-head" role="row">
          <span role="columnheader">申请</span>
          <div className="axis" role="columnheader" aria-label="时间">
            <span className="a-today num">今天 {dateLabel(today, today)}</span>
            {model.ticks.map(
              (tick) =>
                tick.label && (
                  <span className="a-month" style={at(tick.position)} key={tick.date}>
                    {tick.label}
                  </span>
                ),
            )}
          </div>
          <span className="h-due" role="columnheader">
            还剩
          </span>
          <span role="columnheader">状态与材料</span>
        </div>
        <div className="lt-under" aria-hidden="true">
          <div className="zone" style={at(model.soonPosition)}>
            <span>两周内</span>
          </div>
          {model.ticks.map((tick) => (
            <div className="tick" style={at(tick.position)} key={tick.date} />
          ))}
        </div>
        <div className="lt-over" aria-hidden="true">
          <div className="origin" />
        </div>
        {model.rows.map((row) => (
          <Row row={row} today={today} picked={picked === row.record.id} flash={flash === row.record.id} key={row.record.id} />
        ))}
        {!model.rows.length && empty && (
          <div role="row">
            <div role="cell">{empty}</div>
          </div>
        )}
      </div>
    </div>
  );
}

function Row({ row, today, picked, flash }: { row: OverviewRow; today: string; picked: boolean; flash: boolean }) {
  const { record } = row;
  const status = RECORD_STATUSES.find(([value]) => value === record.status)?.[1] ?? record.status;
  return (
    <div className={`lt-row line-${row.line}${row.sent ? " is-sent" : ""}${picked ? " is-sel" : ""}${flash ? " is-flash" : ""}`} role="row">
      <div className="c-id" role="cell">
        <span className="bullet">{row.code}</span>
        <div className="txt">
          <div className="school">
            <Link href={editHref(row)} title="在「我的申请」里查看和修改">
              {record.school}
            </Link>
            {record.round && <span className="round">{record.round}</span>}
          </div>
          <div className="program">{record.name}</div>
        </div>
      </div>
      <Track row={row} today={today} />
      <Due row={row} />
      <div className="c-state" role="cell">
        <span className={`st${row.sent ? " is-sent" : record.status === "considering" ? " is-idea" : ""}`}>
          {row.sent && <Icon name="check" />}
          {status}
        </span>
        {!row.sent && (
          <span className="mat">
            <span className={`stop${record.materialsReady ? " on" : ""}`} aria-hidden="true" />
            {record.materialsReady ? "材料已就绪" : "材料准备中"}
          </span>
        )}
      </div>
    </div>
  );
}

function Track({ row, today }: { row: OverviewRow; today: string }) {
  const { record } = row;
  const date = record.deadline ? dateLabel(record.deadline, today) : null;
  // Nothing ahead of today to draw: a passed date, or a submitted application without a date.
  if (row.position === null && (row.sent || row.days !== null)) {
    return (
      <div className={`c-track is-off${row.sent ? " is-sent" : ""}`} role="cell" aria-label={date ? `${record.deadline} 的截止日期已过` : "没有截止日期"}>
        <span className="org" />
        {date && (
          <span className="when">
            <b>{date}</b>
            {row.sent ? "" : "已过"}
          </span>
        )}
      </div>
    );
  }
  if (row.position === null) {
    return (
      <div className="c-track is-unknown" role="cell" aria-label="截止日期待确认" style={at(UNKNOWN_POSITION)}>
        <span className="org" />
        <span className="ln" />
        <span className="stn" />
        <span className="when">待确认</span>
      </div>
    );
  }
  return (
    <div
      className={`c-track${row.sent ? " is-sent" : record.materialsReady ? " is-complete" : ""}${row.beyond ? " is-beyond" : ""}`}
      role="cell"
      aria-label={`${record.deadline} 截止`}
      style={at(row.position)}
    >
      <span className="org" />
      <span className="ln" />
      {!row.beyond && <span className="stn" />}
      <span className="when">{date}</span>
    </div>
  );
}

function Due({ row }: { row: OverviewRow }) {
  if (row.sent || row.days === null) {
    return (
      <div className="c-due" role="cell">
        <span className="none" aria-label={row.sent ? "已提交" : "待确认"}>
          —
        </span>
      </div>
    );
  }
  // A date is the applicant's own until they have checked it against the official page.
  const unchecked = !row.record.checkedAt && (
    <span className="unchecked" title={row.record.deadlineOrigin === "collected" ? "学校库采集的日期，请对照官网复核" : "还没有对照官网核对"}>
      待核对
    </span>
  );
  if (row.days < 0) {
    return (
      <div className="c-due" role="cell">
        <span className="past">已截止</span>
        {unchecked}
      </div>
    );
  }
  return (
    <div className={`c-due${row.soon ? " is-soon" : ""}`} role="cell">
      {row.days === 0 ? (
        <span className="n is-word">今天</span>
      ) : (
        <>
          <span className="n">{row.days}</span>
          <span className="u">天</span>
        </>
      )}
      {unchecked}
    </div>
  );
}
