"use client";
import Link from "next/link";
import { Fragment, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";

import { useAdvisorDock } from "@/components/advisor/AdvisorProvider";
import { Dock } from "@/components/advisor/Dock";
import { useAuth } from "@/components/auth/AuthProvider";
import { beijingToday } from "@/lib/deadlines";
import { isNavCurrent, routeShape } from "@/lib/navigation";
import { overviewOf, type OverviewRow } from "@/lib/overview";

import { AddProgramToast } from "./AddProgram";
import { useApplicationRecords } from "./ApplicationRecords";
import { Icon, type IconName } from "./Icon";
import { Mark } from "./Mark";
import { useContentMotion, useRailIndicator } from "./Motion";
import { useNavigation } from "./Navigation";
import { RouteSkeleton } from "./RouteSkeleton";
import { UserCenter } from "./UserCenter";

/**
 * `short` is the label under the icon in the phone's tab bar. A `railOnly` entry is in the rail and
 * not among the phone's five tabs; on a phone it is reached from the overview, 我的申请 and the menu.
 */
const links: { label: string; short: string; href: string; icon: IconName; railOnly?: boolean }[] = [
  { label: "总览", short: "总览", href: "/", icon: "overview" },
  { label: "申请路线图", short: "路线图", href: "/roadmap", icon: "roadmap" },
  { label: "我的申请", short: "申请", href: "/applications", icon: "applications" },
  { label: "材料", short: "材料", href: "/materials", icon: "materials", railOnly: true },
  { label: "学校库", short: "学校库", href: "/schools", icon: "schools" },
  { label: "AI 顾问", short: "顾问", href: "/advisor", icon: "advisor" },
];

const searchable: { label: string; href: string; icon: IconName }[] = [
  ...links,
  { label: "申请背景与资料", href: "/me", icon: "profile" },
];

/** Three panes need this much room; below it an open dock folds the rail to its icons. */
const THREE_PANES = "(min-width: 901px) and (max-width: 1439px)";

/**
 * The frame every route sits in. From 901px it is a rail on the left: navigation, the applicant's
 * applications with the days each has left, the sync state, the account and the theme. At 900px and
 * below the same elements become a top bar and a bottom tab bar (app/shell.css); nothing is rendered twice.
 *
 * From 901px the advisor is a dock on the right of every route but its own. Between 901px and 1439px
 * the three panes do not fit, so an open dock folds the rail; the rail's own button still opens it.
 */
export function Shell({ children }: { children: ReactNode }) {
  // `pathname` runs ahead of the router while a navigation is pending (Navigation.tsx): the rail and
  // the content area answer the click, and the route's own content replaces the placeholder when it
  // is ready. The dock follows the committed route: the advisor's page and the dock hold the same
  // conversation under the same ids, and must not be mounted together.
  const { pathname, committed, scrollY, onLinkClick, push } = useNavigation();
  const pendingShape = pathname !== committed ? routeShape(pathname) : null;
  const dock = useAdvisorDock();
  const hasDock = committed !== "/advisor";
  // Leaving the advisor's page, the width already makes room for the dock in the click's frame, so the
  // placeholder of the next page is laid out at its final width and nothing narrows when that page
  // arrives (the dock itself waits for the commit, above). Going to it, the room stays until the dock
  // has gone, so the dock never covers the page.
  const dockLayout = hasDock || pathname !== "/advisor";
  const [collapsed, setCollapsed] = useState(false);
  const [sidebarInteracted, setSidebarInteracted] = useState(false);
  const [tight, setTight] = useState(false);
  /** The applicant opened the rail beside an open dock on a tight screen; kept until the dock closes. */
  const [railForced, setRailForced] = useState(false);
  const [query, setQuery] = useState("");
  const search = useRef<HTMLDialogElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const nav = useRef<HTMLElement>(null);
  const crowded = dockLayout && dock.open && tight;
  const folded = crowded ? !railForced : collapsed;
  useContentMotion(content, pathname);
  useRailIndicator(nav, `${pathname} ${hasDock} ${folded}`);

  useEffect(() => {
    const media = window.matchMedia(THREE_PANES);
    const read = () => setTight(media.matches);
    read();
    media.addEventListener("change", read);
    return () => media.removeEventListener("change", read);
  }, []);
  useEffect(() => {
    if (!crowded) setRailForced(false);
  }, [crowded]);

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
    // Beside an open dock on a tight screen the button moves the rail for now, not the saved choice.
    if (crowded) return setRailForced((previous) => !previous);
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
  function searchSchools(event: FormEvent<HTMLFormElement>) {
    // Without script the form still loads /schools?q=…; with it the switch is the same as a link's.
    event.preventDefault();
    const q = query.trim();
    closeSearch();
    push(q ? `/schools?q=${encodeURIComponent(q)}` : "/schools");
  }

  return (
    <div
      className={`shell${folded ? " sidebar-collapsed" : ""}${dockLayout ? " has-dock" : ""}`}
      data-sidebar-interacted={sidebarInteracted || undefined}
      onClick={onLinkClick}
    >
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
            <button className="rail-button sidebar-collapse" aria-label="折叠侧边栏" aria-expanded={!folded} title="折叠侧边栏" onClick={toggleSidebar}>
              <Icon name="sidebar" />
            </button>
          </div>
        </div>
        <div className="rail-scroll">
          <nav className="rail-nav" aria-label="主导航" ref={nav}>
            <span className="nav-indicator" aria-hidden="true" />
            {links.map(({ label, short, href, icon, railOnly }) => {
              const current = isNavCurrent(href, pathname);
              // From 901px the advisor's entry opens the dock; on a phone it is the tab that leads to its page.
              const asDock = href === "/advisor" && hasDock;
              return (
                <Fragment key={href}>
                {asDock && (
                  <button
                    type="button"
                    id="advisor-toggle"
                    className="nav-dock"
                    title={`${label}（⌘/Ctrl J）`}
                    aria-label={label}
                    aria-expanded={dock.open}
                    aria-controls="advisor-dock"
                    onClick={() => dock.setOpen(!dock.open)}
                  >
                    <Icon name={icon} />
                    <span className="nav-label nav-long">{label}</span>
                    {/* The pane on the right, filled while the dock is open; a turn running out of sight spins here. */}
                    {dock.running && !dock.open ? (
                      <span className="nav-dock-state is-running" aria-hidden="true" />
                    ) : (
                      <Icon name={dock.open ? "dockOpen" : "dock"} className="nav-dock-state" />
                    )}
                  </button>
                )}
                <Link
                  href={href}
                  className={asDock ? "nav-tab-only" : railOnly ? "nav-rail-only" : undefined}
                  title={label}
                  aria-label={label}
                  aria-current={current ? "page" : undefined}
                >
                  <Icon name={icon} />
                  <span className="nav-label nav-long">{label}</span>
                  <span className="nav-label nav-short">{short}</span>
                </Link>
                </Fragment>
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
      <div className="workspace-content" id="main" tabIndex={-1} ref={content} aria-busy={pendingShape ? true : undefined}>
        {/* While a navigation is pending the destination's placeholder is drawn over the route being
            left, which stays mounted, invisible and in place. The window is not scrolled and the
            document keeps its height, so the browser stores the right scroll position for the entry
            being left, and an abandoned navigation finds the page as it was. */}
        {pendingShape && <RouteSkeleton shape={pendingShape} offset={scrollY} />}
        <div className="workspace-route" data-leaving={pendingShape ? "" : undefined} aria-hidden={pendingShape ? true : undefined}>
          {children}
        </div>
      </div>
      {hasDock && <Dock />}
      <AddProgramToast />
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
        <form action="/schools" onSubmit={searchSchools} className="workspace-search-form">
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
 *
 * A signed-out visitor sees the overview's demo programs here instead, under a mark that says so.
 */
function RailLegend() {
  const records = useApplicationRecords();
  const { committed: pathname, push } = useNavigation();
  const isDemo = !records.data && records.demo !== null;
  const source = records.data ?? records.demo;
  const rows = useMemo(() => (source ? overviewOf(source, beijingToday()).rows : []), [source]);
  if (!rows.length) return null;
  return (
    <section className="rail-legend" aria-labelledby="rail-legend-title">
      {isDemo ? (
        <h2 className="rail-legend-title is-demo" id="rail-legend-title">
          <span>我的申请</span>
          <span className="pill pill-sample">演示</span>
        </h2>
      ) : (
        <h2 className="rail-legend-title" id="rail-legend-title">
          我的申请
        </h2>
      )}
      <ul>
        {rows.map((row) => {
          const picked = records.selected === row.record.id;
          return (
            <li key={row.record.id}>
              <button
                type="button"
                className={`line-${row.line}${records.selected && !picked ? " is-dimmed" : ""}`}
                title={`${isDemo ? "演示：" : ""}${row.record.school} · ${row.record.name}`}
                aria-pressed={picked}
                onClick={() => {
                  records.select(picked ? null : row.record.id);
                  // The overview, the materials map and the roadmap draw the lines; from anywhere else a pick goes to the overview.
                  if (!picked && pathname !== "/" && pathname !== "/materials" && pathname !== "/roadmap") push("/");
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
  // A re-read behind data already on screen keeps the last time; only the first read says "syncing".
  const label = records.syncedAt ? `已同步 ${CLOCK.format(records.syncedAt)}` : "正在同步…";
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
