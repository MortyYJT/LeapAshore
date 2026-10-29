"use server";

import { chineseInstitutions } from "@/lib/catalog-server";
import { institutionTier, searchInstitutions } from "@/lib/prototype-library";

export interface InstitutionHit {
  code: string;
  name: string;
  province: string;
  level: string;
  /** The Ministry list's 985 / 211 / 双一流 tags, as the list states them. */
  tags: string[];
  tier: "985" | "211" | "双非" | null;
}

/** Up to eight schools from the Ministry list whose names contain the query. */
export async function findInstitutions(query: string): Promise<InstitutionHit[]> {
  const q = query.trim().slice(0, 100);
  if (!q) return [];
  return searchInstitutions(chineseInstitutions, q)
    .slice(0, 8)
    .map((school) => {
      const tier = institutionTier(school);
      return {
        code: school.code,
        name: school.name,
        province: school.province,
        level: school.level,
        tags: (school.tags ?? []).map((t) => t.tag),
        tier: tier === "985" || tier === "211" ? tier : tier === "其他" ? "双非" : null,
      };
    });
}

/** The listed school with exactly this name, or null when the list does not hold it. */
export async function exactInstitution(name: string): Promise<InstitutionHit | null> {
  const hits = await findInstitutions(name);
  return hits.find((hit) => hit.name === name.trim()) ?? null;
}
