// Local persistence. During the MVP stage state lives in the browser so progress survives a reload.
// Once the backend exists this file becomes FastAPI calls; components stay unchanged.

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
  profile: Profile;
  portfolio: PortfolioItem[];
  completedMaterials: string[];
}

export const initialState: PersistedState = {
  stage: "onboarding",
  profile: EMPTY_PROFILE,
  portfolio: [],
  completedMaterials: [],
};

export function loadState(): PersistedState {
  if (typeof window === "undefined") return initialState;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return initialState;
    const parsed = JSON.parse(raw) as Partial<PersistedState>;
    return {
      stage: parsed.stage ?? initialState.stage,
      profile: { ...EMPTY_PROFILE, ...(parsed.profile ?? {}) },
      portfolio: parsed.portfolio ?? [],
      completedMaterials: parsed.completedMaterials ?? [],
    };
  } catch {
    return initialState;
  }
}

export function saveState(state: PersistedState): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    /* localStorage can be unavailable in private mode; ignore. */
  }
}

export function clearState(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(STORAGE_KEY);
}
