"use client";

import Link from "next/link";
import { useState } from "react";

import { useAuth } from "@/components/auth/AuthProvider";
import { SETTINGS_EVENT } from "@/components/shell/UserCenter";
import { unsubscribe, unsubscribeToken } from "@/lib/reminders";

type Status = "confirm" | "working" | "done" | "invalid" | "failed";

const COPY: Record<Exclude<Status, "working">, { title: string; lede: string }> = {
  confirm: {
    title: "退订截止提醒",
    lede: "确认后，这个账号不再收到截止日期的提醒邮件。申请记录和其他设置不变。",
  },
  done: {
    title: "已退订截止提醒",
    lede: "这个账号不会再收到截止日期的提醒邮件。申请记录和其他设置没有变。",
  },
  invalid: {
    title: "这个退订链接无效",
    lede: "链接可能没有复制完整，或者账号已经注销。提醒没有被改动。",
  },
  failed: { title: "退订没有完成", lede: "没有连上服务器，提醒还开着。" },
};

/**
 * Opening the link changes nothing: a mail gateway that opens every link in a message, scripts
 * included, must not be able to unsubscribe anyone. The page asks, and the request is sent when the
 * applicant presses the button. Using the link a second time is harmless.
 */
export function Unsubscribe() {
  const { state, requireLogin } = useAuth();
  const [status, setStatus] = useState<Status>("confirm");
  // What the page showed before the request started; it stays up while the request runs.
  const [asked, setAsked] = useState<"confirm" | "failed">("confirm");

  async function run() {
    if (status === "working") return;
    setAsked(status === "failed" ? "failed" : "confirm");
    setStatus("working");
    setStatus(await unsubscribe(unsubscribeToken(window.location.search)));
  }

  async function openSettings() {
    if (await requireLogin()) window.dispatchEvent(new CustomEvent(SETTINGS_EVENT, { detail: "reminders" }));
  }

  const signedIn = Boolean(state?.account);
  const working = status === "working";
  const shown = working ? asked : status;
  return (
    <main className="page unsubscribe" aria-live="polite" aria-busy={working}>
      <h1>{COPY[shown].title}</h1>
      <p className="lede">{COPY[shown].lede}</p>
      {shown === "done" && (
        <p>想恢复的话，{signedIn ? "" : "登录后"}在「设置」的「提醒」里选「开启」。</p>
      )}
      {shown === "invalid" && (
        <p>想关掉提醒，可以{signedIn ? "" : "登录后"}在「设置」的「提醒」里选「关闭」。</p>
      )}
      <div className="toolbar section">
        {shown === "confirm" || shown === "failed" ? (
          <button className="btn btn-primary" disabled={working} onClick={() => void run()}>
            {working ? "正在退订…" : shown === "failed" ? "再试一次" : "确认退订"}
          </button>
        ) : (
          <button className="btn btn-primary" onClick={() => void openSettings()}>
            {signedIn ? "打开提醒设置" : "登录并打开提醒设置"}
          </button>
        )}
        <Link className="btn btn-secondary" href="/" referrerPolicy="no-referrer">
          回到总览
        </Link>
      </div>
    </main>
  );
}
