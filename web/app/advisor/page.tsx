"use client";

import { useEffect, useRef, useState } from "react";

import { useAuth } from "@/components/auth/AuthProvider";
import { Pill, SourceNote } from "@/components/ui";
import { confirmAdvisorAction, sendAdvisorMessage, TOOL_LABELS, type AdvisorEvent, type Citation } from "@/lib/advisor";
import { dataStatusLabel } from "@/lib/taxonomy";

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
  "把我组合里的第一个项目标成已提交",
];

const uid = () => Math.random().toString(36).slice(2, 10);
const newConversation = (): Conversation => ({ id: uid(), title: "新对话", messages: [] });

/**
 * The advisor (spec app-navigation: restyled on the shell, confirm flow unchanged). Replies stream from
 * the agent behind /api/advisor; each reply shows the routed intent, the tools called and the official
 * sources the evidence gate let through, and a portfolio change waits for the applicant's confirm.
 */
export default function AdvisorPage() {
  const [conversations, setConversations] = useState<Conversation[]>(() => [newConversation()]);
  const [activeId, setActiveId] = useState(() => conversations[0].id);
  const [draft, setDraft] = useState("");
  const [thinking, setThinking] = useState(false);
  const body = useRef<HTMLDivElement>(null);
  const { requireLogin, refresh } = useAuth();
  const asking = useRef(false);
  const active = conversations.find((c) => c.id === activeId) ?? conversations[0];

  useEffect(() => {
    if (body.current) body.current.scrollTop = body.current.scrollHeight;
  }, [active.messages.length, thinking]);

  function patch(convId: string, msgId: string, change: (m: Message) => Message) {
    setConversations((prev) =>
      prev.map((c) => (c.id === convId ? { ...c, messages: c.messages.map((m) => (m.id === msgId ? change(m) : m)) } : c)),
    );
  }

  function handlerFor(convId: string, msgId: string) {
    return (e: AdvisorEvent) => {
      if (e.type === "done") {
        setThinking(false);
        return;
      }
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
            return { ...m, confirm: { summary: e.summary, state: "pending" } };
          case "error":
            return { ...m, error: e.message };
        }
      });
    };
  }

  /**
   * Send `text`. In login mode a logged-out visitor gets the login dialog first; the sentence stays in the
   * composer while it is open and is sent as typed once the dialog finishes (openspec account-login D11).
   */
  async function send(text: string) {
    const content = text.trim();
    if (!content || thinking || asking.current) return;
    asking.current = true;
    const allowed = await requireLogin().finally(() => {
      asking.current = false;
    });
    if (!allowed) return;
    const convId = active.id;
    const reply: Message = { id: uid(), role: "assistant", content: "" };
    setConversations((prev) =>
      prev.map((c) =>
        c.id === convId
          ? { ...c, title: c.messages.length === 0 ? content.slice(0, 16) : c.title, messages: [...c.messages, { id: uid(), role: "user", content }, reply] }
          : c,
      ),
    );
    setDraft("");
    setThinking(true);
    sendAdvisorMessage(convId, content, handlerFor(convId, reply.id))
      .then((outcome) => outcome === "unauthorized" && void refresh())
      .catch(() => {
      patch(convId, reply.id, (m) => ({ ...m, error: "网络错误，请稍后再试。" }));
      setThinking(false);
    });
  }

  async function answer(message: Message, approved: boolean) {
    if (thinking) return;
    if (!(await requireLogin())) return;
    const convId = active.id;
    patch(convId, message.id, (m) => ({ ...m, confirm: m.confirm && { ...m.confirm, state: approved ? "approved" : "rejected" } }));
    const reply: Message = { id: uid(), role: "assistant", content: "" };
    setConversations((prev) => prev.map((c) => (c.id === convId ? { ...c, messages: [...c.messages, reply] } : c)));
    setThinking(true);
    confirmAdvisorAction(convId, approved, handlerFor(convId, reply.id))
      .then((outcome) => outcome === "unauthorized" && void refresh())
      .catch(() => {
      patch(convId, reply.id, (m) => ({ ...m, error: "网络错误，请稍后再试。" }));
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
    <>
      <main className="page">
        <div className="title-row">
          <div>
            <h1>顾问</h1>
            <p className="lede">问某个项目的官方要求、补充你的背景、调整选校组合。改组合之前会先请你确认。</p>
          </div>
          <button className="btn btn-secondary" type="button" onClick={startNew}>
            新对话
          </button>
        </div>
        <section className="panel section chat" aria-label="对话">
          <nav className="chat-list" aria-label="对话列表">
            {conversations.map((c) => (
              <button key={c.id} type="button" className="conv" aria-current={c.id === active.id ? "true" : undefined} onClick={() => setActiveId(c.id)}>
                {c.title}
              </button>
            ))}
          </nav>
          <div className="chat-main">
            <div ref={body} className={`chat-body${active.messages.length === 0 ? " empty-chat" : ""}`} aria-live="polite">
              {active.messages.length === 0 ? (
                <>
                  <h2>可以这样问</h2>
                  <div className="grid" style={{ gap: 8 }}>
                    {SUGGESTIONS.map((s) => (
                      <button key={s} type="button" className="prompt" onClick={() => void send(s)}>
                        {s}
                      </button>
                    ))}
                  </div>
                  <dl className="rules">
                    <div><dt>官方要求</dt><dd>只引用学校官网页面，并标明是否核对过；查不到来源时直接说查不到。</dd></div>
                    <div><dt>你的背景</dt><dd>从对话里读出的分数和院校会更新到「我的背景」。</dd></div>
                    <div><dt>选校组合</dt><dd>加入、移出、设首选、改申请状态，都会先给出改动，等你确认。</dd></div>
                  </dl>
                </>
              ) : (
                active.messages.map((m) =>
                  m.role === "user" ? (
                    <div key={m.id} className="msg-user">{m.content}</div>
                  ) : (
                    <AssistantMessage key={m.id} message={m} busy={thinking} onAnswer={(m, ok) => void answer(m, ok)} />
                  ),
                )
              )}
              {thinking && active.messages.at(-1)?.content === "" && !active.messages.at(-1)?.confirm && (
                <p className="muted" role="status">正在整理…</p>
              )}
            </div>
            <form
              className="composer"
              onSubmit={(e) => {
                e.preventDefault();
                void send(draft);
              }}
            >
              <label className="sr-only" htmlFor="msg">输入问题</label>
              <textarea
                id="msg"
                rows={1}
                value={draft}
                placeholder="输入问题，Enter 发送，Shift+Enter 换行"
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void send(draft);
                  }
                }}
              />
              <button className="btn btn-primary" type="submit" disabled={!draft.trim() || thinking}>
                发送
              </button>
            </form>
          </div>
        </section>
      </main>
      <SourceNote>回答只引用已收录的官方来源；标“未核对”或“自动标注”的数据都还没有人工核对，请以学校官网为准。对话保存在服务器内存里，服务重启后会清空。</SourceNote>
    </>
  );
}

function AssistantMessage({ message: m, busy, onAnswer }: { message: Message; busy: boolean; onAnswer: (m: Message, approved: boolean) => void }) {
  return (
    <div className="msg-assistant">
      {(m.intent || m.gate || (m.tools && m.tools.length > 0)) && (
        <div className="msg-meta">
          {m.intent && <Pill>意图：{m.intent}</Pill>}
          {m.gate && <Pill kind={m.gate === "pass" ? "tier" : "outline"}>证据门禁：{m.gate === "pass" ? "通过" : "拒答"}</Pill>}
          {m.tools?.map((t, i) => (
            <Pill key={i} kind="outline">{TOOL_LABELS[t] ?? t}</Pill>
          ))}
        </div>
      )}
      {m.content && <div>{m.content}</div>}
      {m.citations && m.citations.length > 0 && (
        <ol className="citations">
          {m.citations.map((c) => (
            <li key={c.n}>
              <a href={c.url} target="_blank" rel="noreferrer">{c.title}</a> <span className="muted">· {dataStatusLabel(c.status)}</span>
            </li>
          ))}
        </ol>
      )}
      {m.confirm && (
        <div className="confirm-box">
          <div className="muted small">需要你确认</div>
          <div style={{ fontWeight: 500, marginTop: 4 }}>{m.confirm.summary}</div>
          {m.confirm.state === "pending" ? (
            <div className="toolbar" style={{ marginTop: 8 }}>
              <button type="button" className="btn btn-primary btn-small" disabled={busy} onClick={() => onAnswer(m, true)}>确认执行</button>
              <button type="button" className="btn btn-secondary btn-small" disabled={busy} onClick={() => onAnswer(m, false)}>取消</button>
            </div>
          ) : (
            <div className="muted small" style={{ marginTop: 8 }}>{m.confirm.state === "approved" ? "已确认" : "已取消"}</div>
          )}
        </div>
      )}
      {m.error && <div className="negative small" role="alert" style={{ marginTop: 6 }}>{m.error}</div>}
    </div>
  );
}
