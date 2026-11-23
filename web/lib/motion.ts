// When the content area animates, decided in one place (components/shell/Motion.tsx applies it).
//
// Three moments move, each once and each short:
// - a page switch: the content area eases in from part opacity (opacity only, so nothing fixed inside
//   it is repositioned while it runs);
// - placeholder bars: they stay invisible for the first `SKELETON_WAIT_MS` of a load, so data that
//   arrives quickly replaces the placeholder before any bar is painted, and then fade in;
// - the content that replaces bars the visitor has seen fades in where they were. Content that
//   arrives before the bars were shown, or is already in memory, is drawn at once with no fade.
// Reduced Motion turns all three off; the placeholder still shows (after the same short wait) and stays
// until the data lands.

/** How long a placeholder is held back before its bars are painted. Under 100 ms reads as instant. */
export const SKELETON_WAIT_MS = 100;

/** How long a page switch and a fill-in fade last (Web Animations, components/shell/Motion.tsx). */
export const ENTER_MS = 180;

/** Where the content area's placeholder bars stand. */
export type LoadPhase =
  | { phase: "idle" }
  /** A placeholder is on screen and its bars are still held back. */
  | { phase: "wait"; since: number }
  /** A placeholder is on screen and its bars are painted. */
  | { phase: "shown"; since: number };

export const IDLE: LoadPhase = { phase: "idle" };

/**
 * The next phase after the content area changed. `placeholder`: whether a placeholder is still on
 * screen. `fade` says whether content that replaced a placeholder in this change fades in: only when
 * the bars had been painted. A placeholder that hands over to another one (the shell's to the route's
 * own, one block's to the next) keeps the phase and its start, so bars already shown are not hidden
 * again and bars still held back are revealed on the first one's clock. Under Reduced Motion the bars
 * are still held back (that is not motion, and it keeps a fast load from flashing them for a frame),
 * but nothing fades.
 */
export function nextPhase(previous: LoadPhase, placeholder: boolean, now: number, reduced: boolean): { next: LoadPhase; fade: boolean } {
  const fade = previous.phase === "shown" && !reduced;
  if (!placeholder) return { next: IDLE, fade };
  return { next: previous.phase === "idle" ? { phase: "wait", since: now } : previous, fade };
}

/** The phase once `now` is reached: bars held back for `SKELETON_WAIT_MS` are then painted. */
export function revealed(current: LoadPhase, now: number): LoadPhase {
  if (current.phase === "wait" && now - current.since >= SKELETON_WAIT_MS) return { phase: "shown", since: current.since };
  return current;
}

/** How long to wait from `now` before the bars of `current` are due, or null when nothing is held back. */
export function revealIn(current: LoadPhase, now: number): number | null {
  if (current.phase !== "wait") return null;
  return Math.max(0, SKELETON_WAIT_MS - (now - current.since));
}

/** Whether a page switch eases in: not under Reduced Motion, and not when the path did not change. */
export function entersOnSwitch(previous: string | null, next: string, reduced: boolean): boolean {
  return !reduced && previous !== null && previous !== next;
}
