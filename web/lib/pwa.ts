// The installed app: what the browser's own bars are coloured, and whether this browser can install.
// No React here, so the manifest, the pre-paint scripts and the tests can all read it.

/** The mode the settings last applied. Not per account: the scripts that run before first paint read it. */
export const APPEARANCE_KEY = "leapashore:appearance";

/** The rail's colour in each theme (`--rail` in app/globals.css): the browser's bars and the status bar take it. */
export const THEME_COLOR = { light: "#f6f6f6", dark: "#141414" } as const;

/** The page's one `<meta name="theme-color">`, which the app keeps in step with its theme switch. */
export const THEME_COLOR_META = "applied-theme-color";

/**
 * Colour the browser's bars for the theme now showing. ThemeScript creates the meta before first
 * paint; this updates it when the mode changes (and creates it if that script did not run).
 */
export function applyThemeColor(appearance: "light" | "dark") {
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
