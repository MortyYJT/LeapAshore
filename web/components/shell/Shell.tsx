"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { Mark } from "./Mark";

// Spec app-navigation: five links and 我的背景, the current one marked, folding into a menu below 640px.
const LINKS: { label: string; href: string; matches: string[] }[] = [
  { label: "路线图", href: "/roadmap", matches: ["/roadmap"] },
  { label: "选校", href: "/portfolio", matches: ["/portfolio", "/assess"] },
  { label: "学校库", href: "/schools", matches: ["/schools"] },
  { label: "项目库", href: "/programs", matches: ["/programs"] },
  { label: "顾问", href: "/advisor", matches: ["/advisor"] },
];

function isCurrent(pathname: string, matches: string[]): boolean {
  return matches.some((m) => pathname === m || pathname.startsWith(`${m}/`));
}

export function Shell({ children }: { children: ReactNode }) {
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
            <Link className="phone-only" href="/me" aria-current={meCurrent ? "page" : undefined}>
              我的背景
            </Link>
          </nav>
          <Link className="me-link" href="/me" aria-current={meCurrent ? "page" : undefined}>
            我的背景
          </Link>
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
    </>
  );
}
