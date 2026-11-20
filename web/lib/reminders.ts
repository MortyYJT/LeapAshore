// Deadline reminders by email: the settings a signed-in applicant keeps, and the unsubscribe link
// (docs/product/PRD-multi-device.md, 3.4). No dependency on React.
//
// Settings are a versioned record like the others (see sync-conflict.ts): a save sends the version
// it was based on and a stale one throws `StaleVersionError` with the server's copy.

import { StaleVersionError, resolveStaleField, staleOf } from "./sync-conflict.ts";

export interface ReminderSettings {
  enabled: boolean;
  /** Days before a deadline, longest first. */
  leadDays: number[];
  /** When the link in an email last turned reminders off; null once they are turned back on. */
  unsubscribedAt: string | null;
  version: string;
}
export type ReminderChange = { enabled: boolean } | { leadDays: number[] };

/** The server's limits (api/app/services/reminders.py), repeated so a bad entry is caught while typing. */
export const LEAD_LIMITS = { min: 1, max: 90, count: 6 } as const;

type Fetch = (input: string, init?: RequestInit) => Promise<Response>;

/** Why this entry cannot be added as a lead time, or null when it can. */
export function leadProblem(entry: string, current: number[]): string | null {
  const text = entry.trim();
  if (!text) return "填一个天数。";
  if (!/^\d+$/.test(text)) return "天数要填整数。";
  const days = Number(text);
  if (days < LEAD_LIMITS.min || days > LEAD_LIMITS.max) return `天数要在 ${LEAD_LIMITS.min} 到 ${LEAD_LIMITS.max} 之间。`;
  if (current.includes(days)) return `已经有提前 ${days} 天的提醒了。`;
  if (current.length >= LEAD_LIMITS.count) return `最多 ${LEAD_LIMITS.count} 个，先删掉一个再加。`;
  return null;
}

export function addLead(current: number[], days: number): number[] {
  return [...new Set([...current, days])].sort((a, b) => b - a);
}

/** Without `days`; the last lead time stays, because reminders with none are reminders turned off. */
export function removeLead(current: number[], days: number): number[] {
  return current.length > 1 ? current.filter((value) => value !== days) : current;
}

export async function loadReminderSettings(fetcher: Fetch = fetch): Promise<ReminderSettings> {
  const response = await fetcher("/api/reminders/settings", { credentials: "same-origin", cache: "no-store" });
  if (!response.ok) throw Error(`读取提醒设置失败：${response.status}`);
  return response.json();
}

export async function saveReminderSettings(
  change: ReminderChange,
  baseVersion: string,
  fetcher: Fetch = fetch,
): Promise<ReminderSettings> {
  const response = await fetcher("/api/reminders/settings", {
    method: "PUT",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...change, baseVersion }),
  });
  const stale = await staleOf<ReminderSettings>(response);
  if (stale) throw stale;
  if (!response.ok) throw Error(`保存提醒设置失败：${response.status}`);
  return response.json();
}

/**
 * What to do with a change the server refused as stale: `adopt` the server's copy (it already says
 * what this change says), `retry` on the server's version (the other device changed something
 * else), or `ask` (both changed the same setting to different values).
 */
export function resolveStaleSettings(
  base: ReminderSettings,
  change: ReminderChange,
  theirs: ReminderSettings,
): "adopt" | "retry" | "ask" {
  if ("enabled" in change) return resolveStaleField(base.enabled, change.enabled, theirs.enabled);
  const text = (days: number[]) => days.join(",");
  return resolveStaleField(text(base.leadDays), text(change.leadDays), text(theirs.leadDays));
}

/** Use the link from an email. `invalid`: the server does not accept this token. `failed`: try again. */
export async function unsubscribe(token: string, fetcher: Fetch = fetch): Promise<"done" | "invalid" | "failed"> {
  if (!token) return "invalid";
  try {
    const response = await fetcher("/api/reminders/unsubscribe", {
      method: "POST",
      credentials: "omit",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    });
    if (response.ok) return "done";
    return response.status === 400 ? "invalid" : "failed";
  } catch {
    return "failed";
  }
}

/** The Beijing date of an unsubscribe, for 「…退订了」. */
export function unsubscribedDay(at: string | null): string | null {
  const time = at ? Date.parse(at) : NaN;
  if (Number.isNaN(time)) return null;
  return new Date(time + 8 * 3600 * 1000).toISOString().slice(0, 10);
}

export { StaleVersionError };
