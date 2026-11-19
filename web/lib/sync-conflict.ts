// Sync conflict handling on the client (docs/product/PRD-multi-device.md, 3.3).
//
// Every applicant-editable record the server serves carries a `version`, and every update sends the
// version it was based on. When another device has changed the record since, the server writes
// nothing and answers 409 with `code: "stale_version"` and the record as it holds it (`current`).
//
// This module is the whole client-side rule and has no dependency on React or on the page layout:
// - `staleOf` turns that 409 into a `StaleVersionError` carrying `current`; the write helpers in
//   `api.ts` and `application-records.ts` throw it;
// - a caller that catches it shows that the record changed elsewhere and offers two actions: keep
//   mine (send the same edit again with `current`'s version) or take the server's (drop the edit and
//   show `current`);
// - `resolveStaleField` decides the one case that needs no question, for a field that saves itself.

export const STALE_CODE = "stale_version";

/** A write the server refused because the record changed elsewhere. `current` is the server's copy. */
export class StaleVersionError<T = unknown> extends Error {
  readonly current: T;

  constructor(current: T, message = "这条记录已在其他设备上修改。") {
    super(message);
    this.name = "StaleVersionError";
    this.current = current;
  }
}

/**
 * The conflict a response reports, or null when it is anything else.
 *
 * Only a 409 whose body names the stale code counts: the material routes answer 409 for their own
 * refusals. The body is read from a copy, so the caller can still read the response it was given.
 */
export async function staleOf<T>(response: Response): Promise<StaleVersionError<T> | null> {
  if (response.status !== 409) return null;
  try {
    const body = (await response.clone().json()) as { code?: unknown; detail?: unknown; current?: T };
    if (body?.code !== STALE_CODE) return null;
    return new StaleVersionError(
      body.current as T,
      typeof body.detail === "string" && body.detail ? body.detail : undefined,
    );
  } catch {
    return null;
  }
}

/**
 * What to do when a single auto-saved field (a checkbox, say) was refused as stale.
 *
 * `base` is the value the edit started from, `mine` the value being saved and `theirs` the value the
 * server holds now.
 * - `adopt`: the server already holds my value; take its row and save nothing.
 * - `retry`: the row changed but this field did not; send the edit again on the server's version.
 *   Nothing of the other change is overwritten, because the update names only this field.
 * - `ask`: the field itself was changed to something else; only the applicant can choose.
 */
export function resolveStaleField<V>(base: V, mine: V, theirs: V): "adopt" | "retry" | "ask" {
  if (theirs === mine) return "adopt";
  if (theirs === base) return "retry";
  return "ask";
}

/**
 * A key for one intended create. The same key is sent again when that create is retried.
 *
 * 128 random bits as hex. `crypto.getRandomValues` rather than `crypto.randomUUID`, which browsers
 * only provide on https and localhost: the app is also opened over plain http from a LAN address.
 */
export function newIdempotencyKey(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

/** An untouched input reads as "", null or undefined depending on where it came from; all three are empty. */
function emptyAsNull(value: unknown): unknown {
  return value === undefined || value === "" ? null : value;
}

/**
 * The part of a form the applicant actually changed, given the record the form was opened on.
 *
 * This is what "keep mine" sends after a refused save. A form submits every field, including the
 * ones still showing what the record held when it was opened; restating those on the server's newer
 * version would undo the other device's change to a field this applicant never touched.
 */
export function changedFields<T extends object>(mine: T, base: object | null | undefined): Partial<T> {
  if (!base) return mine;
  const before = base as Record<string, unknown>;
  return Object.fromEntries(
    Object.entries(mine).filter(([key, value]) => emptyAsNull(value) !== emptyAsNull(before[key])),
  ) as Partial<T>;
}
