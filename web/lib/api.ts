// The profile API. The server is the source of truth for the applicant's background; localStorage
// keeps only what has not moved to the backend yet (see `store.ts`).
//
// Requests go to a same-origin `/api` path that `next.config.ts` rewrites to the backend, so the
// httpOnly `offerpilot_client` cookie rides along on its own and no CORS setup is needed.

import type { Profile } from "./types";

/**
 * Read the caller's profile.
 *
 * The response keys already match `Profile`: the API serialises camelCase and its two database-named
 * columns are aliased to `educationLevel` and `targetDegree`. So the body is handed back as a
 * partial `Profile` rather than mapped, and `EMPTY_PROFILE` fills in whatever is absent.
 */
export async function fetchProfile(): Promise<Partial<Profile>> {
  const response = await fetch("/api/profile", { credentials: "same-origin" });
  if (!response.ok) throw new Error(`读取档案失败：${response.status}`);
  return response.json();
}

/**
 * Save the fields in `patch` and return the profile as the server now holds it.
 *
 * `PATCH` applies only the keys present in the body, so a one-field edit cannot blank the rest, and
 * the server rejects unknown keys with 422. Parse the returned body even though the caller may
 * ignore it: its keys are the ones the server actually accepted, which is what makes a silent
 * divergence visible instead of assumed.
 */
export async function patchProfile(patch: Partial<Profile>): Promise<Partial<Profile>> {
  const response = await fetch("/api/profile", {
    method: "PATCH",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!response.ok) throw new Error(`保存档案失败：${response.status}`);
  return response.json();
}

/** True when an incoming value would replace a locally known one with nothing. */
function isAbsent(value: unknown): boolean {
  return value === null || value === undefined || (typeof value === "string" && value.trim() === "");
}

/**
 * Merge the server's profile under the local one, letting the server win wherever it has a value.
 *
 * The server is authoritative, but it starts every subject on a row of all-null columns, and a
 * null there means "this account never told us", not "the applicant has no school". A blind
 * overwrite would let that empty first-contact row wipe the answers the applicant just gave on this
 * device, so a field the server does not have falls back to the local value. The consequence to
 * remember: a null on the server cannot be used to clear a field that still has a local value. The
 * one place that matters is clearing the detected tier, and its local fallback is empty by then.
 */
export function mergeServerProfile(remote: Partial<Profile>, local: Profile): Profile {
  const merged: Record<string, unknown> = { ...local };
  for (const [key, value] of Object.entries(remote)) {
    // The key comes from the server's own body, so it is narrowed to a known field name by the cast
    // on the way in; an unknown key is rejected by the API before it can reach this map.
    if (!isAbsent(value)) merged[key] = value;
  }
  return merged as unknown as Profile;
}
