"use client";

import Link from "next/link";
import { useEffect, useLayoutEffect, useMemo, useRef } from "react";

import { useApplicationRecords } from "@/components/shell/ApplicationRecords";
import { Icon } from "@/components/shell/Icon";
import { starterQuestions } from "@/lib/advisor-run";
import { beijingToday } from "@/lib/deadlines";
import { overviewOf } from "@/lib/overview";

import { useAdvisorChat, useAdvisorDock } from "./AdvisorProvider";
import { TurnView, type Line } from "./Run";

const HOW: [string, string][] = [
  ["读你的申请", "项目、轮次、截止日期和状态"],
  ["查官方要求", "回答附上来源页面，查不到就直说"],
  ["提议修改", "改选校组合之前，先把改动列给你看"],
  ["写入", "选校组合等你确认才改；你说的成绩和学校会直接记进背景"],
];

/**
 * The advisor: the conversation, and the composer under it. The same component is the dock beside the
 * workspace and the full page at /advisor; `variant` only changes the heading and the tools beside it.
 */
export function Advisor({ variant }: { variant: "dock" | "page" }) {
  const chat = useAdvisorChat();
  const dock = useAdvisorDock();
  const records = useApplicationRecords();
  const thread = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const followTail = useRef(true);
  const running = chat.runningTurn !== null;

  const overview = useMemo(() => (records.data ? overviewOf(records.data, beijingToday()) : null), [records.data]);
  const starters = useMemo(() => starterQuestions(overview), [overview]);
  const lines = useMemo(() => {
    const map = new Map<string, Line>();
    for (const row of overview?.rows ?? []) {
      if (row.record.programId) map.set(row.record.programId, { colour: row.line, code: row.code });
    }
    return map;
  }, [overview]);

  // Stay at the newest line while the reader is there; leave the scroll alone once they move up.
  useLayoutEffect(() => {
    const element = thread.current;
    if (element && followTail.current) element.scrollTop = element.scrollHeight;
  }, [chat.turns]);

  useEffect(() => {
    if (dock.focusRequest) input.current?.focus();
  }, [dock.focusRequest]);

  const Heading = variant === "page" ? "h1" : "h2";
  const submit = () => {
    followTail.current = true;
    void chat.send(chat.draft);
  };

  return (
    <section className={`advisor advisor-${variant}`} aria-labelledby={`advisor-title-${variant}`}>
      <header className="advisor-head">
        <Heading id={`advisor-title-${variant}`}>顾问</Heading>
        <div className="advisor-tools">
          <button type="button" className="btn-quiet" onClick={chat.reset} disabled={!chat.turns.length && !chat.draft}>
            <Icon name="plus" />
            新对话
          </button>
          {variant === "dock" ? (
            <>
              <Link className="icon-button" href="/advisor" aria-label="在整页打开顾问" title="在整页打开">
                <Icon name="expand" />
              </Link>
              <button
                type="button"
                className="icon-button"
                aria-label="收起顾问"
                title="收起（⌘/Ctrl J）"
                onClick={() => {
                  dock.setOpen(false);
                  document.getElementById("advisor-toggle")?.focus();
                }}
              >
                <Icon name="close" />
              </button>
            </>
          ) : (
            <Link
              className="icon-button advisor-redock"
              href="/"
              aria-label="回到总览，把顾问停在右侧"
              title="停在右侧"
              onClick={() => dock.setOpen(true)}
            >
              <Icon name="dock" />
            </Link>
          )}
        </div>
      </header>

      <div
        className="thread"
        ref={thread}
        role="log"
        aria-live="polite"
        aria-busy={running}
        tabIndex={chat.turns.length ? 0 : undefined}
        aria-label="对话"
        onScroll={(event) => {
          const element = event.currentTarget;
          followTail.current = element.scrollHeight - element.clientHeight - element.scrollTop <= 48;
        }}
      >
        <div className="thread-inner">
          {chat.turns.length === 0 ? (
            <div className="hello">
              <h3>要查什么，或者要改什么？</h3>
              <ol className="run how">
                {HOW.map(([name, what]) => (
                  <li className="step" key={name}>
                    <span className="dot" aria-hidden="true" />
                    <b>{name}</b>
                    <span>{what}</span>
                  </li>
                ))}
              </ol>
              <div className="asks">
                {starters.map((question) => (
                  <button key={question} type="button" disabled={running} onClick={() => void chat.send(question)}>
                    <span>{question}</span>
                    <Icon name="arrow" />
                  </button>
                ))}
              </div>
            </div>
          ) : (
            chat.turns.map((turn, index) => (
              <TurnView
                key={turn.id}
                turn={turn}
                running={chat.runningTurn === turn.id}
                busy={running}
                last={index === chat.turns.length - 1}
                lines={lines}
                onAnswer={chat.answer}
                onRetry={chat.retry}
              />
            ))
          )}
        </div>
      </div>

      <form
        className="advisor-composer"
        onSubmit={(event) => {
          event.preventDefault();
          if (running) chat.stop();
          else submit();
        }}
      >
        <div className="composer-field">
          <textarea
            id="advisor-input"
            ref={input}
            rows={1}
            maxLength={2000}
            value={chat.draft}
            placeholder="问问题，或者让顾问改选校组合"
            aria-label="给顾问的消息"
            onChange={(event) => chat.setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                if (!running) submit();
              }
            }}
          />
          {running ? (
            <button type="submit" className="send" aria-label="停止" title="停止（Esc）">
              <Icon name="stop" />
            </button>
          ) : (
            <button type="submit" className="send" aria-label="发送" title="发送（Enter）" disabled={!chat.draft.trim()}>
              <Icon name="send" />
            </button>
          )}
        </div>
        <p className="composer-hint">
          <span>只引用已收录的官方页面，查不到会直说。</span>
          <kbd>{running ? "Esc 停止" : "Enter 发送"}</kbd>
        </p>
      </form>
    </section>
  );
}
