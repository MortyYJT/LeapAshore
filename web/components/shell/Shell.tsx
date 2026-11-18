"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";
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
  const [collapsed, setCollapsed] = useState(false);
  const [query, setQuery] = useState("");
  const search = useRef<HTMLDialogElement>(null);
  useEffect(() => setOpen(false), [pathname]);
  useEffect(() => {
    try {
      setCollapsed(
        localStorage.getItem("leapashore:sidebar-collapsed") === "true",
      );
    } catch {}
    const keydown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        search.current?.showModal();
      }
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, []);
  function toggleSidebar() {
    setCollapsed((previous) => {
      const next = !previous;
      try {
        localStorage.setItem("leapashore:sidebar-collapsed", String(next));
      } catch {}
      return next;
    });
  }
  function closeSearch() {
    search.current?.close();
    setOpen(false);
  }
  return (
    <div className={`workspace-layout${collapsed ? " sidebar-collapsed" : ""}`}>
      <button
        className="icon-button mobile-sidebar-toggle"
        aria-label="打开导航"
        aria-expanded={open}
        aria-controls="workspace-nav"
        onClick={() => setOpen(!open)}
      >
        <Icon path="M4 6h16M4 12h16M4 18h16" />
      </button>
      <aside
        className={`workspace-sidebar${open ? " is-open" : ""}`}
        id="workspace-nav"
        aria-label="工作空间导航"
      >
        <div className="sidebar-top">
          <Link className="brand" href="/" title="LeapAshore">
            <Mark />
            <span className="sidebar-text">LeapAshore</span>
          </Link>
          <div className="sidebar-tools">
            <button
              className="icon-button sidebar-search"
              aria-label="搜索"
              title="搜索（⌘/Ctrl K）"
              onClick={() => search.current?.showModal()}
            >
              <Icon path="m21 21-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Z" />
            </button>
            <button
              className="icon-button sidebar-collapse"
              aria-label={collapsed ? "展开侧边栏" : "折叠侧边栏"}
              aria-expanded={!collapsed}
              title={collapsed ? "展开侧边栏" : "折叠侧边栏"}
              onClick={toggleSidebar}
            >
              <Icon path="M3 4h18v16H3zM9 4v16" />
            </button>
            <button
              className="icon-button mobile-sidebar-close"
              aria-label="收起导航"
              onClick={() => setOpen(false)}
            >
              <Icon path="m6 6 12 12M6 18 18 6" />
            </button>
          </div>
        </div>
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
                title={label}
                aria-label={label}
                aria-current={current ? "page" : undefined}
              >
                <Icon path={path} />
                <span className="sidebar-text">{label}</span>
              </Link>
            );
          })}
        </nav>
        <div className="sidebar-account">
          <UserCenter />
        </div>
      </aside>
      {open && (
        <button
          className="sidebar-backdrop"
          aria-label="关闭导航"
          onClick={() => setOpen(false)}
        />
      )}
      <div className="workspace-content">{children}</div>
      <dialog
        className="dialog workspace-search-dialog"
        ref={search}
        aria-labelledby="workspace-search-title"
        onClick={(event) => {
          if (event.target === event.currentTarget) closeSearch();
        }}
      >
        <div className="panel-head">
          <h2 id="workspace-search-title">搜索工作空间</h2>
          <button
            className="icon-button"
            aria-label="关闭搜索"
            onClick={closeSearch}
          >
            ×
          </button>
        </div>
        <form
          action="/schools"
          onSubmit={closeSearch}
          className="workspace-search-form"
        >
          <label className="sr-only" htmlFor="workspace-search">
            搜索页面或学校
          </label>
          <input
            id="workspace-search"
            className="input"
            name="q"
            placeholder="搜索页面或学校…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            autoFocus
          />
          <button className="btn btn-primary" type="submit">
            搜索学校
          </button>
        </form>
        <nav className="workspace-search-results" aria-label="搜索结果">
          {[
            ...links,
            ["申请背景与资料", "/me", "M4 4h16v16H4z"],
            ["我的材料", "/materials", "M4 4h16v16H4z"],
          ]
            .filter(([label]) =>
              label.toLowerCase().includes(query.trim().toLowerCase()),
            )
            .map(([label, href, path]) => (
              <Link href={href} key={href} onClick={closeSearch}>
                <Icon path={path} />
                {label}
              </Link>
            ))}
        </nav>
        <p className="muted small workspace-search-hint">
          输入校名后按 Enter，搜索真实学校库。Esc 关闭。
        </p>
      </dialog>
    </div>
  );
}
