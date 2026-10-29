import type { Metadata } from "next";
import Link from "next/link";

import { SchoolMark, SourceNote } from "@/components/ui";
import { universityIdsFor, type UniversityRow } from "@/lib/catalog";
import { overseasInstitutions } from "@/lib/catalog-server";
import {
  filterSchools,
  institutionSlug,
  paginateSchools,
  schoolListHref,
  schoolQsRanges,
  schoolQuery,
  schoolRegions,
  sortSchools,
} from "@/lib/prototype-library";
import { serverUniversities } from "@/lib/server-api";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "学校库 · 鱼跃彼岸" };

async function universities(): Promise<UniversityRow[] | null> {
  try {
    return await serverUniversities();
  } catch {
    return null;
  }
}

/** The school library: 346 schools, filterable by name, region and QS band, with collected program counts. */
export default async function SchoolsPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const query = schoolQuery(await searchParams);
  const rows = await universities();
  const list = sortSchools(filterSchools(overseasInstitutions, query));
  const page = paginateSchools(list, query.page);
  const counts = (school: (typeof list)[number]) => {
    if (!rows) return null;
    const ids = new Set(universityIdsFor(school, rows));
    const mine = rows.filter((r) => ids.has(r.id));
    return { programs: mine.reduce((n, r) => n + r.programCount, 0), stated: mine.reduce((n, r) => n + r.withRequirementsCount, 0) };
  };
  const qs = new Set(query.qs?.split(",") ?? []);

  return (
    <>
      <main className="page">
        <div className="title-row">
          <div>
            <h1>学校库</h1>
            <p className="lede">
              QS 2027 前 300，加上澳洲、香港、澳门的其他大学，共 <strong className="num">{overseasInstitutions.length}</strong> 所，按 QS 名次排列。
            </p>
          </div>
        </div>
        <section className="panel section" aria-label="学校列表">
          <form className="panel-head" action="/schools" style={{ padding: "12px 24px" }}>
            <div className="toolbar" style={{ flex: 1 }}>
              <label className="sr-only" htmlFor="q">搜索学校</label>
              <input className="input" id="q" name="q" type="search" placeholder="搜索中文或英文校名" defaultValue={query.q ?? ""} style={{ maxWidth: 280 }} />
              <label className="sr-only" htmlFor="region">地区</label>
              <select className="select" id="region" name="region" defaultValue={query.region ?? ""} style={{ width: 140 }}>
                <option value="">全部地区</option>
                {schoolRegions.map((r) => (
                  <option key={r}>{r}</option>
                ))}
              </select>
              <label className="sr-only" htmlFor="qs">QS 名次</label>
              <select className="select" id="qs" name="qs" defaultValue={[...qs][0] ?? ""} style={{ width: 150 }}>
                <option value="">QS 名次不限</option>
                {schoolQsRanges.map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
              <button className="btn btn-secondary" type="submit">
                筛选
              </button>
              {(query.q || query.region || query.qs) && (
                <Link className="btn btn-text" href="/schools">
                  清空
                </Link>
              )}
            </div>
            <span className="muted num">{list.length} 所</span>
          </form>
          <table className="stack">
            <thead>
              <tr>
                <th className="num" style={{ width: 72 }}>QS</th>
                <th>学校</th>
                <th className="hide-phone">地区 · 城市</th>
                <th className="num">已收录项目</th>
              </tr>
            </thead>
            <tbody>
              {page.items.length === 0 && (
                <tr>
                  <td colSpan={4} className="wide">
                    <div className="empty">没有符合条件的学校。换个关键词，或清空地区和名次筛选。</div>
                  </td>
                </tr>
              )}
              {page.items.map((s) => {
                const name = s.name_zh || s.name_en || "未知";
                const c = counts(s);
                return (
                  <tr key={institutionSlug(s)}>
                    <td className="num muted">{s.qs_rank ?? "—"}</td>
                    <td className="wide">
                      <div className="ident">
                        <SchoolMark logo={s.logo} name={name} />
                        <div className="two-line">
                          <Link className="l1" href={`/schools/${encodeURIComponent(institutionSlug(s))}`}>
                            {name}
                            {s.name_zh_kind === "常用译名" && <span className="muted small" style={{ marginLeft: 6, fontWeight: 400 }}>常用译名</span>}
                          </Link>
                          <div className="l2">{s.name_en}</div>
                        </div>
                      </div>
                    </td>
                    <td className="muted hide-phone">
                      {s.region_zh ?? s.country}
                      {s.city ? ` · ${s.city}` : ""}
                    </td>
                    <td className="num">
                      {c === null ? <span className="muted">未知</span> : c.programs === 0 ? <span className="muted">未收录</span> : <>{c.programs}<span className="muted small"> · 有要求 {c.stated}</span></>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="pager">
            <span className="muted num">
              第 {page.page} / {page.pages} 页
            </span>
            <span className="toolbar">
              {page.page > 1 && <Link className="btn btn-secondary btn-small" href={schoolListHref(query, { page: String(page.page - 1) })}>上一页</Link>}
              {page.page < page.pages && <Link className="btn btn-secondary btn-small" href={schoolListHref(query, { page: String(page.page + 1) })}>下一页</Link>}
            </span>
          </div>
        </section>
      </main>
      <SourceNote>
        入选依据：QS World University Rankings 2027 前 300（2026-06-18 发布，QS 条款限制转载），及澳洲 CRICOS、香港教资会等官方名单补全。中文名标「常用译名」的不是学校官方中文名。校徽归各校所有，仅用于识别，不代表合作关系。
      </SourceNote>
    </>
  );
}
