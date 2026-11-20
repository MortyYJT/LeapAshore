/**
 * Client for the advisor's server-sent event stream (`api/app/routers/advisor.py`).
 *
 * The endpoints are POST, so `EventSource` cannot be used; the body is read as a stream and split on
 * the blank line that ends each event.
 */

/** One value the catalogue holds for a cited program. With `quote`, the sentence it was read from. */
export interface CitationField {
  label: string;
  value: string;
  quote?: string;
  /** The page the value is on, when it is not the citation's own page. */
  url?: string;
}

export interface Citation {
  n: number;
  programId: string;
  program: string;
  title: string;
  url: string;
  status: "已核验" | "待核验";
  /** A requirement answer: the collected values the answer was written from. */
  fields?: CitationField[];
  /** A page answer: what the quotations are about, and the sentences that passed the quote check. */
  field?: string;
  quotes?: string[];
  fetchedAt?: string | null;
}

export interface Detail {
  label: string;
  value: string;
}

/** `running` opens a step; every other status closes it. */
export type StepStatus = "running" | "done" | "empty" | "failed" | "waiting" | "declined" | "stopped";

/** One thing the agent does in a turn. The first event of a step carries what it is; later ones how it ended. */
export interface StepEvent {
  type: "step";
  id: string;
  status: StepStatus;
  kind?: string;
  name?: string;
  title?: string;
  args?: Detail[];
  ms?: number;
  result?: string;
  items?: string[];
  write?: boolean;
}

/** What a proposed change is about. A catalogue program has `programId`; an application the applicant
 * already has carries its record id, which is null for one that is about to be added. */
export interface ChangeTarget {
  applicationId?: string | null;
  programId?: string | null;
  school?: string;
  program?: string;
}

/** The key a target's application goes by in the records: its record id, or its catalogue program. */
export function targetKey(target: ChangeTarget | undefined): string | undefined {
  return target?.applicationId ?? target?.programId ?? undefined;
}

/** One line of a confirm question: the stored value and the value it becomes. `before` is null when there is none yet. */
export interface Change {
  label: string;
  before: string | null;
  after: string;
}

export interface ConfirmEvent {
  type: "confirm";
  summary: string;
  id?: string;
  /** The step that asked. */
  stepId?: string;
  target?: ChangeTarget;
  changes?: Change[];
}

export type AdvisorEvent =
  | StepEvent
  | { type: "intent"; intent: string; confidence: number }
  | { type: "citations"; gate: "pass" | "refuse"; citations: Citation[] }
  | { type: "tool"; name: string }
  | { type: "token"; text: string }
  | ConfirmEvent
  | { type: "error"; message: string; code?: string }
  | { type: "stopped"; wrote?: boolean }
  | { type: "done" };

/**
 * `unauthorized` when the server refused for want of a session (login mode, session expired);
 * `limited` when a rate limit or a daily token quota refused the turn, or the limit store was down
 * (openspec/changes/archive/2026-10-30-advisor-limits) — nothing ran, so a refused confirm can be answered again.
 */
export type StreamOutcome = "ok" | "unauthorized" | "limited" | "failed";

const LIMITED_FALLBACK: Record<number, string> = {
  429: "发送太频繁或今天的额度已用完，请稍后再试。",
  503: "顾问暂时不可用，请稍后再试。",
};

/** What to tell the applicant when the server refused a turn before streaming anything. */
export function advisorRefusal(
  status: number,
  body: unknown,
): { outcome: Exclude<StreamOutcome, "ok">; message: string; code: string } {
  if (status === 401) return { outcome: "unauthorized", message: "登录已失效，请重新登录后再发。", code: "unauthorized" };
  const detail = (body as { detail?: unknown } | null)?.detail;
  const field = (name: string) =>
    detail && typeof detail === "object" && typeof (detail as Record<string, unknown>)[name] === "string"
      ? ((detail as Record<string, unknown>)[name] as string)
      : null;
  if (status in LIMITED_FALLBACK) {
    // The server's code says which limit it was: `rate_limited`, `daily_tokens_*`, `limits_unavailable`.
    const code = field("code") ?? (status === 429 ? "rate_limited" : "limits_unavailable");
    return { outcome: "limited", message: field("message") || LIMITED_FALLBACK[status], code };
  }
  return { outcome: "failed", message: `顾问服务不可用（HTTP ${status}）`, code: "http" };
}

async function stream(path: string, body: unknown, onEvent: (e: AdvisorEvent) => void, signal?: AbortSignal): Promise<StreamOutcome> {
  const response = await fetch(path, {
    method: "POST",
    signal,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok || !response.body) {
    const refusal = advisorRefusal(response.status, await response.json().catch(() => null));
    onEvent({ type: "error", message: refusal.message, code: refusal.code });
    onEvent({ type: "done" });
    return refusal.outcome;
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let end = buffer.indexOf("\n\n");
    while (end !== -1) {
      const line = buffer.slice(0, end).trim();
      buffer = buffer.slice(end + 2);
      if (line.startsWith("data:")) onEvent(JSON.parse(line.slice(5)) as AdvisorEvent);
      end = buffer.indexOf("\n\n");
    }
  }
  return "ok";
}

export function sendAdvisorMessage(conversationId: string, message: string, onEvent: (e: AdvisorEvent) => void, signal?: AbortSignal) {
  return stream("/api/advisor/chat", { conversationId, message }, onEvent, signal);
}

/**
 * The body of a confirm. `interruptId` is the `id` of the `confirm` event being answered: the server
 * applies the answer to that change only, so a repeated click that arrives after the turn has moved on
 * to another change does not answer the new one (openspec/changes/archive/2026-10-30-advisor-persistence D5).
 */
export function confirmBody(conversationId: string, approved: boolean, interruptId?: string) {
  return interruptId ? { conversationId, approved, interruptId } : { conversationId, approved };
}

export function confirmAdvisorAction(
  conversationId: string,
  approved: boolean,
  onEvent: (e: AdvisorEvent) => void,
  interruptId?: string,
  signal?: AbortSignal,
) {
  return stream("/api/advisor/confirm", confirmBody(conversationId, approved, interruptId), onEvent, signal);
}

/**
 * Ask the server to stop the turn running in this conversation. The step in flight finishes and nothing
 * else starts (`api/app/agent/halt.py`). Best effort: the page has already stopped listening, and
 * `keepalive` lets the request outlive a navigation.
 */
export function stopAdvisorTurn(conversationId: string): void {
  void fetch("/api/advisor/stop", {
    method: "POST",
    credentials: "same-origin",
    keepalive: true,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ conversationId }),
  }).catch(() => undefined);
}
