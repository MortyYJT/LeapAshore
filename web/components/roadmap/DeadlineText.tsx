import type { DeadlineView } from "@/lib/deadlines";

/**
 * One deadline as a cell reads it (openspec requirement-dates D3): an open one is a solid link to the
 * page that states it, a past one is marked 已截止, and an unknown one is the hollow 未收录 marker.
 */
export function DeadlineText({ view, showLabel = true }: { view: DeadlineView; showLabel?: boolean }) {
  if (view.state === "unknown" || !view.date || !view.url) {
    return (
      <span className="deadline-unknown">
        <span className="hollow" />
        未收录
      </span>
    );
  }
  // The round's name, or where an entered date came from; a caller that prints these itself hides them.
  const note = showLabel ? (view.origin === "entered" ? "组合里记录的日期" : view.label) : null;
  return (
    <span className={`deadline deadline-${view.state}`}>
      {view.state === "closed" && <span className="pill pill-outline">已截止</span>}{" "}
      <a className="num" href={view.url} target="_blank" rel="noreferrer">
        {view.date}
      </a>
      {note && <span className="small muted deadline-label"> · {note}</span>}
    </span>
  );
}
