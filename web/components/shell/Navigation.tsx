"use client";

import { usePathname, useRouter } from "next/navigation";
import {
  createContext,
  startTransition,
  useCallback,
  useContext,
  useMemo,
  useOptimistic,
  useRef,
  type MouseEvent,
  type ReactNode,
} from "react";

import { clickDestination, clickQuery, pushDestination, pushQuery, type LinkClick } from "@/lib/navigation";

/**
 * The pathname the shell shows, which can run ahead of the router's.
 *
 * Next changes `usePathname()` when the next route commits: after its payload and code have arrived.
 * `pathname` here changes in the click's own event, so the rail's current entry and the content
 * area's placeholder do not wait for the network. It is React's optimistic state: set inside a
 * transition in the same event as the router's own, it lasts exactly as long as that navigation is
 * pending, and falls back to the committed pathname by itself when the navigation commits, is
 * replaced by another click, redirects elsewhere, or never starts. There is no timer and nothing to
 * clear by hand.
 */
interface NavigationState {
  /** What to draw: the destination of a pending navigation, otherwise the committed pathname. */
  pathname: string;
  /** The router's pathname: the route whose content is mounted. */
  committed: string;
  /** How far the page being left was scrolled when the pending navigation began. */
  scrollY: number;
  /**
   * A new query for the page on screen is on its way (the school list's filter, pager, or a search
   * from Cmd-K while on 学校库). The page keeps what it shows until the answer arrives, and says so.
   */
  refreshing: boolean;
  /** For the shell's root: a click on any in-app link switches the shown pathname at once. */
  onLinkClick: (event: MouseEvent<HTMLElement>) => void;
  /** `router.push` with the same instant switch, for navigations that are not links. */
  push: (href: string, options?: { scroll?: boolean }) => void;
}

const Ctx = createContext<NavigationState | null>(null);

/** Clicks a link's own handler answered without leaving the page. */
const answeredHere = new WeakSet<Event>();

/**
 * For a link's `onClick` that handles the click itself (让顾问去查 opens the dock from 901px): cancel
 * the navigation and tell the shell not to switch pages for it. A bare `preventDefault()` cannot say
 * that, because Next's `Link` prevents the default of every click it turns into a navigation.
 */
export function stayOnPage(event: MouseEvent<HTMLElement>) {
  event.preventDefault();
  answeredHere.add(event.nativeEvent);
}

export function NavigationProvider({ children }: { children: ReactNode }) {
  const committed = usePathname() ?? "/";
  const router = useRouter();
  const [shown, setShown] = useOptimistic<{ pathname: string; scrollY: number; query: string | null }>({ pathname: committed, scrollY: 0, query: null });
  const pathname = shown.pathname;
  // Clicks are judged against what is on screen: during a pending navigation a click on the route
  // being left is a real change (back to it, at once), and a click on the pending one is not.
  const shownRef = useRef(pathname);
  shownRef.current = pathname;

  const onLinkClick = useCallback((event: MouseEvent<HTMLElement>) => {
    const anchor = event.target instanceof Element ? event.target.closest<HTMLAnchorElement>("a[href]") : null;
    if (!anchor) return;
    const click: LinkClick = {
      href: anchor.href,
      target: anchor.getAttribute("target"),
      download: anchor.hasAttribute("download"),
      local: answeredHere.has(event.nativeEvent),
      button: event.button,
      metaKey: event.metaKey,
      ctrlKey: event.ctrlKey,
      shiftKey: event.shiftKey,
      altKey: event.altKey,
      // This handler sits above every link, so it runs after the link's own: Next's `Link` has
      // already prevented the default if it took the click.
      defaultPrevented: event.defaultPrevented,
    };
    const destination = clickDestination(click, { origin: window.location.origin, pathname: shownRef.current });
    if (destination) {
      const scrollY = window.scrollY;
      startTransition(() => setShown({ pathname: destination, scrollY, query: null }));
      return;
    }
    const query = clickQuery(click, { origin: window.location.origin, pathname: shownRef.current, search: window.location.search });
    if (query !== null) {
      const scrollY = window.scrollY;
      startTransition(() => setShown({ pathname: shownRef.current, scrollY, query }));
    }
  }, [setShown]);

  const push = useCallback(
    (href: string, options?: { scroll?: boolean }) => {
      const here = { origin: window.location.origin, pathname: shownRef.current };
      const destination = pushDestination(href, here);
      const query = destination ? null : pushQuery(href, { ...here, search: window.location.search });
      const scrollY = window.scrollY;
      startTransition(() => {
        if (destination) setShown({ pathname: destination, scrollY, query: null });
        else if (query !== null) setShown({ pathname: shownRef.current, scrollY, query });
        router.push(href, options);
      });
    },
    [router, setShown],
  );

  const value = useMemo(
    () => ({ pathname, committed, scrollY: shown.scrollY, refreshing: shown.query !== null, onLinkClick, push }),
    [pathname, committed, shown.scrollY, shown.query, onLinkClick, push],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useNavigation(): NavigationState {
  const value = useContext(Ctx);
  if (!value) throw new Error("useNavigation needs NavigationProvider above it");
  return value;
}
