"use client";

import { APPEARANCE_KEY, THEME_COLOR, THEME_COLOR_META } from "@/lib/pwa";

// Reads the mode the settings last applied, then the system, and sets `data-appearance` on <html>.
// It also writes the page's theme-color (lib/pwa.ts, applyThemeColor), so the browser's bars match
// a theme chosen in the settings and not only the system's.
const SOURCE = `(function(){try{var m=localStorage.getItem(${JSON.stringify(APPEARANCE_KEY)});var d=m==="dark"||(m!=="light"&&matchMedia("(prefers-color-scheme: dark)").matches);document.documentElement.dataset.appearance=d?"dark":"light";var c=document.createElement("meta");c.id=${JSON.stringify(THEME_COLOR_META)};c.name="theme-color";c.content=d?${JSON.stringify(THEME_COLOR.dark)}:${JSON.stringify(THEME_COLOR.light)};document.head.append(c)}catch(e){}})()`;

/**
 * Sets the theme before the first paint, so a dark reader never sees a white page first. Once the app
 * has loaded, UserCenter applies the account's own preference.
 *
 * The script only has to run from the server's HTML. When React builds this element in the browser
 * instead (it does for a not-found page), a script would not run anyway and React logs an error for
 * it, so there it is typed as data. The type differs from the server's on purpose, hence
 * `suppressHydrationWarning`.
 */
export function ThemeScript() {
  return (
    <script
      suppressHydrationWarning
      type={typeof window === "undefined" ? undefined : "application/json"}
      dangerouslySetInnerHTML={{ __html: SOURCE }}
    />
  );
}
