import Link from "next/link";

import { cricosFacts, statesARequirement } from "@/lib/catalog";
import { masterPrograms } from "@/lib/catalog-server";
import { verifiedMark } from "@/lib/taxonomy";
import type { Program } from "@/lib/types";

const ALL_COLUMNS = { duration: true, tuition: true, requirements: true };

/**
 * One page of a school's programs as rows. Australian rows add their CRICOS weeks and tuition (design D3).
 * `columns` drops a column no program of the school fills (see `programColumns`).
 */
export function ProgramTable({
  programs,
  columns = ALL_COLUMNS,
  empty,
}: {
  programs: Program[];
  columns?: { duration: boolean; tuition: boolean; requirements: boolean };
  empty: React.ReactNode;
}) {
  const span = 2 + Number(columns.duration) + Number(columns.tuition) + Number(columns.requirements);
  return (
    <table className="stack program-table">
      <thead>
        <tr>
          <th>项目</th>
          <th className="hide-phone">方向</th>
          {columns.duration && <th className="num hide-phone">学制</th>}
          {columns.tuition && <th className="num hide-phone">总学费</th>}
          {columns.requirements && <th className="num">录取要求</th>}
        </tr>
      </thead>
      <tbody>
        {programs.length === 0 && (
          <tr>
            <td colSpan={span} className="wide">
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
                </div>
              </td>
              <td className="muted hide-phone">{p.field ?? "未分类"}</td>
              {columns.duration && (
                <td className="num hide-phone nowrap">
                  {facts?.weeks ? (
                    <>
                      {facts.weeks} <span className="muted">周</span>
                    </>
                  ) : (
                    p.duration ?? <span className="muted">未收录</span>
                  )}
                </td>
              )}
              {columns.tuition && (
                <td className="num hide-phone nowrap">{facts?.tuition ? `A${facts.tuition.replace(".00", "")}` : <span className="muted">未收录</span>}</td>
              )}
              {columns.requirements && (
                <td className="num nowrap">
                  {statesARequirement(p) ? <span className="pill pill-neutral">{verifiedMark(p.dataStatus) ? `已收录 · ${verifiedMark(p.dataStatus)}` : "已收录"}</span> : <span className="muted">未收录</span>}
                </td>
              )}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
