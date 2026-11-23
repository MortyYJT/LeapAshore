// What the pages have read from the server during this visit, kept above the routes.
//
// A page's read used to live in the page: leaving it threw the data away, and coming back showed the
// placeholder until the same read answered again. Entries here outlive the page, so a return visit
// draws the last value at once and reads again behind it (stale-while-revalidate).
//
// Rules the rest of the app relies on:
// - In memory only. Nothing of an applicant's is written to storage here; a reload starts empty.
// - Per account. `clearResourceCache()` runs whenever the signed-in account changes in any direction
//   (lib/hooks/useResource.ts, components/auth/AuthProvider.tsx). It also raises the epoch, so a read
//   that was in flight for the previous account can never store its answer.
// - A write wins over a read. Every stored value, and every `invalidateResource`, raises the entry's
//   revision; a read only stores its answer if the revision is still the one it started from. A
//   background read that left before a save therefore cannot put the pre-save value back.
// - An invalidated entry is not shown to a page that mounts later (it would be pre-write data); pages
//   already showing it keep it and are told to read again.
//
// Pure and synchronous, so the rules above are unit-tested without React.

export type CacheEvent = "changed" | "invalidated" | "cleared";
type Listener = (event: CacheEvent) => void;

interface Entry {
  data: unknown;
  /** False once a write elsewhere made this value out of date. */
  current: boolean;
}

const entries = new Map<string, Entry>();
const revisions = new Map<string, number>();
const listeners = new Map<string, Set<Listener>>();
let epoch = 0;

function bump(key: string): void {
  revisions.set(key, (revisions.get(key) ?? 0) + 1);
}

function tell(key: string, event: CacheEvent): void {
  for (const listener of [...(listeners.get(key) ?? [])]) listener(event);
}

/** The value a newly mounted page may draw at once, or undefined when it has to read first. */
export function peekResource<T>(key: string): T | undefined {
  const entry = entries.get(key);
  return entry?.current ? (entry.data as T) : undefined;
}

/** Store a value the server just confirmed (a read's answer, or what a write returned). */
export function putResource<T>(key: string, data: T): void {
  entries.set(key, { data, current: true });
  bump(key);
  tell(key, "changed");
}

/** Change the stored value in place: an optimistic edit, or a merge of a fresh read into it. */
export function updateResource<T>(key: string, change: (previous: T | undefined) => T): void {
  putResource(key, change(peekResource<T>(key)));
}

/**
 * A write changed this resource on the server and the new value is not known here. Pages showing it
 * keep what they show and read again; a page that mounts later starts from its placeholder.
 */
export function invalidateResource(key: string): void {
  const entry = entries.get(key);
  if (entry) entry.current = false;
  bump(key);
  tell(key, "invalidated");
}

/** `invalidateResource` for every key that starts with `prefix`: one write that outdates a family of reads. */
export function invalidateResources(prefix: string): void {
  const keys = new Set([...entries.keys(), ...listeners.keys(), ...revisions.keys()]);
  for (const key of keys) if (key.startsWith(prefix)) invalidateResource(key);
}

/** Forget everything: the account changed, and nothing read for one may be drawn for another. */
export function clearResourceCache(): void {
  epoch += 1;
  entries.clear();
  for (const key of [...listeners.keys()]) {
    bump(key);
    tell(key, "cleared");
  }
}

export function subscribeResource(key: string, listener: Listener): () => void {
  const set = listeners.get(key) ?? new Set<Listener>();
  listeners.set(key, set);
  set.add(listener);
  return () => {
    set.delete(listener);
    if (set.size === 0) listeners.delete(key);
  };
}

/** A read in progress: where the entry and the account stood when it left. */
export interface ReadTicket {
  key: string;
  revision: number;
  epoch: number;
}

export function beginRead(key: string): ReadTicket {
  return { key, revision: revisions.get(key) ?? 0, epoch };
}

/** Whether nothing was stored, invalidated or cleared since the read left. */
export function readStillCurrent(ticket: ReadTicket): boolean {
  return ticket.epoch === epoch && ticket.revision === (revisions.get(ticket.key) ?? 0);
}

/** Whether the account is still the one the read left for (a merge that tolerates newer writes). */
export function sameAccount(ticket: ReadTicket): boolean {
  return ticket.epoch === epoch;
}

/**
 * Store a read's answer unless something newer is already there. Returns whether it was stored.
 * An answer equal to the stored value keeps the stored object, so nothing that draws it re-renders.
 */
export function finishRead<T>(ticket: ReadTicket, data: T): boolean {
  if (!readStillCurrent(ticket)) return false;
  const entry = entries.get(ticket.key);
  if (entry?.current && sameValue(entry.data, data)) return true;
  putResource(ticket.key, data);
  return true;
}

/** Structural equality of two served values (plain JSON data). */
export function sameValue(a: unknown, b: unknown): boolean {
  if (Object.is(a, b)) return true;
  try {
    return JSON.stringify(a) === JSON.stringify(b);
  } catch {
    return false;
  }
}
