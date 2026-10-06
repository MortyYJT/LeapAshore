// The profile API. The server is the source of truth for the applicant's background; localStorage
// keeps only what has not moved to the backend yet (see `store.ts`).
//
// Requests go to a same-origin `/api` path that `next.config.ts` rewrites to the backend, so the
// httpOnly `offerpilot_client` cookie rides along on its own and no CORS setup is needed.

import type { Profile } from "./types";
import type { ServedRoadmapDefinition } from "./roadmap-source";

/**
 * Read the roadmap definition: which phases exist and what each one asks for.
 *
 * This is shared configuration, not applicant data. The route takes no subject and is served without
 * a cookie, so the response is the same for everyone and reading it has no side effect. What the
 * server does *not* send is any date: the phases carry an offset in days and the client derives the
 * dates from the intake term, which is the split this task keeps on purpose.
 *
 * The body is returned as the wire shape rather than mapped. Mapping it is `roadmap-source.ts`'s job
 * and is a pure function with its own tests, so a body that passes through here unexamined can be
 * checked without a server. A failure raises rather than resolving to an empty definition, because
 * "the server said nothing" and "the server could not be reached" are different claims and only the
 * caller knows which fallback to use.
 */
export async function fetchRoadmapDefinition(): Promise<ServedRoadmapDefinition> {
  const response = await fetch("/api/roadmap", { credentials: "same-origin" });
  if (!response.ok) throw new Error(`读取路线图定义失败：${response.status}`);
  return response.json();
}

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
 * Decimal places the numeric profile columns hold, read from `api/app/models/client.py`.
 *
 * `gpa_score` and `gpa_scale` are `Numeric(5, 2)` and `annual_budget_cny` is `Numeric(12, 2)`, so
 * the database keeps two decimal places and rounds anything finer. That is reachable from the UI
 * today: the GPA input is a number field, and a GPA on the 4.0/4.3/5.0/7.0 scales carries three
 * decimals (`3.756`). The budget's two inputs are fixed option lists, so only a whole option value
 * reaches the column from there, but the rule is the column's rather than the control's: a field
 * this map does not name is compared exactly.
 */
const COLUMN_DECIMALS: Partial<Record<keyof Profile, number>> = {
  gpaScore: 2,
  gpaScale: 2,
  annualBudgetCny: 2,
};

/**
 * Round `value` to `places` decimals the way the database column does: half away from zero, applied
 * to the number's shortest decimal spelling.
 *
 * Measured through the running server: `{"gpaScore": 85.375}` comes back as `85.38`, and
 * `{"annualBudgetCny": 250000.505}` comes back as `250000.51`. Rounding the spelling `String()`
 * produces — which is the same shortest spelling Postgres reads out of the double — reproduces both,
 * including those ties, which are exactly the inputs an applicant can type.
 *
 * Scaling by `10 ** places` instead is not equivalent, and fails on the same class of input:
 * `4.675 * 100` is `467.49999999999994`, which would round down to `4.67` where the column holds
 * `4.68`. That is why the digits are rounded as digits.
 */
function roundToColumnPrecision(value: number, places: number): number {
  if (!Number.isFinite(value)) return value;
  const text = String(value);
  // Exponent notation means |value| is below 1e-6 or at least 1e21: outside what these columns can
  // hold, and not a shape any of the inputs produces. Left alone rather than guessed at.
  if (text.includes("e")) return value;
  const negative = text.startsWith("-");
  const [whole, fraction = ""] = (negative ? text.slice(1) : text).split(".");
  const digits = whole + fraction;
  const keep = whole.length + places;
  if (keep >= digits.length) return value; // already no finer than the column
  let kept = digits.slice(0, keep);
  if (digits.charCodeAt(keep) - 48 >= 5) kept = (BigInt(kept) + 1n).toString();
  // Dividing by `10 ** places` stays right when the carry added a digit: 9.999 keeps "999", rounds
  // up to "1000", and 1000 / 100 is still 10.
  const scaled = Number(kept) / 10 ** places;
  return negative ? -scaled : scaled;
}

/** Whether the value in the reply is the value that was sent, to the precision its column keeps. */
function isStoredAsSent(key: keyof Profile, sent: unknown, saved: unknown): boolean {
  const places = COLUMN_DECIMALS[key];
  if (places === undefined || typeof sent !== "number" || typeof saved !== "number") {
    return saved === sent;
  }
  return roundToColumnPrecision(sent, places) === roundToColumnPrecision(saved, places);
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
 *
 * A numeric field is compared at the precision its column keeps, not by `!==`. Comparing the raw
 * numbers called the database's own rounding a failed save: `85.375` came back as `85.38`, so the
 * caller refused to advance on a save that had landed, and the inline edit path rolled the field
 * back to a value the server disagreed with — the silent divergence this check exists to prevent.
 * The comparison is still exact for everything the column cannot explain, so a field the server
 * kept at its old value, or changed to anything else, still raises.
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
    .filter(
      ([key, value]) =>
        !isStoredAsSent(key as keyof Profile, value, saved[key as keyof Profile]),
    )
    .map(([key]) => key);
  if (diverged.length > 0) {
    throw new Error(`保存档案失败：服务器没有按提交的值保存（${diverged.join("、")}）`);
  }
  return saved;
}

/**
 * True when the server has never been told this field.
 *
 * Only `null` and `undefined` count. An empty string is an answer: `ProfileView` sends it when the
 * applicant clears a field, and the server stores what it was sent, so reading it as "no answer"
 * was how a cleared field came back on the next load while the server held the cleared one — the
 * same silent divergence the write-path check in `patchProfile` exists to prevent. A whitespace-only
 * string is an answer for the same reason; nothing in the UI produces one, and singling it out would
 * reintroduce the resurrection for the one value that most looks like a deliberate blank.
 */
function isAbsent(value: unknown): boolean {
  return value === null || value === undefined;
}

/**
 * Merge the server's profile under the local one, letting the server win wherever it has an answer.
 *
 * The server is authoritative for the profile, so every value it holds for a field wins — including
 * `""`, which is what clearing a saved field leaves behind. What it does not hold is `null`, and
 * that means "this account never told us", not "the applicant has no school": the row a subject
 * starts on is all nulls, so a blind overwrite would wipe the answers given on this device before
 * the first save landed. Only those fields fall back to the local copy, which is the frontend's
 * defaults (`EMPTY_PROFILE`) plus any answer the server has not been told yet.
 *
 * The consequence to remember: a value on screen is therefore not proof that the server holds it.
 * That is what `patchProfile` reports on the write path, and why a field the applicant cleared is
 * an empty win rather than a fallback.
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
