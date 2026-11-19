"use client";
import Link, { useLinkStatus } from "next/link";
import type {} from "react/canary";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState, ViewTransition, type ReactNode } from "react";

import { useAuth } from "@/components/auth/AuthProvider";
import { beijingToday } from "@/lib/deadlines";
import { overviewOf, type OverviewRow } from "@/lib/overview";

import { useApplicationRecords } from "./ApplicationRecords";
import { Icon, type IconName } from "./Icon";
import { Mark } from "./Mark";
import { UserCenter } from "./UserCenter";

/** `short` is the label under the icon in the phone's tab bar. */
const links: { label: string; short: string; href: string; icon: IconName }[] = [
  { label: "总览", short: "总览", href: "/", icon: "overview" },
  { label: "申请路线图", short: "路线图", href: "/roadmap", icon: "roadmap" },
  { label: "我的申请", short: "申请", href: "/applications", icon: "applications" },
  { label: "学校库", short: "学校库", href: "/schools", icon: "schools" },
  { label: "AI 顾问", short: "顾问", href: "/advisor", icon: "advisor" },
];

const searchable: { label: string; href: string; icon: IconName }[] = [
  ...links,
  { label: "申请背景与资料", href: "/me", icon: "profile" },
  { label: "我的材料", href: "/materials", icon: "materials" },
];

/**
 * The frame every route sits in. From 901px it is a rail on the left: navigation, the applicant's
 * applications with the days each has left, the sync state, the account and the theme. At 900px and
 * below the same elements become a top bar and a bottom tab bar (app/shell.css); nothing is rendered twice.
 */
export function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "/";
  const [collapsed, setCollapsed] = useState(false);
  const [sidebarInteracted, setSidebarInteracted] = useState(false);
  const [query, setQuery] = useState("");
  const search = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    try {
      setCollapsed(localStorage.getItem("leapashore:sidebar-collapsed") === "true");
    } catch {}
    const keydown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        search.current?.showModal();
      }
    };
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, []);

  function toggleSidebar() {
    setSidebarInteracted(true);
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
  }

  return (
    <div className={`shell${collapsed ? " sidebar-collapsed" : ""}`} data-sidebar-interacted={sidebarInteracted || undefined}>
      <a className="skip" href="#main">
        跳到主要内容
      </a>
      <aside className="rail" id="workspace-nav" aria-label="工作空间导航">
        <div className="rail-top">
          <div className="sidebar-brand">
            <Link className="brand" href="/" title="鱼跃彼岸 LeapAshore">
              <Mark />
              <span className="brand-name">
                <b>鱼跃彼岸</b>
                <span>LeapAshore</span>
              </span>
            </Link>
            <button
              className="rail-button sidebar-brand-expand"
              aria-label="展开侧边栏"
              title="展开侧边栏"
              aria-expanded={false}
              onClick={toggleSidebar}
            >
              <span className="rail-mark">
                <Mark />
              </span>
              <span className="rail-expand">
                <Icon name="sidebar" />
              </span>
            </button>
          </div>
          <div className="sidebar-tools">
            <button className="rail-button sidebar-search" aria-label="搜索" title="搜索（⌘/Ctrl K）" onClick={() => search.current?.showModal()}>
              <Icon name="search" />
            </button>
            <button className="rail-button sidebar-collapse" aria-label="折叠侧边栏" aria-expanded={!collapsed} title="折叠侧边栏" onClick={toggleSidebar}>
              <Icon name="sidebar" />
            </button>
          </div>
        </div>
        <div className="rail-scroll">
          <nav className="rail-nav" aria-label="主导航">
            {links.map(({ label, short, href, icon }) => {
              const current =
                href === "/"
                  ? pathname === "/"
                  : pathname.startsWith(href) ||
                    (href === "/applications" && ["/portfolio", "/tiers"].includes(pathname)) ||
                    (href === "/schools" && pathname.startsWith("/programs"));
              return (
                <Link
                  href={href}
                  key={href}
                  title={label}
                  aria-label={label}
                  aria-current={current ? "page" : undefined}
                  onNavigate={() => {
                    // Release an in-flight fade when the user chooses another route.
                    for (const animation of document.getAnimations()) {
                      if (animation instanceof CSSAnimation && ["route-in", "route-out"].includes(animation.animationName)) {
                        animation.finish();
                      }
                    }
                  }}
                >
                  <Icon name={icon} />
                  <span className="nav-label nav-long">{label}</span>
                  <span className="nav-label nav-short">{short}</span>
                  <NavigationStatus />
                </Link>
              );
            })}
          </nav>
          <RailLegend />
        </div>
        <div className="rail-foot">
          <SyncStatus />
          <div className="rail-me">
            <UserCenter />
            <ThemeToggle />
          </div>
        </div>
      </aside>
      <ViewTransition default="none" update="workspace-route">
        <div className="workspace-content" id="main" tabIndex={-1}>
          {children}
        </div>
      </ViewTransition>
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
          <button className="icon-button" aria-label="关闭搜索" onClick={closeSearch}>
            <Icon name="close" />
          </button>
        </div>
        <form action="/schools" onSubmit={closeSearch} className="workspace-search-form">
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
          {searchable
            .filter(({ label }) => label.toLowerCase().includes(query.trim().toLowerCase()))
            .map(({ label, href, icon }) => (
              <Link href={href} key={href} onClick={closeSearch}>
                <Icon name={icon} />
                {label}
              </Link>
            ))}
        </nav>
        <p className="muted small workspace-search-hint">输入校名后按 Enter，在学校库里搜索。按 Esc 关闭。</p>
      </dialog>
    </div>
  );
}

function NavigationStatus() {
  const { pending } = useLinkStatus();
  return <span className="sidebar-navigation-pending" data-pending={pending || undefined} aria-hidden="true" />;
}

/** What the rail prints at the right of an application: the days left, or why there is no count. */
function Remaining({ row }: { row: OverviewRow }) {
  if (row.sent) return <span className="left">已提交</span>;
  if (row.days === null) return <span className="left">待确认</span>;
  if (row.days < 0) return <span className="left">已截止</span>;
  if (row.days === 0) return <span className={`left${row.soon ? " is-soon" : ""}`}>今天</span>;
  return (
    <span className={`left${row.soon ? " is-soon" : ""}`}>
      <b>{row.days}</b>天
    </span>
  );
}

/**
 * The applicant's applications, one per line colour. Picking one makes the other lines step back on
 * the overview; picking it again releases it. From another route the pick also opens the overview,
 * which is where the lines are drawn.
 */
function RailLegend() {
  const records = useApplicationRecords();
  const pathname = usePathname() ?? "/";
  const router = useRouter();
  const rows = useMemo(() => (records.data ? overviewOf(records.data, beijingToday()).rows : []), [records.data]);
  if (!rows.length) return null;
  return (
    <section className="rail-legend" aria-labelledby="rail-legend-title">
      <h2 className="rail-legend-title" id="rail-legend-title">
        我的申请
      </h2>
      <ul>
        {rows.map((row) => {
          const picked = records.selected === row.record.id;
          return (
            <li key={row.record.id}>
              <button
                type="button"
                className={`line-${row.line}${records.selected && !picked ? " is-dimmed" : ""}`}
                title={`${row.record.school} · ${row.record.name}`}
                aria-pressed={picked}
                onClick={() => {
                  records.select(picked ? null : row.record.id);
                  if (!picked && pathname !== "/") router.push("/");
                }}
              >
                <span className="bullet">{row.code}</span>
                <span className="name">{row.record.school}</span>
                <Remaining row={row} />
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

const CLOCK = new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });

/**
 * Whether what is on screen is the account's data. It states only what the app knows: the time of the
 * last read, a failed read, or that nobody is signed in. For a visitor it is the sign-in entry.
 */
function SyncStatus() {
  const { state, ready, gated, openLogin } = useAuth();
  const records = useApplicationRecords();
  if (!ready) return <p className="rail-sync" aria-hidden="true" />;
  if (gated) {
    return (
      <button type="button" className="rail-sync" title="登录后同步到账号" onClick={() => openLogin(window.location.pathname)}>
        <Icon name="unsynced" />
        <span>登录后同步到账号</span>
      </button>
    );
  }
  if (!state?.account) {
    return (
      <p className="rail-sync" title="未开启账号，数据只跟着这个浏览器">
        <Icon name="unsynced" />
        <span>未开启账号同步</span>
      </p>
    );
  }
  if (records.error) {
    return (
      <button type="button" className="rail-sync is-failed" title="同步失败，点击重试" onClick={records.reload}>
        <Icon name="unsynced" />
        <span>同步失败，点击重试</span>
      </button>
    );
  }
  const label = records.syncedAt && !records.loading ? `已同步 ${CLOCK.format(records.syncedAt)}` : "正在同步…";
  return (
    <button type="button" className="rail-sync" title={`${label}，点击重新同步`} aria-label={`${label}，点击重新同步`} onClick={records.reload}>
      <Icon name={records.syncedAt ? "synced" : "unsynced"} />
      <span className="num">{label}</span>
    </button>
  );
}

/** A quick switch between light and dark. The full setting, with "follow the system", is under 设置 → 外观. */
function ThemeToggle() {
  return (
    <button
      type="button"
      className="rail-button theme-toggle"
      aria-label="切换深色或浅色"
      title="切换深色或浅色"
      onClick={() => {
        const next = document.documentElement.dataset.appearance === "dark" ? "light" : "dark";
        window.dispatchEvent(new CustomEvent("leapashore-theme", { detail: next }));
      }}
    >
      <Icon name="theme" />
    </button>
  );
}
