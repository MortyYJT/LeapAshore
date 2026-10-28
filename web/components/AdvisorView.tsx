"use client";

import { useEffect, useRef, useState } from "react";
import {
  type AdvisorEvent,
  type Citation,
  TOOL_LABELS,
  confirmAdvisorAction,
  sendAdvisorMessage,
} from "../lib/advisor";

/**
 * The advisor chat. A conversation rail on the left, the message column in the middle and a
 * composer pinned to the bottom. Replies stream from the LangGraph agent behind `/api/advisor`; each
 * assistant message also shows what the agent decided along the way — the routed intent, the tools
 * it called, the official sources the evidence gate let through — so its reasoning is visible.
 */

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  intent?: string;
  tools?: string[];
  citations?: Citation[];
  gate?: "pass" | "refuse";
  confirm?: { summary: string; state: "pending" | "approved" | "rejected" };
  error?: string;
}

interface Conversation {
  id: string;
  title: string;
  messages: Message[];
}

const SUGGESTIONS = [
  "悉尼大学计算机硕士要什么均分和雅思？",
  "我是武汉大学计算机专业，均分 85，雅思 7.0",
  "把蒙纳士人工智能硕士加进我的选校组合，作为冲刺",
];

function uid() {
  return Math.random().toString(36).slice(2, 10);
}

function newConversation(): Conversation {
  return { id: uid(), title: "新对话", messages: [] };
}

export default function AdvisorView() {
  const [conversations, setConversations] = useState<Conversation[]>(() => {
    const first = newConversation();
    return [first];
  });
  const [activeId, setActiveId] = useState<string>(() => "");
  const [draft, setDraft] = useState("");
  const [thinking, setThinking] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Resolve the initial active conversation once, so the first render and the state agree.
  useEffect(() => {
    setActiveId((id) => id || conversations[0].id);
  }, [conversations]);

  const active = conversations.find((c) => c.id === activeId) ?? conversations[0];

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [active?.messages.length, thinking]);

  function patchAssistant(convId: string, msgId: string, patch: (m: Message) => Message) {
    setConversations((prev) =>
      prev.map((c) =>
        c.id === convId ? { ...c, messages: c.messages.map((m) => (m.id === msgId ? patch(m) : m)) } : c,
      ),
    );
  }

  function handlerFor(convId: string, msgId: string) {
    return (e: AdvisorEvent) => {
      if (e.type === "done") {
        setThinking(false);
        return;
      }
      patchAssistant(convId, msgId, (m) => {
        switch (e.type) {
          case "intent":
            return { ...m, intent: e.intent };
          case "citations":
            return { ...m, citations: e.citations, gate: e.gate };
          case "tool":
            return { ...m, tools: [...(m.tools ?? []), e.name] };
          case "token":
            return { ...m, content: m.content + e.text };
          case "confirm":
            return { ...m, confirm: { summary: e.summary, state: "pending" } };
          case "error":
            return { ...m, error: e.message };
        }
      });
    };
  }

  function send(text: string) {
    const content = text.trim();
    if (!content || !active || thinking) return;
    const userMessage: Message = { id: uid(), role: "user", content };
    const reply: Message = { id: uid(), role: "assistant", content: "" };
    const convId = active.id;

    setConversations((prev) =>
      prev.map((c) =>
        c.id === convId
          ? {
              ...c,
              title: c.messages.length === 0 ? content.slice(0, 16) : c.title,
              messages: [...c.messages, userMessage, reply],
            }
          : c,
      ),
    );
    setDraft("");
    setThinking(true);
    sendAdvisorMessage(convId, content, handlerFor(convId, reply.id)).catch(() => {
      patchAssistant(convId, reply.id, (m) => ({ ...m, error: "网络错误，请稍后再试。" }));
      setThinking(false);
    });
  }

  function answerConfirm(msg: Message, approved: boolean) {
    if (!active || thinking) return;
    const convId = active.id;
    patchAssistant(convId, msg.id, (m) => ({
      ...m,
      confirm: m.confirm && { ...m.confirm, state: approved ? "approved" : "rejected" },
    }));
    const reply: Message = { id: uid(), role: "assistant", content: "" };
    setConversations((prev) =>
      prev.map((c) => (c.id === convId ? { ...c, messages: [...c.messages, reply] } : c)),
    );
    setThinking(true);
    confirmAdvisorAction(convId, approved, handlerFor(convId, reply.id)).catch(() => {
      patchAssistant(convId, reply.id, (m) => ({ ...m, error: "网络错误，请稍后再试。" }));
      setThinking(false);
    });
  }

  function startNew() {
    const conv = newConversation();
    setConversations((prev) => [conv, ...prev]);
    setActiveId(conv.id);
    setDraft("");
  }

  return (
    <div className="grid h-[calc(100vh-140px)] min-h-[520px] grid-cols-1 overflow-hidden rounded-2xl border-2 border-[var(--color-line)] bg-[var(--color-canvas)] md:grid-cols-[236px_1fr]">
      {/* Conversation rail */}
      <aside className="hidden flex-col border-r-2 border-[var(--color-line)] bg-[var(--color-surface)] md:flex">
        <div className="p-3">
          <button className="btn btn-primary w-full !py-2 !text-sm" onClick={startNew}>
            ＋ 新对话
          </button>
        </div>
        <div className="px-4 pb-1 pt-2 text-[11px] font-bold text-[var(--color-ink-soft)]">最近</div>
        <nav className="flex-1 overflow-y-auto px-2 pb-3">
          {conversations.map((c) => (
            <button
              key={c.id}
              onClick={() => setActiveId(c.id)}
              className="mb-1 block w-full truncate rounded-lg px-3 py-2 text-left text-sm transition-colors"
              style={
                c.id === active?.id
                  ? {
                      background: "var(--color-brand-soft)",
                      color: "var(--color-brand-dark)",
                      fontWeight: 700,
                    }
                  : { color: "var(--color-ink-soft)" }
              }
            >
              {c.title}
            </button>
          ))}
        </nav>
      </aside>

      {/* Message column */}
      <section className="flex min-w-0 flex-col">
        <header className="flex items-center justify-between gap-3 border-b-2 border-[var(--color-line)] px-5 py-3">
          <div className="min-w-0">
            <div className="truncate text-sm font-extrabold">{active?.title ?? "新对话"}</div>
            <div className="text-[11px] text-[var(--color-ink-soft)]">申请顾问</div>
          </div>
          <button className="btn btn-ghost !px-3 !py-1.5 !text-xs md:hidden" onClick={startNew}>
            ＋ 新对话
          </button>
        </header>

        <div ref={scrollRef} className="flex-1 overflow-y-auto px-5 py-6">
          {active && active.messages.length === 0 ? (
            <div className="mx-auto flex h-full max-w-md flex-col items-center justify-center text-center">
              <div className="mb-3 text-3xl">🧭</div>
              <h2 className="text-lg font-extrabold">有什么可以帮你？</h2>
              <p className="mt-2 text-sm leading-relaxed text-[var(--color-ink-soft)]">
                用一句话推进申请：问官方要求、补充背景、调整选校组合。涉及官方要求的回答都会附上来源；查不到来源时我会直接说查不到。
              </p>
              <div className="mt-6 grid w-full gap-2">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    onClick={() => send(s)}
                    className="rounded-xl border-2 border-[var(--color-line)] px-4 py-2.5 text-left text-sm font-semibold transition-colors hover:border-[var(--color-brand)] hover:bg-[var(--color-surface)]"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="mx-auto grid max-w-2xl gap-5">
              {active?.messages.map((m) =>
                m.role === "user" ? (
                  <div key={m.id} className="flex justify-end">
                    <div
                      className="max-w-[80%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed"
                      style={{ background: "var(--color-brand-soft)", color: "var(--color-ink)" }}
                    >
                      {m.content}
                    </div>
                  </div>
                ) : (
                  <div key={m.id} className="flex gap-3">
                    <span
                      className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-sm"
                      style={{ background: "var(--color-surface)" }}
                    >
                      🧭
                    </span>
                    <AssistantBody message={m} busy={thinking} onConfirm={answerConfirm} />
                  </div>
                ),
              )}
              {thinking && active?.messages.at(-1)?.content === "" && (
                <div className="flex gap-3">
                  <span
                    className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-sm"
                    style={{ background: "var(--color-surface)" }}
                  >
                    🧭
                  </span>
                  <div className="text-sm text-[var(--color-ink-soft)]">正在整理…</div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Composer */}
        <div className="border-t-2 border-[var(--color-line)] px-5 py-4">
          <div className="mx-auto flex max-w-2xl items-end gap-2 rounded-2xl border-2 border-[var(--color-line)] p-2 transition-colors focus-within:border-[var(--color-brand)]">
            <textarea
              rows={1}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send(draft);
                }
              }}
              placeholder="给留学顾问发消息…"
              className="max-h-32 min-h-[38px] flex-1 resize-none bg-transparent px-2 py-2 text-sm outline-none"
            />
            <button
              aria-label="发送"
              onClick={() => send(draft)}
              disabled={!draft.trim()}
              className="btn btn-primary !rounded-xl !px-3 !py-2.5"
            >
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" aria-hidden>
                <path
                  d="M12 19V5m0 0l-6 6m6-6l6 6"
                  stroke="currentColor"
                  strokeWidth="2.2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </button>
          </div>
          <p className="mx-auto mt-2 max-w-2xl text-center text-[11px] text-[var(--color-ink-soft)]">
            回答只引用已收录的官方来源；标"待核验"的数据请以学校官网为准。
          </p>
        </div>
      </section>
    </div>
  );
}

const INTENT_COLORS: Record<string, string> = {
  官方要求核验: "var(--color-brand-soft)",
};

function AssistantBody({
  message: m,
  busy,
  onConfirm,
}: {
  message: Message;
  busy: boolean;
  onConfirm: (m: Message, approved: boolean) => void;
}) {
  return (
    <div className="min-w-0 flex-1 text-sm leading-relaxed text-[var(--color-ink)]">
      {(m.intent || (m.tools && m.tools.length > 0)) && (
        <div className="mb-2 flex flex-wrap gap-1.5 text-[11px]">
          {m.intent && (
            <span
              className="rounded-full px-2 py-0.5 font-bold"
              style={{ background: INTENT_COLORS[m.intent] ?? "var(--color-surface)" }}
            >
              意图：{m.intent}
            </span>
          )}
          {m.gate && (
            <span className="rounded-full bg-[var(--color-surface)] px-2 py-0.5 font-bold">
              证据门禁：{m.gate === "pass" ? "通过" : "拒答"}
            </span>
          )}
          {m.tools?.map((t, i) => (
            <span key={i} className="rounded-full bg-[var(--color-surface)] px-2 py-0.5">
              🔧 {TOOL_LABELS[t] ?? t}
            </span>
          ))}
        </div>
      )}
      {m.content && <div className="whitespace-pre-wrap">{m.content}</div>}
      {m.citations && m.citations.length > 0 && (
        <ol className="mt-3 grid gap-1 rounded-xl border-2 border-[var(--color-line)] p-3 text-xs">
          {m.citations.map((c) => (
            <li key={c.n}>
              [{c.n}]{" "}
              <a href={c.url} target="_blank" rel="noreferrer" className="underline">
                {c.title}
              </a>{" "}
              <span
                className="rounded px-1 font-bold"
                style={{ color: c.status === "已核验" ? "var(--color-brand-dark)" : "#b45309" }}
              >
                {c.status}
              </span>
            </li>
          ))}
        </ol>
      )}
      {m.confirm && (
        <div className="mt-3 rounded-xl border-2 border-[var(--color-brand)] p-3">
          <div className="text-xs font-bold text-[var(--color-ink-soft)]">需要你确认</div>
          <div className="mt-1 font-semibold">{m.confirm.summary}</div>
          {m.confirm.state === "pending" ? (
            <div className="mt-2 flex gap-2">
              <button className="btn btn-primary !px-3 !py-1.5 !text-xs" disabled={busy} onClick={() => onConfirm(m, true)}>
                确认执行
              </button>
              <button className="btn btn-ghost !px-3 !py-1.5 !text-xs" disabled={busy} onClick={() => onConfirm(m, false)}>
                取消
              </button>
            </div>
          ) : (
            <div className="mt-2 text-xs text-[var(--color-ink-soft)]">
              {m.confirm.state === "approved" ? "已确认" : "已取消"}
            </div>
          )}
        </div>
      )}
      {m.error && <div className="mt-2 text-xs font-bold text-red-700">{m.error}</div>}
    </div>
  );
}
