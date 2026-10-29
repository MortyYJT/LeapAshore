import type { Metadata } from "next";
import Link from "next/link";

import { ProgramTable } from "@/components/catalog/ProgramTable";
import { SourceNote } from "@/components/ui";
import { serverProgramPage } from "@/lib/server-api";
import { STUDY_AREAS } from "@/lib/taxonomy";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "项目库 · 鱼跃彼岸" };
const PAGE = 30;

const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v) ?? "";

/** The program library: every program the catalogue holds, searchable and filterable by study area. */
export default async function ProgramsPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  const q = one(params.q).slice(0, 100);
  const field = STUDY_AREAS.includes(one(params.field) as (typeof STUDY_AREAS)[number]) ? one(params.field) : "";
  const stated = one(params.stated) === "1";
  const pageNo = Math.max(1, Number(one(params.page)) || 1);

  let page: Awaited<ReturnType<typeof serverProgramPage>> | null = null;
  try {
    page = await serverProgramPage({ q, field: field || undefined, hasRequirements: stated ? true : undefined, limit: PAGE, offset: (pageNo - 1) * PAGE });
  } catch {
    page = null;
  }
  const pages = page ? Math.max(1, Math.ceil(page.total / PAGE)) : 1;
  const href = (n: number) => {
    const next = new URLSearchParams();
    if (q) next.set("q", q);
    if (field) next.set("field", field);
    if (stated) next.set("stated", "1");
    if (n > 1) next.set("page", String(n));
    return `/programs${next.size ? `?${next}` : ""}`;
  };

  return (
    <>
      <main className="page">
        <div className="title-row">
          <div>
            <h1>项目库</h1>
            <p className="lede">授课型硕士项目，来自澳洲 CRICOS 登记和各校官网。录取要求按官网原文收录，没有收录的显示为未收录。</p>
          </div>
        </div>
        <section className="panel section" aria-label="项目列表">
          <form className="panel-head" action="/programs" style={{ padding: "12px 24px" }}>
            <div className="toolbar" style={{ flex: 1 }}>
              <label className="sr-only" htmlFor="q">搜索项目</label>
              <input className="input" id="q" name="q" type="search" placeholder="项目名或学校，例如 Data Science" defaultValue={q} style={{ maxWidth: 280 }} />
              <label className="sr-only" htmlFor="field">方向</label>
              <select className="select" id="field" name="field" defaultValue={field} style={{ width: 160 }}>
                <option value="">全部方向</option>
                {STUDY_AREAS.map((a) => (
                  <option key={a}>{a}</option>
                ))}
              </select>
              <label className="toolbar muted" style={{ gap: 6 }}>
                <input type="checkbox" name="stated" value="1" defaultChecked={stated} />
                只看已收录要求
              </label>
              <button className="btn btn-secondary" type="submit">筛选</button>
              {(q || field || stated) && <Link className="btn btn-text" href="/programs">清空</Link>}
            </div>
            <span className="muted num">{page ? `${page.total.toLocaleString("en")} 个` : ""}</span>
          </form>
          {page ? (
            <ProgramTable programs={page.programs} empty="没有符合条件的项目。换个关键词，或清空方向筛选。" />
          ) : (
            <div className="panel-pad"><div className="empty">项目读取失败，请稍后再试。</div></div>
          )}
          {page && pages > 1 && (
            <div className="pager">
              <span className="muted num">第 {pageNo} / {pages} 页</span>
              <span className="toolbar">
                {pageNo > 1 && <Link className="btn btn-secondary btn-small" href={href(pageNo - 1)}>上一页</Link>}
                {pageNo < pages && <Link className="btn btn-secondary btn-small" href={href(pageNo + 1)}>下一页</Link>}
              </span>
            </div>
          )}
        </section>
      </main>
      <SourceNote>
        澳洲项目的学制和学费来自 CRICOS Courses（澳大利亚教育部，data.gov.au，CC BY 2.5 AU），学费是整个课程的总学费。其他国家的项目和所有录取要求摘自各校官网；方向是按项目名称自动归类的，用来检索，不是官方分类。
      </SourceNote>
    </>
  );
}
