import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import manifest from "../app/manifest.ts";
import { APPEARANCE_KEY, installMode, isIos, THEME_COLOR, type InstallFacts } from "./pwa.ts";

const IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1";
const IPAD_DESKTOP_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15";
const ANDROID_CHROME = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36";
const MAC_CHROME = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36";

const facts = (over: Partial<InstallFacts>): InstallFacts => ({
  userAgent: MAC_CHROME,
  maxTouchPoints: 0,
  standalone: false,
  promptReady: false,
  ...over,
});

test("an iPad that sends a Mac user agent is still iOS, a Mac is not", () => {
  assert.equal(isIos(IPHONE, 5), true);
  assert.equal(isIos(IPAD_DESKTOP_UA, 5), true);
  assert.equal(isIos(IPAD_DESKTOP_UA, 0), false);
  assert.equal(isIos(ANDROID_CHROME, 5), false);
});

test("the install entry offers the browser's prompt only once the browser has offered one", () => {
  assert.equal(installMode(facts({})), "none");
  assert.equal(installMode(facts({ promptReady: true })), "prompt");
  assert.equal(installMode(facts({ userAgent: ANDROID_CHROME, maxTouchPoints: 5, promptReady: true })), "prompt");
  assert.equal(installMode(facts({ userAgent: ANDROID_CHROME, maxTouchPoints: 5 })), "none");
});

test("iOS has no prompt, so the entry gives the steps instead", () => {
  assert.equal(installMode(facts({ userAgent: IPHONE, maxTouchPoints: 5 })), "ios");
  assert.equal(installMode(facts({ userAgent: IPAD_DESKTOP_UA, maxTouchPoints: 5 })), "ios");
});

test("an app already running in its own window offers nothing", () => {
  assert.equal(installMode(facts({ standalone: true, promptReady: true })), "none");
  assert.equal(installMode(facts({ userAgent: IPHONE, maxTouchPoints: 5, standalone: true })), "none");
});

test("the manifest has what an installer needs, and every icon it lists is a file of that size", () => {
  const m = manifest();
  assert.equal(m.display, "standalone");
  assert.equal(m.start_url, "/");
  assert.equal(m.scope, "/");
  assert.equal(m.lang, "zh-CN");
  assert.ok(m.name && m.short_name && m.description);
  assert.equal(m.theme_color, THEME_COLOR.light);
  const icons = m.icons ?? [];
  for (const size of ["192x192", "512x512"]) {
    assert.ok(icons.some((icon) => icon.sizes === size && (icon.purpose ?? "any") === "any"), `any ${size}`);
    assert.ok(icons.some((icon) => icon.sizes === size && icon.purpose === "maskable"), `maskable ${size}`);
  }
  for (const icon of [...icons, ...(m.shortcuts ?? []).flatMap((shortcut) => shortcut.icons ?? [])]) {
    const png = readFileSync(new URL(`../public${icon.src}`, import.meta.url));
    // A PNG states its width and height in the IHDR chunk, at bytes 16 and 20.
    assert.equal(`${png.readUInt32BE(16)}x${png.readUInt32BE(20)}`, icon.sizes, icon.src);
    assert.equal(icon.type, "image/png");
  }
  assert.deepEqual((m.shortcuts ?? []).map((shortcut) => shortcut.url), ["/", "/applications", "/advisor"]);
});

// ---------- the service worker (public/sw.js), run against a stand-in for its global ----------

const SOURCE = readFileSync(new URL("../public/sw.js", import.meta.url), "utf8");
const ORIGIN = "https://leapashore.example";

type Listener = (event: Record<string, unknown>) => void;

function worker(fetcher: (request: unknown) => Promise<Response>) {
  const listeners = new Map<string, Listener>();
  const scope = {
    location: { origin: ORIGIN },
    addEventListener: (type: string, listener: Listener) => listeners.set(type, listener),
    skipWaiting: () => Promise.resolve(),
    clients: { claim: () => Promise.resolve() },
  };
  new Function("self", "fetch", "caches", SOURCE)(scope, fetcher, undefined);
  return {
    listeners,
    /** The response the worker answers with, or `null` when it leaves the request to the browser. */
    async answer(path: string, init: { mode?: string; method?: string; origin?: string } = {}) {
      let answered: Promise<Response> | null = null;
      listeners.get("fetch")!({
        request: { url: `${init.origin ?? ORIGIN}${path}`, mode: init.mode ?? "navigate", method: init.method ?? "GET" },
        respondWith: (response: Promise<Response>) => (answered = response),
      });
      return answered === null ? null : await (answered as Promise<Response>);
    },
  };
}

const offline = () => Promise.reject(new TypeError("Failed to fetch"));

test("the worker answers a page navigation that cannot reach the server with its own page", async () => {
  const response = await worker(offline).answer("/applications");
  assert.ok(response);
  assert.equal(response.status, 503);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html/);
  assert.equal(response.headers.get("cache-control"), "no-store");
  const html = await response.text();
  assert.match(html, /连不上/);
  // The page follows the theme the settings last applied, like the app's own first paint.
  assert.ok(html.includes(JSON.stringify(APPEARANCE_KEY)));
  // It loads nothing: no stylesheet, script file, image or font it could fail to fetch.
  assert.doesNotMatch(html, /<link|src=|url\(/);
});

test("the worker hands a navigation that does reach the server straight through", async () => {
  const page = new Response("<p>fresh</p>", { status: 200 });
  assert.equal(await worker(async () => page).answer("/"), page);
  const failing = new Response("bad gateway", { status: 502 });
  assert.equal(await worker(async () => failing).answer("/applications"), failing);
});

test("the worker never touches the API, other origins, or anything that is not a page navigation", async () => {
  const w = worker(offline);
  assert.equal(await w.answer("/api/application-records"), null);
  assert.equal(await w.answer("/api"), null);
  assert.equal(await w.answer("/api/materials/1/file"), null);
  assert.equal(await w.answer("/_next/static/chunks/app.js", { mode: "no-cors" }), null);
  assert.equal(await w.answer("/applications", { mode: "cors" }), null);
  assert.equal(await w.answer("/applications", { mode: "same-origin" }), null);
  assert.equal(await w.answer("/applications", { method: "POST" }), null);
  assert.equal(await w.answer("/", { origin: "https://other.example" }), null);
  // A path that merely starts with the same letters is a page.
  assert.ok(await w.answer("/apiary"));
});

test("the worker stores nothing and takes over as soon as it is installed", () => {
  // No Cache Storage, no IndexedDB: there is no copy of a page or a response that could go stale.
  assert.doesNotMatch(SOURCE.replace(/^\s*\/\/.*$/gm, ""), /caches|indexedDB|\.put\(|\.add\(|addAll/);
  const w = worker(offline);
  let waited = 0;
  w.listeners.get("install")!({ waitUntil: () => (waited += 1) });
  w.listeners.get("activate")!({ waitUntil: () => (waited += 1) });
  assert.equal(waited, 2);
});
