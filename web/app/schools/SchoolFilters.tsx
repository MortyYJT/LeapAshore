"use client";

import { useRouter } from "next/navigation";
import { useTransition, type FormEvent, type ReactNode } from "react";

export function SchoolFilters({ controls, count, children }: {
  controls: ReactNode;
  count: number;
  children: ReactNode;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  function filter(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const query = new URLSearchParams();
    for (const [key, value] of new FormData(event.currentTarget)) {
      if (typeof value === "string" && value.trim()) query.set(key, value.trim());
    }
    const href = query.size ? `/schools?${query}` : "/schools";
    startTransition(() => router.push(href, { scroll: false }));
  }

  return (
    <section className="panel section" aria-label="学校列表">
      <form className="panel-head" action="/schools" onSubmit={filter} style={{ padding: "12px 24px" }}>
        <div className="toolbar" style={{ flex: 1 }}>
          {controls}
          <button className="btn btn-secondary school-filter-submit" type="submit" aria-busy={pending}>
            <span>筛选</span>
            {pending && <span className="school-filter-pending" role="status">筛选中…</span>}
          </button>
        </div>
        <span className="muted num" aria-live="polite">{count} 所</span>
      </form>
      <div aria-busy={pending}>{children}</div>
    </section>
  );
}
