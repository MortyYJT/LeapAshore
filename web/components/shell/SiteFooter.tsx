import Link from "next/link";

import { overseasInstitutions } from "@/lib/catalog-server";

const CC_LICENSE = /^CC (BY(?:-SA)?) (\d\.\d)$/;

/** A Creative Commons licence name as a link to its deed, e.g. CC BY-SA 4.0. */
function licenseUrl(license: string): string | null {
  const match = CC_LICENSE.exec(license);
  return match ? `https://creativecommons.org/licenses/${match[1].toLowerCase()}/${match[2]}/` : null;
}

/**
 * The one line every page ends with: the caveat on requirements and the attributions the data's licences
 * require (CRICOS under CC BY 2.5 AU, the QS ranking, and each school logo used under a CC BY or CC BY-SA
 * licence, read from the library file so a new one is credited without editing this component).
 */
export function SiteFooter() {
  const credited = overseasInstitutions.filter((s) => s.logo && s.logo_source && s.logo_license && licenseUrl(s.logo_license));
  return (
    <p>
      录取要求摘自各校官网，申请前请以官网为准。排名：QS World University Rankings 2027。澳洲课程数据：
      <a href="https://data.gov.au/data/dataset/cricos" target="_blank" rel="noreferrer">CRICOS</a>（澳大利亚教育部，
      <a href="https://creativecommons.org/licenses/by/2.5/au/" target="_blank" rel="noreferrer">CC BY 2.5 AU</a>）。校徽归各校所有，仅作识别
      {credited.length > 0 && (
        <>
          ；
          {credited.map((s, i) => (
            <span key={s.logo}>
              {i > 0 && "、"}
              <a href={s.logo_source} target="_blank" rel="noreferrer">{s.name_zh || s.name_en}</a>（
              <a href={licenseUrl(s.logo_license!)!} target="_blank" rel="noreferrer">{s.logo_license}</a>）
            </span>
          ))}
          的校徽来自 Wikimedia Commons
        </>
      )}
      。<Link href="/privacy">隐私政策</Link>
    </p>
  );
}
