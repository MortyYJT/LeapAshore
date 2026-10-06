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
 * the server rejects unknown keys with 422. The response body is parsed and checked rather than
 * ignored: it is the server's own account of what it now holds, so a reply whose value for a field
 * just sent differs from that field is a save that did not land. Raising here turns that into an
 * error the caller already knows how to report, instead of the local state quietly keeping a value
 * the server never stored. Only the sent fields are checked; the response carries the whole profile,
 * and the rest of it is not this call's business.
 */
export async function patchProfile(patch: Partial<Profile>): Promise<Partial<Profile>> {
  const response = await fetch("/api/profile", {
    method: "PATCH",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!response.ok) throw new Error(`保存档案失败：${response.status}`);
  const saved = (await response.json()) as Partial<Profile>;
  // Only the keys this call actually sent are compared. `JSON.stringify` drops a key whose value is
  // `undefined`, so such a key never reached the server and its absence from the reply says nothing
  // about whether the save landed.
  const sent = Object.entries(patch).filter(([, value]) => value !== undefined);
  const diverged = sent
    .filter(([key, value]) => saved[key as keyof Profile] !== value)
    .map(([key]) => key);
  if (diverged.length > 0) {
    throw new Error(`保存档案失败：服务器没有按提交的值保存（${diverged.join("、")}）`);
  }
  return saved;
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
