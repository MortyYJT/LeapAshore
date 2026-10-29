// Where `/` sends a visitor (spec app-navigation; design D2). The decision comes from the server's
// profile, never from a cookie or browser storage alone, so clearing storage does not lose the return.

import { EMPTY_PROFILE, hasBasics } from "./assess.ts";
import type { Profile } from "./types.ts";

export const LANDING_TIMEOUT_MS = 1000;

/**
 * `/roadmap` for a visitor whose server profile holds the four basics, otherwise null (render the
 * introduction). An API that fails or is slower than the timeout is treated as "no profile".
 */
export async function landingFor(
  readProfile: () => Promise<Record<string, unknown>>,
  timeoutMs = LANDING_TIMEOUT_MS,
): Promise<"/roadmap" | null> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<null>((resolve) => {
    timer = setTimeout(() => resolve(null), timeoutMs);
  });
  try {
    const remote = await Promise.race([readProfile(), timeout]);
    if (!remote) return null;
    const profile = { ...EMPTY_PROFILE } as Profile;
    for (const key of Object.keys(EMPTY_PROFILE) as (keyof Profile)[]) {
      const value = remote[key];
      if (value !== undefined && value !== null) (profile as unknown as Record<string, unknown>)[key] = value;
    }
    return hasBasics(profile) ? "/roadmap" : null;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}
