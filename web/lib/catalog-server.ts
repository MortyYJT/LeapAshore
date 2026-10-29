import "server-only";

// The library's own files, read on the Next server (design D3): the 346 schools, the CRICOS course facts
// the `programs` table has no columns for, and the Ministry list of mainland institutions. Renamed from
// `prototype-library-server.ts` with the prototype routes gone.

import cn from "../prototype-fixtures/cn-institutions.json";
import masters from "../prototype-fixtures/cricos-au-masters.json";
import overseas from "../prototype-fixtures/overseas-institutions.json";
import type { ChineseInstitution, MasterProgram, OverseasInstitution } from "./prototype-library";

export const chineseInstitutions: ChineseInstitution[] = cn.institutions;
export const overseasInstitutions: OverseasInstitution[] = overseas.institutions;
export const masterPrograms: MasterProgram[] = masters.courses;

export const SOURCES = {
  ministry: { title: cn.source, url: cn.source_url, retrievedAt: cn.retrieved_at },
  cricos: { title: masters.source, retrievedAt: masters.retrieved_at, url: "https://data.gov.au/data/dataset/cricos" },
  qs: { retrievedAt: overseas.retrieved_at },
};
