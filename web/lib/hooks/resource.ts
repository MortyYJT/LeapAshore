// One read of one server resource, as every page sees it: `{ data, error, loading, reload }` (design D1).
// The state transitions are a pure function so the error path can be tested without React.
//
// A resource with a key is also kept in `resource-cache.ts`, above the pages: the state a page starts
// from is the value read earlier in the visit, and every read stores its answer there.

import { beginRead, finishRead, peekResource, sameAccount, type ReadTicket } from "../resource-cache.ts";

export interface LoadState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
}

export interface Resource<T> extends LoadState<T> {
  reload: () => void;
}

export const INITIAL: LoadState<never> = { data: null, error: null, loading: true };

/**
 * Run a read and return the state it leaves. A failed reload keeps the data already on screen: the
 * applicant keeps what they were reading, and the error says the refresh did not land.
 */
export async function settle<T>(load: () => Promise<T>, previous: LoadState<T>): Promise<LoadState<T>> {
  try {
    return { data: await load(), error: null, loading: false };
  } catch (error: unknown) {
    return {
      data: previous.data,
      error: error instanceof Error && error.message ? error.message : "读取失败，请稍后再试。",
      loading: false,
    };
  }
}

/**
 * The state a page starts from. With a value read earlier in this visit there is nothing to wait
 * for: it is drawn at once, and the read that follows runs behind it.
 */
export function initialState<T>(key?: string): LoadState<T> {
  const cached = key === undefined ? undefined : peekResource<T>(key);
  return cached === undefined ? INITIAL : { data: cached, error: null, loading: false };
}

/**
 * One read of a cached resource, and the state it leaves the page in; `null` when the page must keep
 * what it has because the answer is not for it any more (the account changed while it was in flight).
 *
 * - An answer is stored and shown, unless a write stored or invalidated something after the read
 *   left: then the newer value stays, here and in the cache.
 * - A failed read keeps the data on screen and in the cache, and reports the error beside it.
 */
export async function readThrough<T>(
  key: string,
  load: () => Promise<T>,
  previous: LoadState<T>,
  ticket: ReadTicket = beginRead(key),
): Promise<LoadState<T> | null> {
  const next = await settle(load, previous);
  if (!sameAccount(ticket)) return null;
  if (next.error !== null) return next;
  if (finishRead(ticket, next.data as T)) {
    // The stored object, which is the earlier one when the answer was equal to it.
    return { data: peekResource<T>(key) ?? next.data, error: null, loading: false };
  }
  const newer = peekResource<T>(key);
  return { data: newer === undefined ? previous.data : newer, error: null, loading: false };
}

/** Sent on `window` when a read of the account's data is answered 401: the session is over. */
export const SESSION_ENDED = "leapashore:session-ended";

/**
 * Whether a read's error says the server no longer knows the session (the readers in `lib/api.ts`
 * end their message with the status). The session is then read again, and when it names no account
 * everything kept for the visit is dropped (components/auth/AuthProvider.tsx).
 */
export function saysSignedOut(error: string | null): boolean {
  return error !== null && /[:：]\s*401$/.test(error.trim());
}
