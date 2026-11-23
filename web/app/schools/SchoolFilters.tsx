"use client";

import { type FormEvent, type ReactNode } from "react";

import { useNavigation } from "@/components/shell/Navigation";

/**
 * The filter bar and the list under it. A new query (this form, the pager, or a search from Cmd-K
 * while the list is on screen) keeps the rows on screen until the new ones arrive; meanwhile the
 * button says 筛选中… and the rows step back (app/motion.css), so it is clear they are about to change.
 */
export function SchoolFilters({ controls, count, programs = null, children }: {
  controls: ReactNode;
  count: number;
  /** Programs whose name holds the search, when there was one. */
  programs?: number | null;
  children: ReactNode;
}) {
  const { push, refreshing } = useNavigation();

  function filter(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const query = new URLSearchParams();
    for (const [key, value] of new FormData(event.currentTarget)) {
      if (typeof value === "string" && value.trim()) query.set(key, value.trim());
    }
    push(query.size ? `/schools?${query}` : "/schools", { scroll: false });
  }

  return (
    <section className="panel section" aria-label="学校列表">
      <form className="panel-head" action="/schools" onSubmit={filter} style={{ padding: "12px 24px" }}>
        <div className="toolbar" style={{ flex: 1 }}>
          {controls}
          <button className="btn btn-secondary school-filter-submit" type="submit" aria-busy={refreshing}>
            <span>筛选</span>
            {refreshing && <span className="school-filter-pending" role="status">筛选中…</span>}
          </button>
        </div>
        <span className="muted num" aria-live="polite">
          {count} 所{programs ? ` · ${programs} 个项目` : ""}
        </span>
      </form>
      <div className="school-results" aria-busy={refreshing}>{children}</div>
    </section>
  );
}
