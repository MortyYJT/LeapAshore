// The profile API. The server is the source of truth for the applicant's background; localStorage
// keeps only what has not moved to the backend yet (see `store.ts`).
//
// Requests go to a same-origin `/api` path that `next.config.ts` rewrites to the backend, so the
// httpOnly `offerpilot_client` cookie rides along on its own and no CORS setup is needed.

import type { Profile } from "./types";
import type { TaskReplacePayload, TaskReplaceResult } from "./roadmap-sync";
import type {
  ServedMaterial,
  ServedPhase,
  ServedRoadmapDefinition,
  ServedTask,
} from "./roadmap-source";

/** Whether the value the wire sent is a string with at least one character in it. */
function isFilled(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

/**
 * The offset magnitude past which the client's own date arithmetic cannot produce a date at all.
 *
 * `buildRoadmap` derives a phase's suggested date as `anchor - offsetDays * 86_400_000` and calls
 * `toISOString` on it. A `Date` spans ±8.64e15 ms, which is 1e8 days, so a phase whose offset leaves
 * that window makes the builder throw `RangeError: Invalid time value` from inside its `.map` — a
 * failure during render, where the read's `catch` cannot reach it. The largest offset the definition
 * uses is 330, and the column is a Postgres `INTEGER` (up to 2147483647) with no CHECK, so a value
 * in that window is reachable by editing a row, which is exactly what this design invites. Measured
 * in a browser against the stub `offsetDays: 1000000000`: the Next Runtime RangeError overlay, no
 * phases and no notice.
 *
 * `Number.isFinite` alone does not close this, which is why the bound is here: 1e9 is finite and
 * still crashes. The intake pattern (`20\d{2}`) narrows the anchor to a window that moves the edge
 * by about twelve days, so 1e8 days is the conservative line to hold.
 */
const MAX_OFFSET_DAYS = 100_000_000;

/**
 * The first reason a served definition cannot be walked, or `null` when it can.
 *
 * The list checks in `fetchRoadmapDefinition` say the response carries two lists; this says their
 * entries can be built into a roadmap. A phase with no `offsetDays` used to be installed as it
 * arrived: `addDays` yielded `Invalid Date`, `toISOString` threw, and the throw happened while
 * rendering — outside the promise chain, so the page's `catch` never saw it and the applicant got
 * a crash where the built-in copy belonged. The asymmetry is what let that through:
 * `phases: [null]` throws inside the mapping and does reach the `catch`, while a phase missing a
 * single field does not.
 *
 * The materials are checked for the fields a nameless or unplaceable requirement would come from:
 * a missing `key` is the React duplicate-key warning the browser walkthrough treats as a failure,
 * and a missing `phase` groups the requirement under no phase at all, so it silently never renders.
 *
 * The caller's own `tasks` are checked for the same class of entry, one step later in the chain: the
 * rows are mapped by `toTaskRows` before anything renders them, and a `null` entry throws there —
 * `Cannot read properties of null (reading 'id')`. That throw happens inside the caller's mapping
 * step, so where it lands is decided by whether the caller wrapped the mapping as well as the read;
 * this check is the half that belongs to the transport, and the answer is the same as for a phase or
 * a material that cannot be walked: the body is refused and the caller takes its fallback. The `id`
 * and `materialKey` are the two fields the page cannot do its job without — the first addresses the
 * row on the per-row edit route, the second is how a tick on screen finds its row at all — so a row
 * missing either is not a thin row but a control that would silently do nothing.
 */
function unwalkableReason(definition: ServedRoadmapDefinition): string | null {
  for (const [index, phase] of definition.phases.entries()) {
    // The declared types above are this side's claim about the wire, not a promise the wire
    // keeps: an entry can arrive as `null`, as a bare value, or as an object missing a field, and
    // finding that is what this function is for.
    const served = phase as Partial<ServedPhase> | null;
    const key = served?.key;
    if (!isFilled(key)) return `阶段 ${index} 缺少 key`;
    if (!isFilled(served?.title)) return `阶段 ${index}（${key}）缺少 title`;
    const offsetDays = served?.offsetDays;
    if (
      typeof offsetDays !== "number" ||
      !Number.isFinite(offsetDays) ||
      Math.abs(offsetDays) > MAX_OFFSET_DAYS
    ) {
      return `阶段 ${index}（${key}）的 offsetDays 不是可用的天数`;
    }
  }
  for (const [index, material] of definition.materials.entries()) {
    const served = material as Partial<ServedMaterial> | null;
    const key = served?.key;
    if (!isFilled(key)) return `材料 ${index} 缺少 key`;
    if (!isFilled(served?.phase)) return `材料 ${index}（${key}）缺少 phase`;
    if (!isFilled(served?.title)) return `材料 ${index}（${key}）缺少 title`;
  }
  // `tasks` is optional — a subject with no rows yet is the normal first answer — so the array check
  // is the loader's and this loop only walks what is already known to be a list.
  for (const [index, task] of (definition.tasks ?? []).entries()) {
    const served = task as Partial<ServedTask> | null;
    const id = served?.id;
    if (!isFilled(id)) return `任务 ${index} 缺少 id`;
    if (!isFilled(served?.materialKey)) return `任务 ${index}（${id}）缺少 materialKey`;
  }
  return null;
}

/**
 * Read the roadmap definition: which phases exist, what each one asks for, and the caller's own rows.
 *
 * The definition half is shared configuration — the phases and materials are the same for everyone —
 * but the response is not: it also carries the caller's own `tasks`, so the route reads and sets the
 * `offerpilot_client` cookie and the answer differs per subject. Reading it still writes no row: a
 * first-time visitor simply has no tasks, and the subject row is created by the first write. The
 * cookie is repeated on every response rather than only on the first, which is what `deps.py` records
 * having once got wrong in the other direction.
 *
 * What the server does *not* send is any date: the phases carry an offset in days and the client
 * derives the dates from the intake term, which is the split this task keeps on purpose.
 *
 * The body is returned as the wire shape rather than mapped. Mapping it is `roadmap-source.ts`'s job
 * and is a pure function with its own tests, so a body that passes through here unexamined can be
 * checked without a server. A failure raises rather than resolving to an empty definition, because
 * "the server said nothing" and "the server could not be reached" are different claims and only the
 * caller knows which fallback to use.
 *
 * A `200` that cannot be walked is a failure too, and it raises here instead of being handed on. The
 * caller's only lever is "did the read fail", so a well-formed definition carrying no phases has to
 * answer that question the way an unreachable route does: otherwise the page takes it as the truth,
 * overrides the built-in copy, and renders an empty timeline with no notice to say why — the blank
 * screen the fallback exists to prevent. The check lives in the transport rather than in
 * `buildRoadmap` because the builder cannot report what it did: falling back there would put the
 * built-in phases on screen while the page still believed it was rendering the server's empty
 * definition, which is the silent half of the same bug.
 *
 * The entries are checked for the values the builder cannot work without, and for nothing else. A
 * phase this build has never heard of is the server's to add, and a definition with phases and no
 * materials yet is walkable, if thin. What is refused is an entry whose own values cannot produce
 * a roadmap at all — see `unwalkableReason`, and `MAX_OFFSET_DAYS` for the one bound that is not
 * merely a missing field.
 *
 * That includes the body's third list, the caller's own `tasks`. It is optional — "this subject has
 * no rows yet" is the normal first answer — but when it is there it is checked the same way, because
 * the rows are mapped by the caller before anything renders and a `null` entry throws inside that
 * mapping. The transport is where "this response cannot be read" is decided, so the shape of the list
 * and the fields of its entries are decided here rather than by whichever caller wrapped its mapping
 * step in a `catch`.
 */
export async function fetchRoadmapDefinition(): Promise<ServedRoadmapDefinition> {
  const response = await fetch("/api/roadmap", { credentials: "same-origin" });
  if (!response.ok) throw new Error(`读取路线图定义失败：${response.status}`);
  const definition = (await response.json()) as ServedRoadmapDefinition;
  if (!Array.isArray(definition.phases)) {
    throw new Error("读取路线图定义失败：响应缺少阶段列表");
  }
  if (!Array.isArray(definition.materials)) {
    throw new Error("读取路线图定义失败：响应缺少材料列表");
  }
  // The caller's own rows are the third list the body carries and the only one that may legitimately
  // be absent. When it is present it has to be a list: `tasks: {}`, `tasks: 5` and `tasks: "pending"`
  // are bodies the checks above accept and `toTaskRows` cannot walk — `(served ?? []).map is not a
  // function` — so they used to reach the mapping and take the notice only if the caller happened to
  // have wrapped it. Refusing them here is what makes "the read failed" the transport's answer, the
  // same way an empty phase list is.
  if (definition.tasks !== undefined && !Array.isArray(definition.tasks)) {
    throw new Error("读取路线图定义失败：响应的任务列表不是列表");
  }
  if (definition.phases.length === 0) {
    throw new Error("读取路线图定义失败：响应里没有任何阶段");
  }
  const reason = unwalkableReason(definition);
  if (reason !== null) throw new Error(`读取路线图定义失败：${reason}`);
  return definition;
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

/**
 * Store one recomputation: the material keys that are applicable this round, and the rows computed
 * for them.
 *
 * The payload is built by `toReplacePayload`, which returns `null` for "do not write" — when the
 * definition on screen did not come from the server. That case never reaches this function; the
 * caller skips the call rather than sending an empty payload, because an empty `applicableKeys` is a
 * real statement that nothing applies this round and the server would delete every system row for it.
 *
 * The body is compared against the reply rather than trusted, the same way `patchProfile` checks what
 * it sent. Here the check is the four counts: every row this call sent has to come back as created or
 * updated, because a replacement that reported success while storing nothing is the silent failure
 * this whole path exists to prevent — the applicant would tick a material, the screen would keep it,
 * and the next load would find nothing. A count that disagrees is reported as a failed save naming
 * the numbers, so the caller's notice says what happened instead of "something went wrong".
 *
 * Anything else about the counts is the server's business: `kept` counts rows the caller does not own
 * and cannot predict, so it is returned rather than checked.
 */
export async function replaceRoadmapTasks(
  payload: TaskReplacePayload,
): Promise<TaskReplaceResult> {
  const response = await fetch("/api/roadmap/tasks", {
    method: "PUT",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(`保存路线图失败：${response.status}`);
  const result = (await response.json()) as TaskReplaceResult;
  const written = (result.created ?? 0) + (result.updated ?? 0);
  if (written !== payload.rows.length) {
    throw new Error(
      `保存路线图失败：服务器只写入了 ${written} 行，提交的是 ${payload.rows.length} 行`,
    );
  }
  return result;
}

/**
 * Edit one task row: its status, or its dates.
 *
 * This is the applicant's own door onto a row, and the difference from `replaceRoadmapTasks` is the
 * whole ownership rule: a replacement may only ever touch the rows the client generated, while this
 * call takes one row out of the recomputation's reach by flipping its `origin` to `user`. So a tick
 * goes here and never through the replacement, and the two are not interchangeable even though both
 * write to `roadmap_tasks`.
 *
 * The reply is the row as the server stored it, and it is returned rather than discarded: it carries
 * the server's own `status` and `completedAt`, which is what the caller's optimistic update has to
 * agree with once the request lands. It is the wire shape, so the caller reads it the way the
 * transport spells it; `toTaskRows` is what turns a list of these into this side's names. A failed
 * edit raises, because a tick the server did not take is the silent divergence this layer exists to
 * surface.
 */
export async function patchRoadmapTask(
  taskId: string,
  patch: { status?: string; dueAt?: string | null; suggestedAt?: string | null },
): Promise<ServedTask> {
  const response = await fetch(`/api/roadmap/tasks/${encodeURIComponent(taskId)}`, {
    method: "PATCH",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!response.ok) throw new Error(`保存材料状态失败：${response.status}`);
  return (await response.json()) as ServedTask;
}
