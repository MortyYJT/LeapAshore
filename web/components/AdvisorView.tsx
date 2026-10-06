"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Front-end skeleton for the advisor. The layout follows a chat product: a conversation rail on the
 * left, the message column in the middle and a composer pinned to the bottom.
 *
 * No model is connected yet. Sending a message appends it and then answers with a fixed notice, so the
 * interaction can be reviewed without pretending an assistant replied.
 */

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
}

interface Conversation {
  id: string;
  title: string;
  messages: Message[];
}

const NOT_CONNECTED =
  "留学顾问还没接入模型，暂时不能回答。你可以先在「流程进度」里看每个阶段要准备的材料，或者到「个人信息」补充档案。";

const SUGGESTIONS = [
  "帮我看看现在的选校组合合不合理",
  "语言成绩还不够，我该怎么安排",
  "提交申请前还差哪些材料",
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

  function send(text: string) {
    const content = text.trim();
    if (!content || !active) return;
    const userMessage: Message = { id: uid(), role: "user", content };

    setConversations((prev) =>
      prev.map((c) =>
        c.id === active.id
          ? {
              ...c,
              title: c.messages.length === 0 ? content.slice(0, 16) : c.title,
              messages: [...c.messages, userMessage],
            }
          : c,
      ),
    );
    setDraft("");
    setThinking(true);

    window.setTimeout(() => {
      setConversations((prev) =>
        prev.map((c) =>
          c.id === active.id
            ? {
                ...c,
                messages: [...c.messages, { id: uid(), role: "assistant", content: NOT_CONNECTED }],
              }
            : c,
        ),
      );
      setThinking(false);
    }, 500);
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
                顾问能力还在搭建中。上线后你可以用一句话推进申请：问官方要求、更新档案、调整申请组合。
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
                    <div className="text-sm leading-relaxed text-[var(--color-ink)]">{m.content}</div>
                  </div>
                ),
              )}
              {thinking && (
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
            顾问尚未接入模型，当前只演示交互。
          </p>
        </div>
      </section>
    </div>
  );
}
