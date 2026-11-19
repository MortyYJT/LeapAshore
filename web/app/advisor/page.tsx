"use client";

import { memo, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { useAuth } from "@/components/auth/AuthProvider";
import { Pill } from "@/components/ui";
import {
  confirmAdvisorAction,
  sendAdvisorMessage,
  TOOL_LABELS,
  type AdvisorEvent,
  type Citation,
} from "@/lib/advisor";
import { verifiedMark } from "@/lib/taxonomy";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  intent?: string;
  tools?: string[];
  citations?: Citation[];
  gate?: "pass" | "refuse";
  confirm?: {
    summary: string;
    id?: string;
    state: "pending" | "approved" | "rejected";
  };
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
  "把我组合里的第一个项目标成已提交",
];

const uid = () => Math.random().toString(36).slice(2, 10);
const newConversation = (): Conversation => ({
  id: uid(),
  title: "新对话",
  messages: [],
});

/**
 * The advisor (spec app-navigation: restyled on the shell, confirm flow unchanged). Replies stream from
 * the agent behind /api/advisor; each reply shows the tools called and the official sources the evidence
 * gate let through, and a portfolio change waits for the applicant's confirm. The routed intent and the
 * gate's verdict are kept on the message but not shown: they describe the machinery, not the answer.
 */
export default function AdvisorPage() {
  const [conversations, setConversations] = useState<Conversation[]>(() => [
    newConversation(),
  ]);
  const [activeId, setActiveId] = useState(() => conversations[0].id);
  const [draft, setDraft] = useState("");
  const [request, setRequest] = useState<{ convId: string; controller?: AbortController } | null>(null);
  const thinking = request !== null;
  const body = useRef<HTMLDivElement>(null);
  const followTail = useRef(true);
  const scrollPositions = useRef(new Map<string, number>());
  const shownConversation = useRef(activeId);
  const { requireLogin, refresh } = useAuth();
  const asking = useRef(false);
  useEffect(() => {
    const question = new URLSearchParams(window.location.search).get("q");
    if (question) setDraft(question.slice(0, 4000));
  }, []);
  const active =
    conversations.find((c) => c.id === activeId) ?? conversations[0];

  useLayoutEffect(() => {
    const element = body.current;
    if (!element) return;
    if (shownConversation.current !== active.id) {
      shownConversation.current = active.id;
      element.scrollTop = scrollPositions.current.get(active.id) ?? element.scrollHeight;
      followTail.current = element.scrollHeight - element.clientHeight - element.scrollTop <= 32;
    }
    if (followTail.current) element.scrollTop = element.scrollHeight;
  }, [active.id, active.messages, request]);

  useEffect(() => () => request?.controller?.abort(), [request]);

  const patch = useCallback((
    convId: string,
    msgId: string,
    change: (m: Message) => Message,
  ) => {
    setConversations((prev) =>
      prev.map((c) =>
        c.id === convId
          ? {
              ...c,
              messages: c.messages.map((m) => (m.id === msgId ? change(m) : m)),
            }
          : c,
      ),
    );
  }, []);

  const handlerFor = useCallback((convId: string, msgId: string) => {
    return (e: AdvisorEvent) => {
      if (e.type === "done") return;
      patch(convId, msgId, (m) => {
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
            return {
              ...m,
              confirm: { summary: e.summary, id: e.id, state: "pending" },
            };
          case "error":
            return { ...m, error: e.message };
        }
      });
    };
  }, [patch]);

  /**
   * Send `text`. In login mode a logged-out visitor gets the login dialog first; the sentence stays in the
   * composer while it is open and is sent as typed once the dialog finishes (openspec account-login D11).
   */
  async function send(text: string) {
    const content = text.trim();
    if (!content || thinking || asking.current) return;
    asking.current = true;
    const allowed = await requireLogin().catch(() => false);
    if (!allowed) {
      asking.current = false;
      return;
    }
    const convId = active.id;
    const reply: Message = { id: uid(), role: "assistant", content: "" };
    setConversations((prev) =>
      prev.map((c) =>
        c.id === convId
          ? {
              ...c,
              title: c.messages.length === 0 ? content.slice(0, 16) : c.title,
              messages: [
                ...c.messages,
                { id: uid(), role: "user", content },
                reply,
              ],
            }
          : c,
      ),
    );
    if (shownConversation.current === convId) {
      followTail.current = true;
      setDraft("");
    }
    const controller = new AbortController();
    setRequest({ convId, controller });
    sendAdvisorMessage(convId, content, handlerFor(convId, reply.id), controller.signal)
      .then((outcome) => outcome === "unauthorized" && void refresh())
      .catch(() => {
        patch(convId, reply.id, (m) => ({
          ...m,
          error: controller.signal.aborted ? undefined : "网络错误，请稍后再试。",
          content: controller.signal.aborted && !m.content ? "已停止生成" : m.content,
        }));
      })
      .finally(() => {
        asking.current = false;
        setRequest(null);
      });
  }

  const answer = useCallback(async (message: Message, approved: boolean) => {
    if (thinking || asking.current) return;
    asking.current = true;
    if (!(await requireLogin().catch(() => false))) {
      asking.current = false;
      return;
    }
    const convId = active.id;
    patch(convId, message.id, (m) => ({
      ...m,
      confirm: m.confirm && {
        ...m.confirm,
        state: approved ? "approved" : "rejected",
      },
    }));
    const reply: Message = { id: uid(), role: "assistant", content: "" };
    setConversations((prev) =>
      prev.map((c) =>
        c.id === convId ? { ...c, messages: [...c.messages, reply] } : c,
      ),
    );
    setRequest({ convId });
    confirmAdvisorAction(
      convId,
      approved,
      handlerFor(convId, reply.id),
      message.confirm?.id,
    )
      .then((outcome) => {
        if (outcome === "unauthorized") void refresh();
        // Refused before anything ran: the change is still pending, so offer the buttons again.
        if (outcome === "limited" || outcome === "unauthorized")
          patch(convId, message.id, (m) => ({
            ...m,
            confirm: m.confirm && { ...m.confirm, state: "pending" },
          }));
      })
      .catch(() => {
        patch(convId, reply.id, (m) => ({
          ...m,
          error: "网络错误，请稍后再试。",
        }));
      })
      .finally(() => {
        asking.current = false;
        setRequest(null);
      });
  }, [active.id, handlerFor, patch, requireLogin, thinking]);

  function startNew() {
    const conv = newConversation();
    setConversations((prev) => [conv, ...prev]);
    setActiveId(conv.id);
    setDraft("");
  }

  return (
    <main className="page">
      <div className="title-row">
        <div>
          <h1>顾问</h1>
          <p className="lede">
            问某个项目的官方要求、补充你的背景、调整选校组合。改组合之前会先请你确认。
          </p>
        </div>
        <button className="btn btn-secondary" type="button" onClick={startNew}>
          新对话
        </button>
      </div>
      <section className="panel section chat" aria-label="对话">
        <nav className="chat-list" aria-label="对话列表">
          {conversations.map((c) => (
            <button
              key={c.id}
              type="button"
              className="conv"
              aria-current={c.id === active.id ? "true" : undefined}
              onClick={() => setActiveId(c.id)}
            >
              {c.title}
            </button>
          ))}
        </nav>
        <div className="chat-main">
          <div
            ref={body}
            className={`chat-body${active.messages.length === 0 ? " empty-chat" : ""}`}
            data-streaming={request?.convId === active.id || undefined}
            role="log"
            aria-live="polite"
            onScroll={(event) => {
              const element = event.currentTarget;
              scrollPositions.current.set(active.id, element.scrollTop);
              followTail.current = element.scrollHeight - element.clientHeight - element.scrollTop <= 32;
            }}
          >
            {active.messages.length === 0 ? (
              <>
                <h2>可以这样问</h2>
                <div className="grid" style={{ gap: 8 }}>
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      type="button"
                      className="prompt"
                      onClick={() => void send(s)}
                    >
                      {s}
                    </button>
                  ))}
                </div>
                <dl className="rules">
                  <div>
                    <dt>官方要求</dt>
                    <dd>只引用学校官网页面；查不到来源时直接说查不到。</dd>
                  </div>
                  <div>
                    <dt>你的背景</dt>
                    <dd>从对话里读出的分数和院校会更新到「我的背景」。</dd>
                  </div>
                  <div>
                    <dt>选校组合</dt>
                    <dd>
                      加入、移出、设首选、改申请状态，都会先给出改动，等你确认。
                    </dd>
                  </div>
                </dl>
              </>
            ) : (
              active.messages.map((m) =>
                m.role === "user" ? (
                  <div key={m.id} className="msg-user">
                    {m.content}
                  </div>
                ) : (
                  <AssistantMessage
                    key={m.id}
                    message={m}
                    busy={thinking}
                    onAnswer={answer}
                  />
                ),
              )
            )}
            {request?.convId === active.id &&
              active.messages.at(-1)?.content === "" &&
              !active.messages.at(-1)?.confirm &&
              !active.messages.at(-1)?.error && (
                <p className="muted advisor-pending" role="status">
                  {request.controller ? "正在生成回复…" : "正在处理确认…"}
                </p>
              )}
          </div>
          <form
            className="composer"
            onSubmit={(e) => {
              e.preventDefault();
              void send(draft);
            }}
          >
            <label className="sr-only" htmlFor="msg">
              输入问题
            </label>
            <textarea
              id="msg"
              rows={1}
              maxLength={4000}
              value={draft}
              placeholder="输入问题，Enter 发送"
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  void send(draft);
                }
              }}
            />
            {request?.controller && request.convId === active.id ? (
              <button className="btn btn-secondary" type="button" onClick={() => request.controller?.abort()}>
                停止生成
              </button>
            ) : (
              <button className="btn btn-primary" type="submit" disabled={!draft.trim() || thinking}>
                发送
              </button>
            )}
          </form>
        </div>
      </section>
    </main>
  );
}

const AssistantMessage = memo(function AssistantMessage({
  message: m,
  busy,
  onAnswer,
}: {
  message: Message;
  busy: boolean;
  onAnswer: (m: Message, approved: boolean) => void;
}) {
  return (
    <div className="msg-assistant">
      {m.tools && m.tools.length > 0 && (
        <div className="msg-meta">
          {m.tools.map((t, i) => (
            <Pill key={i} kind="outline">
              {TOOL_LABELS[t] ?? t}
            </Pill>
          ))}
        </div>
      )}
      {m.content && <div>{m.content}</div>}
      {m.citations && m.citations.length > 0 && (
        <ol className="citations">
          {m.citations.map((c) => (
            <li key={c.n}>
              <a className="link" href={c.url} target="_blank" rel="noreferrer">
                {c.title}
              </a>
              {verifiedMark(c.status) && (
                <span className="muted"> · {verifiedMark(c.status)}</span>
              )}
            </li>
          ))}
        </ol>
      )}
      {m.confirm && (
        <div className="confirm-box">
          <div className="muted small">需要你确认</div>
          <div style={{ fontWeight: 500, marginTop: 4 }}>
            {m.confirm.summary}
          </div>
          {m.confirm.state === "pending" ? (
            <div className="toolbar" style={{ marginTop: 8 }}>
              <button
                type="button"
                className="btn btn-primary btn-small"
                disabled={busy}
                onClick={() => onAnswer(m, true)}
              >
                确认执行
              </button>
              <button
                type="button"
                className="btn btn-secondary btn-small"
                disabled={busy}
                onClick={() => onAnswer(m, false)}
              >
                取消
              </button>
            </div>
          ) : (
            <div className="muted small" style={{ marginTop: 8 }}>
              {m.confirm.state === "approved" ? "已确认" : "已取消"}
            </div>
          )}
        </div>
      )}
      {m.error && (
        <div className="negative small" role="alert" style={{ marginTop: 6 }}>
          {m.error}
        </div>
      )}
    </div>
  );
});
