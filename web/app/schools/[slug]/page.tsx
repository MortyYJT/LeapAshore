import type { Metadata } from "next";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { ProgramTable } from "@/components/catalog/ProgramTable";
import { SchoolMark } from "@/components/ui";
import { programColumns, universityIdsFor } from "@/lib/catalog";
import { masterPrograms, overseasInstitutions } from "@/lib/catalog-server";
import { institutionSlug } from "@/lib/prototype-library";
import { serverProgramPage, serverUniversities } from "@/lib/server-api";
import { STUDY_AREAS } from "@/lib/taxonomy";
import type { Program } from "@/lib/types";

export const dynamic = "force-dynamic";
const PAGE = 30;

const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v) ?? "";

function schoolFor(slug: string) {
  return overseasInstitutions.find((s) => institutionSlug(s) === slug) ?? null;
}

/** Every program the catalogue holds for these rows, a page (the route's cap of 100) at a time. */
async function allPrograms(provider: string[]): Promise<Program[]> {
  const first = await serverProgramPage({ provider, limit: 100, offset: 0 });
  const rest = [];
  for (let offset = 100; offset < first.total; offset += 100) rest.push(serverProgramPage({ provider, limit: 100, offset }));
  return [...first.programs, ...(await Promise.all(rest)).flatMap((page) => page.programs)];
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const school = schoolFor(decodeURIComponent((await params).slug));
  return { title: `${school?.name_zh ?? school?.name_en ?? "学校"} · 鱼跃彼岸` };
}

/**
 * One school and the programs the catalogue holds for it, searchable by name and filterable by study area.
 * The only way to browse programs: the catalogue-wide list was removed. The API serves programs with a
 * stated requirement first.
 */
export default async function SchoolPage({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const slug = decodeURIComponent((await params).slug);
  const school = schoolFor(slug);
  if (!school) {
    // A CRICOS provider code (the spec's own example is /schools/00008C) lands on its school.
    const byProvider = overseasInstitutions.find((s) => s.cricos_codes?.includes(slug));
    if (byProvider) redirect(`/schools/${encodeURIComponent(institutionSlug(byProvider))}`);
    notFound();
  }
  const query = await searchParams;
  const q = one(query.q).slice(0, 100);
  const field = STUDY_AREAS.includes(one(query.field) as (typeof STUDY_AREAS)[number]) ? one(query.field) : "";
  const pageNo = Math.max(1, Number(one(query.page)) || 1);
  const name = school.name_zh || school.name_en || "未知";
  const base = `/schools/${encodeURIComponent(institutionSlug(school))}`;

  let all: Program[] | null = null;
  let page: { programs: Program[]; total: number } | null = null;
  try {
    const ids = universityIdsFor(school, await serverUniversities());
    if (ids.length === 0) {
      all = [];
      page = { programs: [], total: 0 };
    } else {
      [all, page] = await Promise.all([
        allPrograms(ids),
        serverProgramPage({ provider: ids, q, field: field || undefined, limit: PAGE, offset: (pageNo - 1) * PAGE }),
      ]);
    }
  } catch {
    all = null;
    page = null;
  }
  const pages = page ? Math.max(1, Math.ceil(page.total / PAGE)) : 1;
  const filtered = Boolean(q || field);
  const href = (n: number) => {
    const next = new URLSearchParams();
    if (q) next.set("q", q);
    if (field) next.set("field", field);
    if (n > 1) next.set("page", String(n));
    return `${base}${next.size ? `?${next}` : ""}`;
  };

  return (
    <main className="page">
      <Link className="crumb" href="/schools">学校库</Link>
      <div className="title-row">
        <div className="ident" style={{ gap: 16 }}>
          <SchoolMark logo={school.logo} name={name} />
          <div className="two-line">
            <h1>{name}</h1>
            <p className="lede" style={{ marginTop: 2 }}>{school.name_en}</p>
          </div>
        </div>
        {school.website && (
          <a className="btn btn-secondary" href={school.website.startsWith("http") ? school.website : `https://${school.website}`} target="_blank" rel="noreferrer">
            学校官网
          </a>
        )}
      </div>
      <div className="stagger">
        <section className="panel section" aria-label="学校概况">
          <div className="strip">
            <div><div className="label">QS 2027</div><div className="value num">{school.qs_rank ?? "未进入前 300"}</div></div>
            <div><div className="label">地区</div><div className="value">{school.region_zh ?? school.country}</div></div>
            <div><div className="label">城市</div><div className="value">{school.city ?? "未知"}</div></div>
            <div><div className="label">已收录项目</div><div className="value num">{all ? all.length : "未知"}</div></div>
          </div>
        </section>
        {!!school.alliances?.length && (
          <p className="section toolbar" style={{ marginTop: 16 }}>
            {school.alliances.map((a) => (
              <a key={a.name} className="pill pill-neutral" href={a.source} target="_blank" rel="noreferrer">{a.name}</a>
            ))}
          </p>
        )}
        <section className="panel section" aria-labelledby="programs-h">
          <div className="panel-head">
            <h2 id="programs-h">授课型硕士项目</h2>
            {page && <span className="muted num">{filtered ? `${page.total} / ${all?.length ?? "?"}` : page.total} 个</span>}
          </div>
          {!!all?.length && (
            <form className="panel-head" action={base} aria-label="筛选项目">
              <div className="toolbar" style={{ flex: 1 }}>
                <label className="sr-only" htmlFor="q">搜索项目</label>
                <input className="input" id="q" name="q" type="search" placeholder="项目名，例如 Data Science" defaultValue={q} style={{ maxWidth: 280 }} />
                <label className="sr-only" htmlFor="field">方向</label>
                <select className="select" id="field" name="field" defaultValue={field} style={{ width: 160 }}>
                  <option value="">全部方向</option>
                  {STUDY_AREAS.map((a) => (
                    <option key={a}>{a}</option>
                  ))}
                </select>
                <button className="btn btn-secondary" type="submit">筛选</button>
                {filtered && <Link className="btn btn-text" href={base}>清空</Link>}
              </div>
            </form>
          )}
          {page && all ? (
            <ProgramTable
              programs={page.programs}
              columns={programColumns(all, masterPrograms)}
              empty={filtered ? "没有符合条件的项目。换个关键词，或清空方向筛选。" : "这所学校的项目还没有收录。可以先到学校官网查看。"}
            />
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
      </div>
    </main>
  );
}
