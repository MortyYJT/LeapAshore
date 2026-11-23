// The resources kept for the visit (lib/resource-cache.ts), by the key each is kept under. A write
// names the keys it makes out of date; they are listed here so the reads and the writes agree.

/** The applicant's background. Written by the profile form and by the advisor. */
export const PROFILE_KEY = "profile";
/** The uploaded files. Written by uploads, new versions, archiving and sending for review. */
export const MATERIALS_KEY = "documents";
/** The saved portfolio. Written by its confirm and by the advisor. */
export const PORTFOLIO_KEY = "portfolio";
/** The roadmap's served definition and the applicant's task rows. Ticks are merged in place (useRoadmap). */
export const ROADMAP_KEY = "roadmap";
/** Catalogue reads the pages repeat: the tiers' programs by field, and programs by slug. */
export const TIER_PROGRAMS_PREFIX = "tier-programs:";
export const TIER_PROGRAMS_KEY = (field: string) => `${TIER_PROGRAMS_PREFIX}${field}`;
export const PROGRAMS_BY_SLUG_KEY = "programs-by-slug";
/** The admin's lists. */
export const ADMIN_PAGES_PREFIX = "admin-pages:";
export const ADMIN_PAGES_KEY = (query: string) => `${ADMIN_PAGES_PREFIX}${query}`;
export const ADMIN_GAPS_KEY = "admin-gaps";
