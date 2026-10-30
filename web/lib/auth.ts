// The login client (openspec/changes/archive/2026-10-30-account-login). The session lives in an httpOnly cookie the
// browser cannot read, so "who am I" is always a request to `/api/auth/me`.

export interface Account {
  email: string;
  createdAt: string | null;
}

export interface AuthState {
  authEnabled: boolean;
  account: Account | null;
}

export interface VerifyResult {
  account: Account;
  created: boolean;
}

/** A refusal from an auth route, with the fields the dialog shows. */
export class AuthApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly retryAfter: number | null;
  readonly remaining: number | null;

  constructor(status: number, code: string, message: string, retryAfter: number | null = null, remaining: number | null = null) {
    super(message);
    this.status = status;
    this.code = code;
    this.retryAfter = retryAfter;
    this.remaining = remaining;
  }
}

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export function normalizeEmail(raw: string): string {
  return raw.trim().toLowerCase();
}

export function isPlausibleEmail(raw: string): boolean {
  const email = normalizeEmail(raw);
  return email.length <= 254 && EMAIL.test(email);
}

export function isSixDigits(code: string): boolean {
  return /^\d{6}$/.test(code);
}

const FALLBACK: Record<number, string> = {
  401: "需要登录。",
  404: "登录未开启。",
  429: "操作太频繁，请稍后再试。",
  502: "验证码邮件发送失败，请稍后再试。",
};

/** The error a refused response stands for. The server's `detail` object wins when it has one. */
export function authErrorFrom(status: number, body: unknown): AuthApiError {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (detail && typeof detail === "object" && !Array.isArray(detail) && typeof (detail as { code?: unknown }).code === "string") {
    const d = detail as { code: string; message?: string; retryAfter?: number; remaining?: number };
    return new AuthApiError(status, d.code, d.message || FALLBACK[status] || "出错了，请稍后再试。", d.retryAfter ?? null, d.remaining ?? null);
  }
  const text = typeof detail === "string" ? detail : FALLBACK[status] ?? `请求失败（HTTP ${status}）。`;
  return new AuthApiError(status, `http_${status}`, text);
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: init.body ? { "Content-Type": "application/json" } : undefined,
    ...init,
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) throw authErrorFrom(response.status, body);
  return body as T;
}

export function fetchAuthState(): Promise<AuthState> {
  return call<AuthState>("/api/auth/me", { cache: "no-store" });
}

export function requestLoginCode(email: string): Promise<{ sent: boolean; resendAfter: number }> {
  return call("/api/auth/code", { method: "POST", body: JSON.stringify({ email: normalizeEmail(email) }) });
}

export function verifyLoginCode(email: string, code: string): Promise<VerifyResult> {
  return call("/api/auth/verify", { method: "POST", body: JSON.stringify({ email: normalizeEmail(email), code }) });
}

export function logout(): Promise<{ ok: boolean }> {
  return call("/api/auth/logout", { method: "POST" });
}

export function deleteAccount(email: string): Promise<{ deleted: boolean }> {
  return call("/api/auth/account", { method: "DELETE", body: JSON.stringify({ email: normalizeEmail(email) }) });
}

/** Fired on `window` after login, logout or deletion, so every server read on screen reloads. */
export const AUTH_CHANGED = "leapashore:auth-changed";
