"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { useAuth } from "@/components/auth/AuthProvider";
import { Mark } from "./Mark";
import { UserCenter } from "./UserCenter";

const links = [
  ["总览", "/", "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z"],
  [
    "申请路线图",
    "/roadmap",
    "M6 3v12m0 0a3 3 0 1 0 3 3 3 3 0 0 0-3-3Zm3 3c7 0 9-5 9-10m0-6a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z",
  ],
  [
    "我的选校",
    "/portfolio",
    "m2 9 10-5 10 5-10 5-10-5Zm4 2v6c4 3 8 3 12 0v-6M22 9v8",
  ],
  ["学校库", "/schools", "M3 21h18M5 21V5h8v16m0-12h6v12M8 8h2m-2 4h2m-2 4h2"],
  [
    "AI 顾问",
    "/advisor",
    "m12 3 3 6 6 3-6 3-3 6-3-6-6-3 6-3 3-6Zm7-1v4m-2-2h4",
  ],
];
export function Icon({ path }: { path: string }) {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={path} />
    </svg>
  );
}
export function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "/";
  const [open, setOpen] = useState(false);
  const { gated, openLogin } = useAuth();
  useEffect(() => setOpen(false), [pathname]);
  function toggleTheme() {
    const root = document.documentElement;
    const next = root.dataset.appearance === "dark" ? "light" : "dark";
    root.dataset.appearance = next;
    window.dispatchEvent(new CustomEvent("leapashore-theme", { detail: next }));
    try {
      const key = "leapashore:preferences:browser";
      const prefs = JSON.parse(localStorage.getItem(key) || "{}");
      if (gated)
        localStorage.setItem(key, JSON.stringify({ ...prefs, mode: next }));
    } catch {}
  }
  useEffect(() => {
    if (!gated) return;
    try {
      const saved = JSON.parse(
        localStorage.getItem("leapashore:preferences:browser") || "{}",
      ).mode;
      if (saved && saved !== "system")
        document.documentElement.dataset.appearance = saved;
    } catch {}
  }, [gated]);
  return (
    <>
      <header className="workspace-header">
        <Link className="brand" href="/">
          <Mark />
          <span>
            LeapAshore <span className="brand-sub">— 鱼跃彼岸</span>
          </span>
        </Link>
        <div className="workspace-actions">
          <button
            className="icon-button"
            onClick={toggleTheme}
            aria-label="切换明暗主题"
            title="切换明暗主题"
          >
            <Icon path="M20 15A9 9 0 0 1 9 4a9 9 0 1 0 11 11Z" />
          </button>
          {gated ? (
            <button
              className="btn btn-secondary btn-small"
              onClick={() => openLogin(pathname)}
            >
              登录
            </button>
          ) : (
            <UserCenter />
          )}
          <button
            className="icon-button mobile-menu"
            aria-label="打开导航"
            aria-expanded={open}
            aria-controls="workspace-nav"
            onClick={() => setOpen(!open)}
          >
            <Icon path="M4 6h16M4 12h16M4 18h16" />
          </button>
        </div>
      </header>
      <aside
        className={`workspace-sidebar${open ? " is-open" : ""}`}
        id="workspace-nav"
      >
        <div className="sidebar-label">工作空间</div>
        <nav aria-label="主导航">
          {links.map(([label, href, path]) => {
            const current =
              href === "/"
                ? pathname === "/"
                : pathname.startsWith(href) ||
                  (href === "/portfolio" && pathname === "/tiers") ||
                  (href === "/schools" && pathname.startsWith("/programs"));
            return (
              <Link
                href={href}
                key={href}
                aria-current={current ? "page" : undefined}
              >
                <Icon path={path} />
                {label}
              </Link>
            );
          })}
        </nav>
        <Link
          href="/me"
          className="sidebar-settings"
          aria-current={pathname === "/me" ? "page" : undefined}
        >
          <Icon path="M4 7h16M4 17h16M9 4v6m6 4v6" />
          设置
        </Link>
      </aside>
      {open && (
        <button
          className="sidebar-backdrop"
          aria-label="关闭导航"
          onClick={() => setOpen(false)}
        />
      )}
      <div className="workspace-content">{children}</div>
    </>
  );
}
