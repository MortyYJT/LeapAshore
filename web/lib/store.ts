// Local persistence for the state the server does not own: which stage the applicant is looking at,
// the chosen portfolio, the ticked material rows, and the avatar. The profile is not part of it —
// `web/lib/api.ts` reads and writes that against the backend, which is where it is authoritative.

import type { AppStage, PortfolioItem, Profile } from "./types";

const STORAGE_KEY = "offerpilot.state.v1";

export const EMPTY_PROFILE: Profile = {
  educationLevel: null,
  schoolOrigin: null,
  schoolName: "",
  domesticTier: null,
  overseasBand: null,
  major: "",
  gpaScore: null,
  gpaScale: 100,
  targetDegree: "授课型硕士",
  targetField: null,
  englishScore: "",
  annualBudgetCny: null,
  intake: "2027 S1",
};

export interface PersistedState {
  stage: AppStage;
  /**
   * The in-memory profile. It stays in this type because the running state holds it, but it is not
   * written to `localStorage`: see `saveState`.
   */
  profile: Profile;
  portfolio: PortfolioItem[];
  completedMaterials: string[];
  /** Downscaled data URL for the account avatar, or null to use the default glyph. */
  avatar: string | null;
}

export const initialState: PersistedState = {
  stage: "onboarding",
  profile: EMPTY_PROFILE,
  portfolio: [],
  completedMaterials: [],
  avatar: null,
};

export function loadState(): PersistedState {
  if (typeof window === "undefined") return initialState;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return initialState;
    const parsed = JSON.parse(raw) as Partial<PersistedState>;
    return {
      stage: parsed.stage ?? initialState.stage,
      // A fresh object rather than `EMPTY_PROFILE` itself, so no caller can mutate the constant.
      // `parsed.profile` is deliberately ignored: a copy written by an older build is a second
      // opinion about a profile the server owns, and it would be merged back in wherever the server
      // has no answer — the divergence `mergeServerProfile` is written to avoid.
      profile: { ...EMPTY_PROFILE },
      portfolio: parsed.portfolio ?? [],
      completedMaterials: parsed.completedMaterials ?? [],
      avatar: parsed.avatar ?? null,
    };
  } catch {
    return initialState;
  }
}

/**
 * Persist everything except the profile.
 *
 * The profile is server state. Writing it here as well meant the next load merged the surviving
 * local copy back over the server's answer wherever the server had none, so a value the applicant
 * had cleared or a save the server never took could reappear as if it were stored. `Onboarding`
 * already tells the applicant that answers which have not reached the server are lost on a refresh
 * ("这里的答案还没同步到服务器，刷新页面会丢失"), and keeping a copy here contradicted that.
 */
export function saveState(state: PersistedState): void {
  if (typeof window === "undefined") return;
  try {
    const { stage, portfolio, completedMaterials, avatar } = state;
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ stage, portfolio, completedMaterials, avatar }),
    );
  } catch {
    /* localStorage can be unavailable in private mode; ignore. */
  }
}

export function clearState(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(STORAGE_KEY);
}
