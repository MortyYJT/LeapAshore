// Instant navigation feedback: which route a click is about to open, which rail entry that makes
// current, and which page-shaped placeholder stands in until the route itself is on screen.
//
// Next commits a route change only once the next route can render, and `usePathname()` follows that
// commit. For a server-rendered route that is one or two network round trips after the click, during
// which nothing on screen used to change. The shell therefore keeps an optimistic pathname
// (components/shell/Navigation.tsx): set in the click's own event, dropped by React when the
// navigation commits or is abandoned. Everything here is pure so it can be tested without a browser.

/** The rail's entries, in order. `/advisor` is a tab on a phone and the dock's switch from 901px. */
export const NAV_HREFS = ["/", "/roadmap", "/applications", "/materials", "/schools", "/advisor"] as const;

/** Whether the rail entry `href` is the current one on `pathname`. */
export function isNavCurrent(href: string, pathname: string): boolean {
  if (href === "/") return pathname === "/";
  if (pathname === href || pathname.startsWith(`${href}/`)) return true;
  if (href === "/applications") return pathname === "/portfolio" || pathname === "/tiers";
  if (href === "/schools") return pathname === "/programs" || pathname.startsWith("/programs/");
  return false;
}

/** The page shapes the shell can draw before a route arrives. */
export type RouteShape =
  | "overview"
  | "roadmap"
  | "applications"
  | "materials"
  | "schools"
  | "school"
  | "program"
  | "tiers"
  | "portfolio"
  | "advisor"
  | "me"
  | "privacy"
  | "unsubscribe"
  | "admin";

const EXACT: Record<string, RouteShape> = {
  "/": "overview",
  "/roadmap": "roadmap",
  "/applications": "applications",
  "/materials": "materials",
  "/schools": "schools",
  "/tiers": "tiers",
  // The removed assessment pages redirect to /tiers (next.config.ts).
  "/assess": "tiers",
  "/assess/result": "tiers",
  "/portfolio": "portfolio",
  "/advisor": "advisor",
  "/me": "me",
  "/privacy": "privacy",
  "/reminders/unsubscribe": "unsubscribe",
  "/admin": "admin",
};

/**
 * The shape of the page at `pathname`, or null when it is not one of the app's routes (an API
 * download, a static file, a path that will be the 404 page). Null means no optimistic switch: the
 * click is left to the router alone.
 */
export function routeShape(pathname: string): RouteShape | null {
  const path = pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
  const exact = EXACT[path];
  if (exact) return exact;
  const [, first, second, third, ...rest] = path.split("/");
  if (first === "schools" && second && third === undefined) return "school";
  if (first === "programs" && second && third === undefined) return "program";
  if (first === "admin" && second === "sources" && third && rest.length === 0) return "admin";
  return null;
}

/** What the shell needs to know about a click, read off the event and the anchor it landed in. */
export interface LinkClick {
  /** The anchor's resolved `href` (absolute). */
  href: string;
  target?: string | null;
  download?: boolean;
  /** The link's own handler answered the click without leaving the page (`stayOnPage`). */
  local?: boolean;
  button: number;
  metaKey: boolean;
  ctrlKey: boolean;
  shiftKey: boolean;
  altKey: boolean;
  /** Read after the link's own handlers ran. Next's `Link` prevents the default when it navigates. */
  defaultPrevented: boolean;
}

/**
 * The pathname a click is about to navigate to inside the app, or null when the shell must not
 * switch ahead of the router: a modified or non-primary click, a new tab, a download, another
 * origin, a path that is not an app route, the page already on screen (a query-only change keeps its
 * content and is the page's own business), or a click nobody turned into a client-side navigation.
 */
export function clickDestination(click: LinkClick, here: { origin: string; pathname: string }): string | null {
  const url = clickedUrl(click, here.origin);
  return url ? destinationOf(url.pathname, here.pathname) : null;
}

/** The same decision for a programmatic `router.push(href)`. */
export function pushDestination(href: string, here: { origin: string; pathname: string }): string | null {
  const url = sameOrigin(href, here.origin);
  return url ? destinationOf(url.pathname, here.pathname) : null;
}

/**
 * The query a click is about to load on the page already on screen (the school list's pager, a search
 * from Cmd-K while on 学校库), or null. The page stays and keeps its rows until the new ones arrive;
 * the shell uses this to say that what is on screen is being refreshed. `here.search` is the query
 * on screen, with or without its "?".
 */
export function clickQuery(click: LinkClick, here: { origin: string; pathname: string; search: string }): string | null {
  const url = clickedUrl(click, here.origin);
  return url ? queryOf(url, here) : null;
}

/** The same decision for a programmatic `router.push(href)`. */
export function pushQuery(href: string, here: { origin: string; pathname: string; search: string }): string | null {
  const url = sameOrigin(href, here.origin);
  return url ? queryOf(url, here) : null;
}

function clickedUrl(click: LinkClick, origin: string): URL | null {
  if (click.button !== 0 || click.metaKey || click.ctrlKey || click.shiftKey || click.altKey) return null;
  if (!click.defaultPrevented || click.local || click.download) return null;
  if (click.target && click.target !== "_self") return null;
  return sameOrigin(click.href, origin);
}

function sameOrigin(href: string, origin: string): URL | null {
  let url: URL;
  try {
    url = new URL(href, origin);
  } catch {
    return null;
  }
  return url.origin === origin ? url : null;
}

function queryOf(url: URL, here: { pathname: string; search: string }): string | null {
  if (url.pathname !== here.pathname || routeShape(url.pathname) === null) return null;
  const search = here.search && !here.search.startsWith("?") ? `?${here.search}` : here.search;
  return url.search === search ? null : url.search;
}

function destinationOf(pathname: string, current: string): string | null {
  if (pathname === current || routeShape(pathname) === null) return null;
  return pathname;
}
