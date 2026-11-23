"use client";

import { useEffect, useLayoutEffect, useRef, type RefObject } from "react";

import { ENTER_MS, IDLE, entersOnSwitch, nextPhase, revealIn, revealed, type LoadPhase } from "@/lib/motion";

// The content area's motion (lib/motion.ts decides, app/motion.css draws the bars). Nothing here is
// React state, so a load or a page switch costs no extra render.
//
// - `data-loading="wait" | "shown"` on the content area while any placeholder is in it: bars stay
//   invisible until it says "shown", then fade in.
// - When content replaces bars that were painted, the new blocks fade in where they were (Web
//   Animations, started in the frame they are inserted). Blocks that were already there (the title)
//   and new blocks that are themselves placeholders are left alone.

/** What counts as a placeholder: the shell's page-shaped one, a bar, the generic loading block. */
const PLACEHOLDER = "[data-route-skeleton], .sk, .skeleton";

/** New blocks that do not fade: what the placeholder already drew. Placeholders themselves do not either. */
const STEADY = "h1, .page-head, .title-row, .crumb, .sr-only";

/** A placeholder, or a block holding one. (`:has()` would say this in one selector, but throws in older browsers.) */
function holdsPlaceholder(element: Element): boolean {
  return element.matches(PLACEHOLDER) || element.querySelector(PLACEHOLDER) !== null;
}

/** The rail's highlight moving to the entry clicked (--motion-normal). */
const SLIDE_MS = 180;

/** Fast at first, settling gently: the arrival curve every motion here shares (--motion-out). */
const EASE_OUT = "cubic-bezier(.16, 1, .3, 1)";

function reducedMotion(): boolean {
  return typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function isPlaceholder(node: Node): boolean {
  return node instanceof Element && holdsPlaceholder(node);
}

/**
 * Whether a placeholder is on screen. The route being left during a pending navigation is hidden, and
 * a placeholder still in it says nothing about the load that has just begun.
 */
function placeholderShown(area: HTMLElement): boolean {
  for (const found of area.querySelectorAll(PLACEHOLDER)) if (!found.closest("[data-leaving]")) return true;
  return false;
}

/**
 * Where the content that replaced a placeholder sits. The shell's placeholder is a child of the
 * content area itself and the route replaces it from the wrapper beside it: there the route's own
 * root is the target, so its new title (drawn by the placeholder already) is not faded.
 */
function fillTarget(parent: Node, area: HTMLElement): Element | null {
  if (!(parent instanceof Element) || !parent.isConnected) return null;
  if (parent === area || parent.classList.contains("workspace-route")) {
    return area.querySelector(":scope > .workspace-route > *");
  }
  return parent;
}

/**
 * The page switch and the placeholder hand-over for the content area `ref`. `pathname` is the path the
 * shell shows (it runs ahead of the router while a navigation is pending), so the switch starts in the
 * click's own frame and is not repeated when the route commits.
 */
export function useContentMotion(ref: RefObject<HTMLElement | null>, pathname: string) {
  const last = useRef<string | null>(null);
  const restart = useRef<(() => void) | null>(null);
  useLayoutEffect(() => {
    const area = ref.current;
    const previous = last.current;
    last.current = pathname;
    // A page switch starts a new load: the bars of the page being left say nothing about it.
    if (previous !== null && previous !== pathname) restart.current?.();
    if (!area || !entersOnSwitch(previous, pathname, reducedMotion())) return;
    // Opacity only: a transform here would make the content area the frame of anything fixed inside it.
    for (const running of area.getAnimations()) if (running.id === "page-enter") running.cancel();
    const enter = area.animate([{ opacity: 0.4 }, { opacity: 1 }], { duration: ENTER_MS, easing: EASE_OUT });
    enter.id = "page-enter";
  }, [pathname, ref]);

  useEffect(() => {
    const area = ref.current;
    if (!area) return;
    let phase: LoadPhase = IDLE;
    let reveal: ReturnType<typeof setTimeout> | undefined;

    const show = () => {
      if (phase.phase === "idle") delete area.dataset.loading;
      else area.dataset.loading = phase.phase;
    };
    const schedule = () => {
      clearTimeout(reveal);
      const wait = revealIn(phase, performance.now());
      if (wait === null) return;
      reveal = setTimeout(() => {
        phase = revealed(phase, performance.now());
        show();
        schedule();
      }, wait);
    };
    const fadeIn = (target: Element, added: Set<Node>) => {
      // Every block under a new root is new; under a root that stayed, only the inserted ones are.
      const fresh = (node: Node) => {
        for (let at: Node | null = node; at && at !== area; at = at.parentNode) if (added.has(at)) return true;
        return false;
      };
      const all = fresh(target);
      const blocks = [...target.children].filter((child) => (all || added.has(child)) && !child.matches(STEADY) && !holdsPlaceholder(child));
      // The sentence under the title changes from a bar to words, in a new header or in place.
      for (const head of target.querySelectorAll(":scope > :is(.page-head, .title-row) .finding")) {
        if ((all || fresh(head)) && !holdsPlaceholder(head)) blocks.push(head);
      }
      // A bar inside a line of text (the sentence under a title, a value) gave way to words: the line fades.
      if (!blocks.length && target.children.length === 0 && target !== area) blocks.push(target);
      for (const block of blocks) block.animate([{ opacity: 0 }, { opacity: 1 }], { duration: ENTER_MS, easing: EASE_OUT, id: "fill-in" });
    };
    const update = (changes: MutationRecord[]) => {
      const { next, fade } = nextPhase(phase, placeholderShown(area), performance.now(), reducedMotion());
      if (fade) {
        const added = new Set(changes.flatMap((change) => [...change.addedNodes]));
        const targets = new Set<Element>();
        for (const change of changes) {
          if (![...change.removedNodes].some(isPlaceholder)) continue;
          const target = fillTarget(change.target, area);
          if (target) targets.add(target);
        }
        for (const target of targets) fadeIn(target, added);
      }
      phase = next;
      show();
      schedule();
    };

    // Mutation callbacks run after React's commit and before the frame is painted, so a placeholder
    // is held back from its first frame and replaced content starts transparent in its first frame.
    const observer = new MutationObserver(update);
    observer.observe(area, { childList: true, subtree: true });
    // Bars already in the server's HTML have been on screen since the first paint: they stay. Until
    // this runs, nothing hides them (app/motion.css keys the wait on `data-motion`).
    if (placeholderShown(area)) phase = { phase: "shown", since: performance.now() };
    area.dataset.motion = "";
    show();
    restart.current = () => {
      // The pending mutations belong to the page being left; the new load is judged from here.
      observer.takeRecords();
      phase = IDLE;
      update([]);
    };
    return () => {
      restart.current = null;
      delete area.dataset.motion;
      observer.disconnect();
      clearTimeout(reveal);
      delete area.dataset.loading;
    };
  }, [ref]);
}

/**
 * The rail's highlight as one shape that slides to the current entry (from 901px; the phone's tabs
 * change colour). `nav` holds the entries and a `.nav-indicator` as its first child; `key` is anything
 * that moves the current entry or the entries themselves.
 */
export function useRailIndicator(nav: RefObject<HTMLElement | null>, key: string) {
  useLayoutEffect(() => {
    if (nav.current) placeIndicator(nav.current, true);
  }, [nav, key]);
  useEffect(() => {
    const list = nav.current;
    if (!list) return;
    // A change of layout (the rail folded, the window resized) puts it in place without a slide. The
    // observer reports once when it starts; that is not a change.
    let started = false;
    const resized = new ResizeObserver(() => {
      if (started) placeIndicator(list, false);
      started = true;
    });
    resized.observe(list);
    return () => resized.disconnect();
  }, [nav]);
}

function placeIndicator(list: HTMLElement, slide: boolean) {
  const current = [...list.querySelectorAll<HTMLElement>('a[aria-current="page"]')].find((link) => link.offsetParent !== null);
  const shape = list.querySelector<HTMLElement>(".nav-indicator");
  if (!current || !shape) {
    delete list.dataset.indicator;
    return;
  }
  // Where the highlight is on screen now, part-way through a slide if one is running.
  const from = list.dataset.indicator !== undefined ? shape.getBoundingClientRect().top - list.getBoundingClientRect().top : NaN;
  const to = current.offsetTop;
  list.style.setProperty("--indicator-h", `${current.offsetHeight}px`);
  if (list.dataset.indicator !== undefined && list.style.getPropertyValue("--indicator-y") === `${to}px`) return;
  list.style.setProperty("--indicator-y", `${to}px`);
  list.dataset.indicator = "";
  // The first placement, and a change of layout, are drawn in place; a new current entry slides from
  // where the highlight was. A script animation rather than a CSS transition: the transition did not
  // start when React's commit and this placement landed in the same frame.
  for (const running of shape.getAnimations()) running.cancel();
  // On a phone the shape is not drawn (the tabs change colour instead).
  if (slide && shape.getClientRects().length > 0 && Number.isFinite(from) && Math.abs(from - to) > 1 && !reducedMotion()) {
    shape.animate([{ translate: `0 ${from}px` }, { translate: `0 ${to}px` }], { duration: SLIDE_MS, easing: EASE_OUT, id: "rail-slide" });
  }
}
