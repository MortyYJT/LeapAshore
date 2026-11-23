"use client";

import { fetchProfile } from "../api";
import { EMPTY_PROFILE } from "../assess";
import type { Profile } from "../types";
import { PROFILE_KEY } from "../resource-keys";
import { useResource } from "./useResource";

/** A served profile with every field the server has never been told left empty, and its version. */
export function toProfile(remote: Partial<Profile>): Profile {
  const merged: Profile = { ...EMPTY_PROFILE };
  for (const key of Object.keys(EMPTY_PROFILE) as (keyof Profile)[]) {
    const value = remote[key];
    if (value !== undefined && value !== null) (merged as unknown as Record<string, unknown>)[key] = value;
  }
  if (typeof remote.version === "number") merged.version = remote.version;
  return merged;
}

export async function loadProfile(): Promise<Profile> {
  return toProfile(await fetchProfile());
}

export function useProfile() {
  return useResource(loadProfile, PROFILE_KEY);
}
