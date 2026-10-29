import type { Metadata } from "next";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { ProgramTable } from "@/components/catalog/ProgramTable";
import { SchoolMark, SourceNote } from "@/components/ui";
import { universityIdsFor } from "@/lib/catalog";
import { overseasInstitutions } from "@/lib/catalog-server";
import { institutionSlug } from "@/lib/prototype-library";
import { serverProgramPage, serverUniversities } from "@/lib/server-api";

export const dynamic = "force-dynamic";
const PAGE = 30;

function schoolFor(slug: string) {
  return overseasInstitutions.find((s) => institutionSlug(s) === slug) ?? null;
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const school = schoolFor(decodeURIComponent((await params).slug));
  return { title: `${school?.name_zh ?? school?.name_en ?? "学校"} · 鱼跃彼岸` };
}

/** One school and the programs the catalogue holds for it. */
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
  const pageNo = Math.max(1, Number((await searchParams).page) || 1);
  const name = school.name_zh || school.name_en || "未知";

  let ids: string[] = [];
  let page: { programs: Awaited<ReturnType<typeof serverProgramPage>>["programs"]; total: number } | null = null;
  let failed = false;
  try {
    ids = universityIdsFor(school, await serverUniversities());
    page = ids.length ? await serverProgramPage({ provider: ids, limit: PAGE, offset: (pageNo - 1) * PAGE }) : { programs: [], total: 0 };
  } catch {
    failed = true;
  }
  const pages = page ? Math.max(1, Math.ceil(page.total / PAGE)) : 1;

  return (
    <>
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
              <div><div className="label">已收录项目</div><div className="value num">{page ? page.total : "未知"}</div></div>
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
              {page && <span className="muted num">{page.total} 个</span>}
            </div>
            {failed ? (
              <div className="panel-pad"><div className="empty">项目读取失败，请稍后再试。</div></div>
            ) : (
              <ProgramTable programs={page?.programs ?? []} showSchool={false} empty="这所学校的项目还没有收录。可以先到学校官网查看。" />
            )}
            {page && pages > 1 && (
              <div className="pager">
                <span className="muted num">第 {pageNo} / {pages} 页</span>
                <span className="toolbar">
                  {pageNo > 1 && <Link className="btn btn-secondary btn-small" href={`?page=${pageNo - 1}`}>上一页</Link>}
                  {pageNo < pages && <Link className="btn btn-secondary btn-small" href={`?page=${pageNo + 1}`}>下一页</Link>}
                </span>
              </div>
            )}
          </section>
        </div>
      </main>
      <SourceNote>
        学校信息：QS World University Rankings 2027 及各国官方名单。项目来自 CRICOS 登记或学校官网，录取要求“自动标注”表示程序已对照官网原文核对，“未核对”表示还没核对，均未经人工核对。
      </SourceNote>
    </>
  );
}
