import type { Metadata } from "next";
import Link from "next/link";

import { SchoolFilters } from "./SchoolFilters";

import { ProgramTable } from "@/components/catalog/ProgramTable";
import { SchoolMark } from "@/components/ui";
import { programsAcrossSchools, universityIdsFor, type UniversityRow } from "@/lib/catalog";
import { overseasInstitutions } from "@/lib/catalog-server";
import {
  filterSchools,
  institutionSlug,
  paginate,
  paginateSchools,
  schoolListHref,
  schoolQsRanges,
  schoolQuery,
  schoolRegions,
  sortSchools,
} from "@/lib/prototype-library";
import { serverProgramPage, serverUniversities } from "@/lib/server-api";
import type { Program } from "@/lib/types";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "学校库 · 鱼跃彼岸" };

async function universities(): Promise<UniversityRow[] | null> {
  try {
    return await serverUniversities();
  } catch {
    return null;
  }
}

/** Program matches listed per page under the schools. */
const PROGRAM_PAGE = 20;
/** At most this many pages of 100 are read for one search; a word that matches more is too broad to list whole. */
const PROGRAM_READS = 10;

type School = (typeof overseasInstitutions)[number];

/**
 * The programs whose name holds the search, at the schools the list's other filters keep, in the list's
 * order. Null when there is nothing to search for (fewer than two characters) or the catalogue could
 * not be read; `capped` when more programs matched than were read.
 */
async function programSearch(q: string | undefined, scope: School[], rows: UniversityRow[] | null): Promise<{ hits: { program: Program; school: School }[]; capped: boolean } | null> {
  const term = q?.trim() ?? "";
  if (term.length < 2 || !rows) return null;
  try {
    const first = await serverProgramPage({ q: term, limit: 100, offset: 0 });
    const reads = Math.min(Math.ceil(first.total / 100), PROGRAM_READS);
    const rest = await Promise.all(Array.from({ length: Math.max(0, reads - 1) }, (_, i) => serverProgramPage({ q: term, limit: 100, offset: (i + 1) * 100 })));
    const programs = [...first.programs, ...rest.flatMap((page) => page.programs)];
    return { hits: programsAcrossSchools(programs, term, scope, rows), capped: first.total > reads * 100 };
  } catch {
    return null;
  }
}

/**
 * The school library: 287 schools, filterable by name, region and QS band, with collected program counts.
 * A search also lists the programs whose name holds it, each with 加入申请, so an applicant who searches
 * for a subject rather than a school adds a program from the list in one press.
 */
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
  // The schools the region and QS filters keep, whatever the search says: a program match is at one of them.
  const scope = sortSchools(filterSchools(overseasInstitutions, { ...query, q: undefined }));
  const found = await programSearch(query.q, scope, rows);
  const matches = found ? paginate(found.hits, query.pp, PROGRAM_PAGE) : null;
  // With programs found and no school named so, the empty school table is left out.
  const showSchools = list.length > 0 || !matches?.total;

  return (
    <main className="page">
      <div className="title-row">
        <div>
          <h1>学校库</h1>
          <p className="lede">
            29 个国家和地区里的 QS 2027 前 300，加上澳洲、香港、澳门的其他大学，共 <strong className="num">{overseasInstitutions.length}</strong> 所，按 QS 名次排列。
          </p>
        </div>
      </div>
      <SchoolFilters
        count={list.length}
        programs={matches?.total ?? null}
        controls={
          <>
            <label className="sr-only" htmlFor="q">搜索学校或项目</label>
            <input className="input" id="q" key={`q:${query.q ?? ""}`} name="q" type="search" placeholder="校名或项目名，例如 Data Science" defaultValue={query.q ?? ""} style={{ maxWidth: 280 }} />
            <label className="sr-only" htmlFor="region">地区</label>
            <select className="select" id="region" key={`region:${query.region ?? ""}`} name="region" defaultValue={query.region ?? ""} style={{ width: 140 }}>
              <option value="">全部地区</option>
              {schoolRegions.map((r) => (
                <option key={r}>{r}</option>
              ))}
            </select>
            <label className="sr-only" htmlFor="qs">QS 名次</label>
            <select className="select" id="qs" key={`qs:${query.qs ?? ""}`} name="qs" defaultValue={[...qs][0] ?? ""} style={{ width: 150 }}>
              <option value="">QS 名次不限</option>
              {schoolQsRanges.map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
            {(query.q || query.region || query.qs) && (
              <Link className="btn btn-text" href="/schools">
                清空
              </Link>
            )}
          </>
        }
      >
        {showSchools && (
        <>
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
                  <div className="empty">没有符合条件的学校{found ? "或项目" : ""}。换个关键词，或清空地区和名次筛选。</div>
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
                        <Link className="l1" href={`/schools/${encodeURIComponent(institutionSlug(s))}`} prefetch={false}>
                          {name}
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
        </>
        )}
        {!found && (query.q?.trim().length ?? 0) >= 2 && (
          <p className="panel-pad muted small program-hits-failed">项目这次没有读到，上面只按校名找了。可以稍后再搜一次。</p>
        )}
        {matches && matches.total > 0 && (
          <section className={`program-hits${showSchools ? " after-schools" : ""}`} aria-labelledby="program-hits-h">
            <div className="panel-head">
              <h2 id="program-hits-h">项目名里有「{query.q}」</h2>
              <span className="muted num">{matches.total} 个</span>
            </div>
            {found?.capped && (
              <p className="panel-pad muted small" style={{ margin: 0 }}>
                匹配的项目太多，这里只列出读到的前 {PROGRAM_READS * 100} 个里的。换个更具体的词能列全。
              </p>
            )}
            <ProgramTable
              programs={matches.items.map((hit) => hit.program)}
              columns={{ duration: false, tuition: false, requirements: true }}
              schoolOf={(program) => {
                const school = matches.items.find((hit) => hit.program.slug === program.slug)?.school;
                return school ? { name: school.name_zh || school.name_en || "未知", href: `/schools/${encodeURIComponent(institutionSlug(school))}` } : null;
              }}
              empty={null}
            />
            {matches.pages > 1 && (
              <div className="pager">
                <span className="muted num">
                  第 {matches.page} / {matches.pages} 页
                </span>
                <span className="toolbar">
                  {matches.page > 1 && <Link className="btn btn-secondary btn-small" href={schoolListHref(query, { page: query.page, pp: String(matches.page - 1) })} scroll={false}>上一页</Link>}
                  {matches.page < matches.pages && <Link className="btn btn-secondary btn-small" href={schoolListHref(query, { page: query.page, pp: String(matches.page + 1) })} scroll={false}>下一页</Link>}
                </span>
              </div>
            )}
          </section>
        )}
      </SchoolFilters>
    </main>
  );
}
