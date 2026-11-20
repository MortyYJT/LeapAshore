"use client";

import { useEffect, useState } from "react";

import { installMode, type InstallMode } from "@/lib/pwa";

/** Fired on `window` when the browser's offer to install appears or goes away. */
const CHANGED = "leapashore-install";

/** Chromium's `beforeinstallprompt` event, which no DOM typing describes. */
type PromptEvent = Event & {
  prompt(): Promise<unknown>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};

declare global {
  interface Window {
    /** The offer the browser last made, kept until it is used. */
    __leapashoreInstall?: PromptEvent | null;
  }
}

// The browser may offer to install before React has hydrated, so the offer is caught here. Taking
// the event (preventDefault) also keeps Chrome on Android from showing its own banner: installing
// is offered only where the applicant goes looking for it (settings and the account menu).
const CATCH = `addEventListener("beforeinstallprompt",function(e){e.preventDefault();window.__leapashoreInstall=e;dispatchEvent(new Event("${CHANGED}"))});addEventListener("appinstalled",function(){window.__leapashoreInstall=null;dispatchEvent(new Event("${CHANGED}"))});`;
// The service worker only answers a failed page load with a "cannot reach the server" page
// (public/sw.js). The dev server goes without one.
const REGISTER =
  process.env.NODE_ENV === "production"
    ? `if("serviceWorker" in navigator)addEventListener("load",function(){navigator.serviceWorker.register("/sw.js",{scope:"/",updateViaCache:"none"}).catch(function(){})});`
    : "";
const SOURCE = `(function(){try{${CATCH}${REGISTER}}catch(e){}})()`;

/** Runs from the server's HTML, like ThemeScript; see there for why the type differs in the browser. */
export function InstallScript() {
  return (
    <script
      suppressHydrationWarning
      type={typeof window === "undefined" ? undefined : "application/json"}
      dangerouslySetInnerHTML={{ __html: SOURCE }}
    />
  );
}

/** Whether installing can be offered here and how (lib/pwa.ts), and the call that opens the browser's dialog. */
export function useInstall(): { mode: InstallMode; install: () => Promise<"accepted" | "dismissed" | "unavailable"> } {
  const [mode, setMode] = useState<InstallMode>("none");

  useEffect(() => {
    const display = window.matchMedia("(display-mode: standalone)");
    const read = () =>
      setMode(
        installMode({
          userAgent: navigator.userAgent,
          maxTouchPoints: navigator.maxTouchPoints,
          // iOS reports a home-screen app through its own property.
          standalone: display.matches || (navigator as { standalone?: boolean }).standalone === true,
          promptReady: Boolean(window.__leapashoreInstall),
        }),
      );
    read();
    window.addEventListener(CHANGED, read);
    display.addEventListener("change", read);
    return () => {
      window.removeEventListener(CHANGED, read);
      display.removeEventListener("change", read);
    };
  }, []);

  async function install() {
    const offer = window.__leapashoreInstall;
    if (!offer) return "unavailable";
    // An offer opens the dialog once. If the applicant declines, the browser makes a new one when
    // it is willing to be asked again, and the entry comes back with it.
    window.__leapashoreInstall = null;
    window.dispatchEvent(new Event(CHANGED));
    try {
      await offer.prompt();
      return (await offer.userChoice).outcome;
    } catch {
      return "unavailable";
    }
  }

  return { mode, install };
}
