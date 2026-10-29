"use client";

import { fetchProfile } from "../api";
import { EMPTY_PROFILE } from "../assess";
import type { Profile } from "../types";
import { useResource } from "./useResource";

/** The server profile, with every field the server has never been told left empty. */
export async function loadProfile(): Promise<Profile> {
  const remote = await fetchProfile();
  const merged: Profile = { ...EMPTY_PROFILE };
  for (const key of Object.keys(EMPTY_PROFILE) as (keyof Profile)[]) {
    const value = remote[key];
    if (value !== undefined && value !== null) (merged as unknown as Record<string, unknown>)[key] = value;
  }
  return merged;
}

export function useProfile() {
  return useResource(loadProfile);
}
