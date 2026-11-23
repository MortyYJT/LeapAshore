// The installed app: what the browser's own bars are coloured, and whether this browser can install.
// No React here, so the manifest, the pre-paint scripts and the tests can all read it.

/** The mode the settings last applied. Not per account: the scripts that run before first paint read it. */
export const APPEARANCE_KEY = "leapashore:appearance";

/** The three choices under 设置 → 外观, in the order they are shown. The first is the default. */
export const APPEARANCE_MODES = ["system", "light", "dark"] as const;
export type AppearanceMode = (typeof APPEARANCE_MODES)[number];
export type Appearance = "light" | "dark";

/** A stored mode, or "system" for anything else: a new visitor, a cleared store, a value from an older build. */
export function appearanceMode(stored: unknown): AppearanceMode {
  return APPEARANCE_MODES.includes(stored as AppearanceMode) ? (stored as AppearanceMode) : "system";
}

/** The theme a mode shows while the system asks for dark (`systemDark`) or light. */
export function resolveAppearance(mode: AppearanceMode, systemDark: boolean): Appearance {
  return mode === "system" ? (systemDark ? "dark" : "light") : mode;
}

/** The rail's colour in each theme (`--rail` in app/globals.css): the browser's bars and the status bar take it. */
export const THEME_COLOR = { light: "#f6f6f6", dark: "#141414" } as const;

/** The page's one `<meta name="theme-color">`, which the app keeps in step with its theme switch. */
export const THEME_COLOR_META = "applied-theme-color";

/**
 * The script ThemeScript puts in the server's HTML, run before first paint: the same decision as
 * `appearanceMode` and `resolveAppearance`, written out because it runs before any module loads.
 * Only "dark" and "light" are explicit; anything else follows the system.
 */
export const THEME_SCRIPT = `(function(){try{var m=localStorage.getItem(${JSON.stringify(APPEARANCE_KEY)});var d=m==="dark"||(m!=="light"&&matchMedia("(prefers-color-scheme: dark)").matches);document.documentElement.dataset.appearance=d?"dark":"light";var c=document.createElement("meta");c.id=${JSON.stringify(THEME_COLOR_META)};c.name="theme-color";c.content=d?${JSON.stringify(THEME_COLOR.dark)}:${JSON.stringify(THEME_COLOR.light)};document.head.append(c)}catch(e){}})()`;

/**
 * Colour the browser's bars for the theme now showing. ThemeScript creates the meta before first
 * paint; this updates it when the mode changes (and creates it if that script did not run).
 */
export function applyThemeColor(appearance: Appearance) {
  let meta = document.getElementById(THEME_COLOR_META);
  if (!meta) {
    meta = document.createElement("meta");
    meta.id = THEME_COLOR_META;
    meta.setAttribute("name", "theme-color");
    document.head.append(meta);
  }
  meta.setAttribute("content", THEME_COLOR[appearance]);
}

export type InstallMode = "prompt" | "ios" | "none";

export type InstallFacts = {
  userAgent: string;
  maxTouchPoints: number;
  /** Already running in its own window. */
  standalone: boolean;
  /** The browser fired `beforeinstallprompt`, so its install dialog can be opened. */
  promptReady: boolean;
};

/** iPadOS sends a Mac user agent by default; a Mac has no touch points. */
export function isIos(userAgent: string, maxTouchPoints: number): boolean {
  return /iPhone|iPad|iPod/.test(userAgent) || (/Macintosh/.test(userAgent) && maxTouchPoints > 1);
}

/**
 * How the install entry behaves here. `prompt`: a button that opens the browser's install dialog.
 * `ios`: the steps for the share menu, since iOS has no such dialog. `none`: no entry, because the
 * app is already installed and open, or this browser has not offered to install it.
 */
export function installMode(facts: InstallFacts): InstallMode {
  if (facts.standalone) return "none";
  if (facts.promptReady) return "prompt";
  return isIos(facts.userAgent, facts.maxTouchPoints) ? "ios" : "none";
}
