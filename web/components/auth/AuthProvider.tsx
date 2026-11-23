"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { LoadingPanel } from "@/components/ui";
import { AUTH_CHANGED, fetchAuthState, logout, type AuthState } from "@/lib/auth";
import { forgetModelKey } from "@/lib/model-key";
import { clearDraft } from "@/lib/portfolio-draft";
import { SESSION_ENDED } from "@/lib/hooks/resource";
import { clearResourceCache } from "@/lib/resource-cache";

import { LoginDialog } from "./LoginDialog";
import { useNavigation } from "@/components/shell/Navigation";

interface AuthContext {
  /** Null until `/api/auth/me` has answered (or when it could not be read). */
  state: AuthState | null;
  ready: boolean;
  /** Login mode is on and nobody is logged in: private data and writes are behind the dialog. */
  gated: boolean;
  /**
   * Resolve true once the caller may act: at once with login mode off or a session present, otherwise after
   * the dialog has logged in (and, on a first registration, the info step has been saved or skipped). False
   * when the visitor closes the dialog. The caller then finishes what it was doing with the values it holds,
   * which is how an advisor message typed before logging in is still sent afterwards.
   */
  requireLogin: () => Promise<boolean>;
  /** The header's 登录: after the dialog the visitor lands on `landing`. */
  openLogin: (landing?: string) => void;
  /** Re-read the session, e.g. after a 401 says it expired. */
  refresh: () => Promise<AuthState | null>;
  signOut: () => Promise<void>;
}

const Ctx = createContext<AuthContext | null>(null);

export function useAuth(): AuthContext {
  const value = useContext(Ctx);
  if (!value) throw new Error("useAuth outside AuthProvider");
  return value;
}

function announce() {
  // What was read for whoever was here before is dropped before anything reads for the new session.
  clearResourceCache();
  window.dispatchEvent(new Event(AUTH_CHANGED));
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const { push } = useNavigation();
  const router = useRouter();
  const [state, setState] = useState<AuthState | null>(null);
  const [ready, setReady] = useState(false);
  const [dialog, setDialog] = useState<{ landing: string | null } | null>(null);
  const stateRef = useRef<AuthState | null>(null);
  const waiting = useRef<((ok: boolean) => void) | null>(null);

  const refresh = useCallback(async () => {
    try {
      const next = await fetchAuthState();
      stateRef.current = next;
      setState(next);
      return next;
    } catch {
      return stateRef.current;
    } finally {
      setReady(true);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // A read of the account's data was refused as signed out (lib/hooks/useResource.ts): read the
  // session again. If it is over, the effect below drops what was kept for the account.
  useEffect(() => {
    const ended = () => void refresh();
    window.addEventListener(SESSION_ENDED, ended);
    return () => window.removeEventListener(SESSION_ENDED, ended);
  }, [refresh]);

  // The data kept for the visit (lib/resource-cache.ts) belongs to one account. Whenever the session
  // is read and names a different account than the last time, or none (it expired, or ended in
  // another tab), everything kept is dropped, so nothing of one account can be drawn for another or
  // beside the signed-out demo. Signing in through the dialog also clears it (`announce`), and signing
  // out is a full page load.
  const account = !ready ? undefined : state?.account ? (state.account.email ?? "signed-in") : null;
  const lastAccount = useRef<string | null | undefined>(undefined);
  useEffect(() => {
    if (account === undefined) return;
    if (lastAccount.current !== undefined && lastAccount.current !== account) {
      clearResourceCache();
      // The server-rendered routes the router keeps for return visits (next.config.ts, staleTimes)
      // include the admin's, which is a 404 or a page depending on who asks.
      router.refresh();
    }
    lastAccount.current = account;
  }, [account, router]);

  // A browser that is signed out keeps no model key: the session may have expired, or ended in
  // another tab, without `signOut` running here.
  useEffect(() => {
    if (ready && state?.authEnabled && !state.account) forgetModelKey();
  }, [ready, state]);

  const requireLogin = useCallback(async () => {
    const current = stateRef.current ?? (await refresh());
    // An unreadable auth state lets the action through; the server still refuses it without a session.
    if (!current || !current.authEnabled || current.account) return true;
    waiting.current?.(false);
    return new Promise<boolean>((resolve) => {
      waiting.current = resolve;
      setDialog({ landing: null });
    });
  }, [refresh]);

  const openLogin = useCallback((landing = "/tiers") => setDialog({ landing }), []);

  const finish = useCallback(
    async (ok: boolean) => {
      const landing = dialog?.landing ?? null;
      setDialog(null);
      if (ok) {
        await refresh();
        announce();
      }
      const resolve = waiting.current;
      waiting.current = null;
      resolve?.(ok);
      if (ok && landing) push(landing);
    },
    [dialog, refresh, push],
  );

  const signOut = useCallback(async () => {
    await logout().catch(() => undefined);
    // The model key the applicant stored in this browser goes with the session.
    forgetModelKey();
    // An unsaved portfolio draft belongs to the account that made it, not to whoever logs in next.
    clearDraft(sessionStorage);
    // A full load, not `router.push`: the client router may hold a prefetched `/` that the proxy answered
    // with a redirect to /roadmap while the session was alive.
    window.location.assign("/");
  }, []);

  const value = useMemo<AuthContext>(
    () => ({
      state,
      ready,
      gated: Boolean(state?.authEnabled && !state.account),
      requireLogin,
      openLogin,
      refresh,
      signOut,
    }),
    [state, ready, requireLogin, openLogin, refresh, signOut],
  );

  return (
    <Ctx.Provider value={value}>
      {children}
      {dialog && <LoginDialog onDone={() => void finish(true)} onCancel={() => void finish(false)} />}
    </Ctx.Provider>
  );
}

/**
 * Render `children` only for someone who may see private data. In login mode a logged-out visitor sees
 * `fallback` (by default a short 登录后查看 panel); the children mount after login, so their reads start
 * with the session instead of a 401. Until the session is known it shows `pending`, which a page that
 * wraps its whole body passes with its own title, so the page keeps its frame while it waits.
 */
export function RequireAccount({
  children,
  what,
  fallback,
  pending,
}: {
  children: ReactNode;
  what: string;
  fallback?: ReactNode;
  pending?: ReactNode;
}) {
  const { ready, gated } = useAuth();
  if (!ready) return <>{pending ?? <LoadingPanel what={what} />}</>;
  if (gated) return <>{fallback ?? <LoginPrompt what={what} />}</>;
  return <>{children}</>;
}

export function LoginPrompt({ what }: { what: string }) {
  const { requireLogin } = useAuth();
  return (
    <section className="panel panel-pad section login-prompt" aria-label="需要登录">
      <h2 style={{ marginBottom: 6 }}>登录后查看{what}</h2>
      <p className="muted" style={{ margin: "0 0 16px" }}>
        用邮箱收一个 6 位验证码就能登录，第一次登录会自动注册。学校库和路线图示例不用登录也能看。
      </p>
      <div className="toolbar">
        <button type="button" className="btn btn-primary" onClick={() => void requireLogin()}>
          登录
        </button>
        <Link className="btn btn-text" href="/privacy">
          隐私政策
        </Link>
      </div>
    </section>
  );
}
