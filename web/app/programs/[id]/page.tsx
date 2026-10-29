import type { Metadata } from "next";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { SourceNote } from "@/components/ui";
import { cricosFacts, schoolSlugForUniversity } from "@/lib/catalog";
import { masterPrograms, overseasInstitutions } from "@/lib/catalog-server";
import { serverProgramPage, serverUniversities } from "@/lib/server-api";
import { dataStatusLabel, DATA_STATUS_MEANINGS, NOT_COLLECTED } from "@/lib/taxonomy";
import type { Program } from "@/lib/types";

import { ProgramActions } from "./ProgramActions";

export const dynamic = "force-dynamic";

async function programFor(id: string): Promise<Program | null> {
  const { programs } = await serverProgramPage({ ids: [id], limit: 1 });
  return programs[0] ?? null;
}

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  try {
    const program = await programFor(decodeURIComponent((await params).id));
    return { title: `${program?.name ?? "项目"} · 鱼跃彼岸` };
  } catch {
    return { title: "项目 · 鱼跃彼岸" };
  }
}

const missing = <span className="muted">{NOT_COLLECTED}</span>;

/** One program: its facts, its collected requirements with their source, and how it compares. */
export default async function ProgramPage({ params }: { params: Promise<{ id: string }> }) {
  const id = decodeURIComponent((await params).id);
  // A bare CRICOS course code (the spec's own example is /programs/0100139) is that course's row.
  if (masterPrograms.some((c) => c.code === id)) redirect(`/programs/cricos-${encodeURIComponent(id)}`);
  const program = await programFor(id).catch(() => null);
  if (!program) notFound();

  const facts = cricosFacts(program.slug, masterPrograms);
  const schoolSlug = program.universityId
    ? await serverUniversities()
        .then((rows) => schoolSlugForUniversity(program.universityId!, rows, overseasInstitutions))
        .catch(() => null)
    : null;
  const strip: [string, React.ReactNode][] = facts
    ? [
        ["CRICOS 代码", <span className="num" key="c">{facts.code}</span>],
        ["方向", program.field ?? "未分类"],
        ["细分", facts.narrow.replace(/^\d+ - /, "")],
        ["学制", <span key="w"><span className="num">{facts.weeks ?? "—"}</span> <span className="unit">周</span></span>],
        ["总学费", <span className="num" key="t">{facts.tuition ? `A${facts.tuition.replace(".00", "")}` : NOT_COLLECTED}</span>],
      ]
    : [
        ["国家和地区", program.country ?? "未知"],
        ["方向", program.field ?? "未分类"],
        ["学位", program.degreeLevel ?? "未知"],
        ["学制", program.duration ?? NOT_COLLECTED],
      ];
  // The rule of `has_requirement_data` in api/app/models/program.py, so this page and the catalogue counts agree.
  const stated = program.minimumMark !== null || program.non211MinimumMark !== null || program.englishRequirement !== null || program.prerequisites.length > 0;

  return (
    <>
      <main className="page">
        <Link className="crumb" href="/programs">项目库</Link>
        <div className="title-row">
          <div style={{ minWidth: 0 }}>
            <h1>{program.name ?? "未知"}</h1>
            <p className="lede">
              {schoolSlug ? <Link href={`/schools/${encodeURIComponent(schoolSlug)}`}>{program.university}</Link> : program.university}
              {facts ? ` · ${facts.institution}` : ""}
            </p>
          </div>
        </div>
        <div className="stagger">
          <section className="panel section" aria-label="项目事实">
            <div className="strip">
              {strip.map(([label, value]) => (
                <div key={label}>
                  <div className="label">{label}</div>
                  <div className="value">{value}</div>
                </div>
              ))}
            </div>
          </section>
          <div className="grid grid-8-4 section">
            <section className="panel" aria-labelledby="req-h">
              <div className="panel-head">
                <h2 id="req-h">录取要求</h2>
                {stated && <span className="pill pill-neutral" title={DATA_STATUS_MEANINGS[program.dataStatus]}>{dataStatusLabel(program.dataStatus)}</span>}
              </div>
              <table className="req-table">
                <tbody>
                  <tr><td>均分门槛（985 / 211）</td><td>{program.minimumMark !== null ? <><span className="num">{program.minimumMark}</span> <span className="muted">/ 100</span></> : missing}</td></tr>
                  <tr><td>均分门槛（其他院校）</td><td>{program.non211MinimumMark !== null ? <><span className="num">{program.non211MinimumMark}</span> <span className="muted">/ 100</span></> : missing}</td></tr>
                  <tr><td>相关专业背景</td><td>{program.requiresCognate ? "需要" : missing}</td></tr>
                  <tr><td>先修课</td><td>{program.prerequisites.length ? program.prerequisites.join("；") : missing}</td></tr>
                  <tr><td>英语</td><td>{program.englishRequirement ?? missing}</td></tr>
                  <tr>
                    <td>来源</td>
                    <td>
                      <a href={program.source.url} target="_blank" rel="noreferrer">{program.source.title}</a>
                      <div className="muted small">{DATA_STATUS_MEANINGS[program.source.status]}</div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </section>
            <ProgramActions program={program} />
          </div>
        </div>
      </main>
      <SourceNote>
        {facts ? "课程事实来自 CRICOS（澳大利亚教育部，CC BY 2.5 AU）。" : ""}录取要求摘自该校官网页面，尚未经人工核对，申请前请以官网为准。没有收录的要求显示为未收录，系统不会代填。
      </SourceNote>
    </>
  );
}
