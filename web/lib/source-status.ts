// The served citation status as the union the domain type declares, in one place.
//
// Two adapters read this field — the program catalogue's and the material library's — and the
// direction of the fallback is the whole rule: a status this build has never heard of must be read as
// `待核验`, never as `已核验`, because `eligibility.ts` treats `已核验` as grounds to stop warning the
// applicant that a conclusion rests on unverified data. The backend has a third value, `失效`, which
// this build does not declare; it falls into the same unknown branch on purpose.
//
// It lives in its own module rather than in `programs-source.ts` because a second copy of it would be
// free to fall the other way, and the failure that follows — a dead page presented as a checked one —
// is invisible in review and only visible to the applicant being misled.

import type { SourceStatus } from "./types";

export function toSourceStatus(value: unknown): SourceStatus {
  return value === "已核验" ? "已核验" : "待核验";
}
