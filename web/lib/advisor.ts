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
  | { type: "confirm"; summary: string }
  | { type: "error"; message: string }
  | { type: "done" };

async function stream(path: string, body: unknown, onEvent: (e: AdvisorEvent) => void) {
  const response = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok || !response.body) {
    onEvent({ type: "error", message: `顾问服务不可用（HTTP ${response.status}）` });
    onEvent({ type: "done" });
    return;
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
}

export function sendAdvisorMessage(conversationId: string, message: string, onEvent: (e: AdvisorEvent) => void) {
  return stream("/api/advisor/chat", { conversationId, message }, onEvent);
}

export function confirmAdvisorAction(conversationId: string, approved: boolean, onEvent: (e: AdvisorEvent) => void) {
  return stream("/api/advisor/confirm", { conversationId, approved }, onEvent);
}

/** Display names for the tools, so the interface shows what the agent did in the applicant's words. */
export const TOOL_LABELS: Record<string, string> = {
  search_programs: "搜索项目",
  get_my_profile: "读取档案",
  update_my_profile: "更新档案",
  get_my_portfolio: "读取选校组合",
  propose_portfolio_change: "提议修改组合",
};
