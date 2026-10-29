"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { ProfileForm } from "@/components/profile/ProfileForm";
import { AuthApiError, isPlausibleEmail, isSixDigits, normalizeEmail, requestLoginCode, verifyLoginCode } from "@/lib/auth";
import { hasBasics } from "@/lib/assess";
import { loadProfile } from "@/lib/hooks/useProfile";
import type { Profile } from "@/lib/types";

type Step = { kind: "email" } | { kind: "code" } | { kind: "basics"; profile: Profile };

const RESEND_SECONDS = 60;

/**
 * Email → 6-digit code → (first registration only) the four basics. A native modal `<dialog>`, so focus is
 * trapped and Escape cancels. `onDone` runs once the visitor is logged in and past the info step.
 */
export function LoginDialog({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [step, setStep] = useState<Step>({ kind: "email" });
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [wait, setWait] = useState(0);
  const codeInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (dialog && !dialog.open) dialog.showModal();
    return () => dialog?.close();
  }, []);

  useEffect(() => {
    if (wait <= 0) return;
    const timer = setTimeout(() => setWait((w) => w - 1), 1000);
    return () => clearTimeout(timer);
  }, [wait]);

  useEffect(() => {
    if (step.kind === "code") codeInput.current?.focus();
  }, [step.kind]);

  function explain(e: unknown): string {
    if (e instanceof AuthApiError) {
      if (e.retryAfter) setWait(e.retryAfter);
      return e.message;
    }
    return "网络出错，请稍后再试。";
  }

  async function send(event?: FormEvent) {
    event?.preventDefault();
    if (!isPlausibleEmail(email)) {
      setError("请填写正确的邮箱地址。");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const sent = await requestLoginCode(email);
      setWait(sent.resendAfter ?? RESEND_SECONDS);
      setStep({ kind: "code" });
    } catch (e) {
      const message = explain(e);
      // A code sent moments ago is still valid: let the visitor type it.
      if (e instanceof AuthApiError && e.code === "too_soon") setStep({ kind: "code" });
      setError(message);
    } finally {
      setBusy(false);
    }
  }

  async function verify(event: FormEvent) {
    event.preventDefault();
    if (!isSixDigits(code)) {
      setError("验证码是 6 位数字。");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await verifyLoginCode(email, code);
      if (result.created) {
        const profile = await loadProfile().catch(() => null);
        if (profile && !hasBasics(profile)) {
          setStep({ kind: "basics", profile });
          return;
        }
      }
      onDone();
    } catch (e) {
      setError(explain(e));
      if (e instanceof AuthApiError && (e.code === "too_many_attempts" || e.code === "code_expired")) setCode("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <dialog
      ref={ref}
      className="dialog"
      aria-labelledby="login-title"
      onCancel={(e) => {
        e.preventDefault();
        onCancel();
      }}
    >
      <div className="dialog-head">
        <h2 id="login-title">{step.kind === "basics" ? "补充四项信息" : "登录"}</h2>
        <button type="button" className="btn btn-text btn-small" aria-label="关闭" onClick={step.kind === "basics" ? onDone : onCancel}>
          关闭
        </button>
      </div>

      {step.kind === "email" && (
        <form className="dialog-body" noValidate onSubmit={send}>
          <p className="muted" style={{ marginTop: 0 }}>输入邮箱，我们会发一个 6 位验证码。第一次登录会自动注册。</p>
          <label htmlFor="login-email" className="label">邮箱</label>
          <input
            id="login-email"
            className="input"
            type="email"
            autoComplete="email"
            inputMode="email"
            autoFocus
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? "login-error" : undefined}
          />
          {error && <p className="negative small" id="login-error" role="alert">{error}</p>}
          <button className="btn btn-primary dialog-submit" type="submit" disabled={busy}>
            {busy ? "正在发送…" : "发送验证码"}
          </button>
          <p className="muted small" style={{ marginBottom: 0 }}>
            登录即表示你已阅读<Link href="/privacy" target="_blank">《隐私政策》</Link>。
          </p>
        </form>
      )}

      {step.kind === "code" && (
        <form className="dialog-body" noValidate onSubmit={verify}>
          <p className="muted" style={{ marginTop: 0 }}>
            验证码已发到 <b className="ink">{normalizeEmail(email)}</b>，10 分钟内有效。
          </p>
          <label htmlFor="login-code" className="label">验证码</label>
          <input
            id="login-code"
            ref={codeInput}
            className="input num code-input"
            autoComplete="one-time-code"
            inputMode="numeric"
            maxLength={6}
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? "login-error" : undefined}
          />
          {error && <p className="negative small" id="login-error" role="alert">{error}</p>}
          <button className="btn btn-primary dialog-submit" type="submit" disabled={busy}>
            {busy ? "正在登录…" : "登录"}
          </button>
          <div className="toolbar" style={{ justifyContent: "space-between" }}>
            <button
              type="button"
              className="btn btn-text btn-small"
              onClick={() => {
                setStep({ kind: "email" });
                setCode("");
                setError(null);
              }}
            >
              换个邮箱
            </button>
            <button type="button" className="btn btn-text btn-small" disabled={busy || wait > 0} onClick={() => void send()}>
              {wait > 0 ? `${wait} 秒后可重发` : "重新发送"}
            </button>
          </div>
        </form>
      )}

      {step.kind === "basics" && (
        <div className="dialog-body">
          <p className="muted" style={{ marginTop: 0 }}>
            注册好了。分档只看这四项：本科院校、均分、申请方向、英语成绩。可以先跳过，之后在分档页或「我的」里补。
          </p>
          <ProfileForm initial={step.profile} mode="basics" idPrefix="basics" onSaved={onDone} onSkip={onDone} submitLabel="保存，继续" />
        </div>
      )}
    </dialog>
  );
}
