import Link from "next/link";

import { cricosFacts } from "@/lib/catalog";
import { masterPrograms } from "@/lib/catalog-server";
import { dataStatusLabel } from "@/lib/taxonomy";
import type { Program } from "@/lib/types";

const hasRequirements = (p: Program) => p.minimumMark !== null || p.englishRequirement !== null;

/** One page of catalogue programs as rows. Australian rows add their CRICOS weeks and tuition (design D3). */
export function ProgramTable({ programs, showSchool = true, empty }: { programs: Program[]; showSchool?: boolean; empty: React.ReactNode }) {
  return (
    <table className="stack">
      <thead>
        <tr>
          <th>项目</th>
          <th className="hide-phone">方向</th>
          <th className="num hide-phone">学制</th>
          <th className="num hide-phone">总学费</th>
          <th>录取要求</th>
        </tr>
      </thead>
      <tbody>
        {programs.length === 0 && (
          <tr>
            <td colSpan={5} className="wide">
              <div className="empty">{empty}</div>
            </td>
          </tr>
        )}
        {programs.map((p) => {
          const facts = cricosFacts(p.slug, masterPrograms);
          return (
            <tr key={p.slug}>
              <td className="wide">
                <div className="two-line">
                  <Link className="l1" href={`/programs/${encodeURIComponent(p.slug)}`}>
                    {p.name ?? "未知"}
                  </Link>
                  {showSchool && (
                    <div className="l2">
                      {p.university}
                      {p.country ? ` · ${p.country}` : ""}
                    </div>
                  )}
                </div>
              </td>
              <td className="muted hide-phone">{p.field ?? "未分类"}</td>
              <td className="num hide-phone">
                {facts?.weeks ? (
                  <>
                    {facts.weeks} <span className="muted">周</span>
                  </>
                ) : (
                  p.duration ?? <span className="muted">未收录</span>
                )}
              </td>
              <td className="num hide-phone">{facts?.tuition ? `A${facts.tuition.replace(".00", "")}` : <span className="muted">未收录</span>}</td>
              <td>
                {hasRequirements(p) ? <span className="pill pill-neutral">已收录 · {dataStatusLabel(p.dataStatus)}</span> : <span className="muted">未收录</span>}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
