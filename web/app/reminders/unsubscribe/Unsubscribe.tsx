"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/components/auth/AuthProvider";
import { SETTINGS_EVENT } from "@/components/shell/UserCenter";
import { unsubscribe } from "@/lib/reminders";

type Status = "working" | "done" | "invalid" | "failed";

const COPY: Record<Status, { title: string; lede: string }> = {
  working: { title: "正在退订", lede: "稍等一下。" },
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
 * Opening the link is the request: the page posts the token once it has loaded and shows what the
 * server answered. Reloading or reusing the link is harmless, since a second use changes nothing.
 */
export function Unsubscribe() {
  const { state, requireLogin } = useAuth();
  const [status, setStatus] = useState<Status>("working");

  const run = useCallback(async () => {
    setStatus("working");
    setStatus(await unsubscribe(new URLSearchParams(window.location.search).get("token") ?? ""));
  }, []);

  useEffect(() => {
    void run();
  }, [run]);

  async function openSettings() {
    if (await requireLogin()) window.dispatchEvent(new CustomEvent(SETTINGS_EVENT, { detail: "reminders" }));
  }

  const signedIn = Boolean(state?.account);
  return (
    <main className="page unsubscribe" aria-live="polite" aria-busy={status === "working"}>
      <h1>{COPY[status].title}</h1>
      <p className="lede">{COPY[status].lede}</p>
      {status === "done" && (
        <p>想恢复的话，{signedIn ? "" : "登录后"}在「设置」的「提醒」里选「开启」。</p>
      )}
      {status === "invalid" && (
        <p>想关掉提醒，可以{signedIn ? "" : "登录后"}在「设置」的「提醒」里选「关闭」。</p>
      )}
      {status !== "working" && (
        <div className="toolbar section">
          {status === "failed" ? (
            <button className="btn btn-primary" onClick={() => void run()}>
              再试一次
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
      )}
    </main>
  );
}
