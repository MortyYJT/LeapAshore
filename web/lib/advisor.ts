/**
 * Client for the advisor's server-sent event stream (`api/app/routers/advisor.py`).
 *
 * The endpoints are POST, so `EventSource` cannot be used; the body is read as a stream and split on
 * the blank line that ends each event.
 */

export interface Citation {
  n: number;
  programId: string;
  program: string;
  title: string;
  url: string;
  status: "已核验" | "待核验";
}

export type AdvisorEvent =
  | { type: "intent"; intent: string; confidence: number }
  | { type: "citations"; gate: "pass" | "refuse"; citations: Citation[] }
  | { type: "tool"; name: string }
  | { type: "token"; text: string }
  | { type: "confirm"; summary: string; id?: string }
  | { type: "error"; message: string }
  | { type: "done" };

/**
 * `unauthorized` when the server refused for want of a session (login mode, session expired);
 * `limited` when a rate limit or a daily token quota refused the turn, or the limit store was down
 * (openspec/changes/advisor-limits) — nothing ran, so a refused confirm can be answered again.
 */
export type StreamOutcome = "ok" | "unauthorized" | "limited" | "failed";

const LIMITED_FALLBACK: Record<number, string> = {
  429: "发送太频繁或今天的额度已用完，请稍后再试。",
  503: "顾问暂时不可用，请稍后再试。",
};

/** What to tell the applicant when the server refused a turn before streaming anything. */
export function advisorRefusal(status: number, body: unknown): { outcome: Exclude<StreamOutcome, "ok">; message: string } {
  if (status === 401) return { outcome: "unauthorized", message: "登录已失效，请重新登录后再发。" };
  const detail = (body as { detail?: unknown } | null)?.detail;
  const serverMessage =
    detail && typeof detail === "object" && typeof (detail as { message?: unknown }).message === "string"
      ? (detail as { message: string }).message
      : null;
  if (status in LIMITED_FALLBACK) return { outcome: "limited", message: serverMessage || LIMITED_FALLBACK[status] };
  return { outcome: "failed", message: `顾问服务不可用（HTTP ${status}）` };
}

async function stream(path: string, body: unknown, onEvent: (e: AdvisorEvent) => void): Promise<StreamOutcome> {
  const response = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok || !response.body) {
    const refusal = advisorRefusal(response.status, await response.json().catch(() => null));
    onEvent({ type: "error", message: refusal.message });
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

export function sendAdvisorMessage(conversationId: string, message: string, onEvent: (e: AdvisorEvent) => void) {
  return stream("/api/advisor/chat", { conversationId, message }, onEvent);
}

/**
 * The body of a confirm. `interruptId` is the `id` of the `confirm` event being answered: the server
 * applies the answer to that change only, so a repeated click that arrives after the turn has moved on
 * to another change does not answer the new one (openspec/changes/advisor-persistence D5).
 */
export function confirmBody(conversationId: string, approved: boolean, interruptId?: string) {
  return interruptId ? { conversationId, approved, interruptId } : { conversationId, approved };
}

export function confirmAdvisorAction(
  conversationId: string,
  approved: boolean,
  onEvent: (e: AdvisorEvent) => void,
  interruptId?: string,
) {
  return stream("/api/advisor/confirm", confirmBody(conversationId, approved, interruptId), onEvent);
}

/** Display names for the tools, so the interface shows what the agent did in the applicant's words. */
export const TOOL_LABELS: Record<string, string> = {
  search_programs: "搜索项目",
  get_my_profile: "读取档案",
  update_my_profile: "更新档案",
  get_my_portfolio: "读取选校组合",
  propose_portfolio_change: "提议修改组合",
};
