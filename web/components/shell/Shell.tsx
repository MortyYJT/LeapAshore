"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { useAuth } from "@/components/auth/AuthProvider";

import { Mark } from "./Mark";

// Spec app-navigation: four links and 我的, the current one marked, folding into a menu below 640px.
// Programs are browsed on their school's page; /programs/[id] still marks 学校库 as current.
// In login mode a logged-out visitor sees 登录 instead of 我的 (openspec account-login D11).
const LINKS: { label: string; href: string; matches: string[] }[] = [
  { label: "路线图", href: "/roadmap", matches: ["/roadmap"] },
  { label: "选校", href: "/portfolio", matches: ["/portfolio", "/tiers"] },
  { label: "学校库", href: "/schools", matches: ["/schools", "/programs"] },
  { label: "顾问", href: "/advisor", matches: ["/advisor"] },
];

function isCurrent(pathname: string, matches: string[]): boolean {
  return matches.some((m) => pathname === m || pathname.startsWith(`${m}/`));
}

export function Shell({ children, footer }: { children: ReactNode; footer?: ReactNode }) {
  const pathname = usePathname() ?? "/";
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => setOpen(false), [pathname]);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 4);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const meCurrent = isCurrent(pathname, ["/me"]);
  const { gated, state, openLogin } = useAuth();
  return (
    <>
      <header className={`bar${scrolled ? " scrolled" : ""}${open ? " open" : ""}`}>
        <div className="bar-inner">
          <Link className="brand" href="/">
            <Mark />
            <span>鱼跃彼岸</span>
          </Link>
          <nav className="nav" id="main-nav" aria-label="主导航">
            {LINKS.map((link) => (
              <Link key={link.href} href={link.href} aria-current={isCurrent(pathname, link.matches) ? "page" : undefined}>
                {link.label}
              </Link>
            ))}
            {!gated && (
              <Link className="phone-only" href="/me" aria-current={meCurrent ? "page" : undefined}>
                我的
              </Link>
            )}
          </nav>
          {gated ? (
            <button type="button" className="btn btn-primary btn-small login-btn" onClick={() => openLogin("/tiers")}>
              登录
            </button>
          ) : (
            <Link className="me-link" href="/me" aria-current={meCurrent ? "page" : undefined} title={state?.account?.email}>
              我的
            </Link>
          )}
          <button
            type="button"
            className="btn btn-secondary btn-small menu-btn"
            aria-expanded={open}
            aria-controls="main-nav"
            onClick={() => setOpen((v) => !v)}
          >
            {open ? "关闭" : "菜单"}
          </button>
        </div>
      </header>
      {children}
      <footer className="site-foot">{footer}</footer>
    </>
  );
}
