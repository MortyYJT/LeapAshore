import type { Metadata } from "next";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { cricosFacts, missingRequirements, schoolSlugForUniversity } from "@/lib/catalog";
import { beijingToday, isClosed } from "@/lib/deadlines";
import { masterPrograms, overseasInstitutions } from "@/lib/catalog-server";
import { institutionSlug } from "@/lib/prototype-library";
import { serverProgramPage, serverUniversities } from "@/lib/server-api";
import { NOT_COLLECTED, verifiedMark } from "@/lib/taxonomy";
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

/** The host of an official page, shown beside its link so the applicant sees where it leads. */
function hostOf(url: string): string | null {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return null;
  }
}

/**
 * One program: its facts, its collected requirements with their source, and how it compares. Only the
 * requirements the program states get a row; the rest are named once on a 未收录 line.
 */
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
  const school = schoolSlug ? overseasInstitutions.find((s) => institutionSlug(s) === schoolSlug) ?? null : null;
  // A fact the catalogue does not hold is left out of the strip rather than shown as 未收录.
  const cells: [string, React.ReactNode][] =
    facts
      ? [
          ["CRICOS 代码", <span className="num" key="c">{facts.code}</span>],
          ["方向", program.field ?? "未分类"],
          ["细分", facts.narrow.replace(/^\d+ - /, "")],
          ["学制", facts.weeks ? <span key="w"><span className="num">{facts.weeks}</span> <span className="unit">周</span></span> : null],
          ["总学费", facts.tuition ? <span className="num" key="t">{`A${facts.tuition.replace(".00", "")}`}</span> : null],
        ]
      : [
          ["国家和地区", program.country ?? "未知"],
          ["方向", program.field ?? "未分类"],
          ["学位", program.degreeLevel ?? "未知"],
          ["学制", program.duration],
        ];
  const strip = cells.filter(([, value]) => value !== null);
  const missing = missingRequirements(program);
  const sourceHost = hostOf(program.source.url);
  // Rendered per request, so 已截止 is judged against today's Beijing date (requirement-dates D4).
  const today = beijingToday();
  const deadlines = [...program.deadlines].sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));

  return (
    <main className="page">
      <nav className="crumb" aria-label="位置">
        <Link href="/schools">学校库</Link>
        {schoolSlug && (
          <>
            <span aria-hidden="true"> › </span>
            <Link href={`/schools/${encodeURIComponent(schoolSlug)}`}>{school?.name_zh || school?.name_en || program.university}</Link>
          </>
        )}
      </nav>
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
              {verifiedMark(program.dataStatus) && <span className="pill pill-tier">{verifiedMark(program.dataStatus)}</span>}
            </div>
            <table className="req-table">
              <tbody>
                {program.minimumMark !== null && (
                  <tr><td>均分门槛（985 / 211）</td><td><span className="num">{program.minimumMark}</span> <span className="muted">/ 100</span></td></tr>
                )}
                {program.non211MinimumMark !== null && (
                  <tr><td>均分门槛（其他院校）</td><td><span className="num">{program.non211MinimumMark}</span> <span className="muted">/ 100</span></td></tr>
                )}
                {program.requiresCognate && <tr><td>相关专业背景</td><td>需要</td></tr>}
                {program.prerequisites.length > 0 && <tr><td>先修课</td><td>{program.prerequisites.join("；")}</td></tr>}
                {program.englishRequirement !== null && <tr><td>英语</td><td>{program.englishRequirement}</td></tr>}
                {program.academicRequirement !== null && (
                  <tr>
                    <td>学术要求</td>
                    <td>
                      <span lang="en">{program.academicRequirement}</span>
                      <div className="muted small">
                        英文摘要 ·{" "}
                        <a className="link" href={program.academicSourceUrl ?? program.source.url} target="_blank" rel="noreferrer">
                          看原文
                        </a>
                      </div>
                    </td>
                  </tr>
                )}
                {deadlines.length > 0 && (
                  <tr>
                    <td>申请截止</td>
                    <td>
                      <ul className="deadline-list">
                        {deadlines.map((d, i) => {
                          const closed = isClosed(d.date, today);
                          return (
                            <li key={`${d.date}-${i}`} data-state={closed ? "closed" : "upcoming"}>
                              {closed && <span className="pill pill-outline">已截止</span>}{" "}
                              <a className="num link" href={d.sourceUrl} target="_blank" rel="noreferrer">{d.date}</a>
                              {d.label && <span className="muted small" lang="en"> · {d.label}</span>}
                            </li>
                          );
                        })}
                      </ul>
                    </td>
                  </tr>
                )}
                {missing.length > 0 && (
                  <tr className="req-missing">
                    <td>{NOT_COLLECTED}</td>
                    <td className="muted">{missing.join("、")}</td>
                  </tr>
                )}
                <tr>
                  <td>来源</td>
                  <td>
                    <a className="link" href={program.source.url} target="_blank" rel="noreferrer">
                      {program.source.title}
                      <span aria-hidden="true"> ↗</span>
                    </a>
                    {sourceHost && <div className="muted small">{sourceHost}</div>}
                  </td>
                </tr>
              </tbody>
            </table>
          </section>
          <ProgramActions program={program} />
        </div>
      </div>
    </main>
  );
}
