// LeapAshore's service worker. It has one job: when opening a page cannot reach the server, answer
// with the small page below instead of the browser's own error page.
//
// It stores nothing. There is no offline mode (docs/product/PRD-multi-device.md, 3.2): a deadline
// read from an old copy could be wrong, so no page and no API response is ever kept, and the page
// below is a string in this file rather than an entry in a cache. Requests under /api, requests to
// other origins, and everything that is not a page navigation (scripts, styles, data, uploads) are
// left to the browser untouched.
//
// A release replaces it at once: the browser re-fetches this file on every navigation (it is served
// with `Cache-Control: no-cache`, web/next.config.ts), and a changed copy skips waiting and takes
// over the open pages. Since it holds no pages, there is no old shell for it to keep serving.
// lib/pwa.test.ts runs this file against a stand-in for `self`.

// Tokens as in app/globals.css; the theme is the one the settings last applied (lib/pwa.ts,
// APPEARANCE_KEY), read the same way as components/shell/ThemeScript.tsx.
const OFFLINE_PAGE = `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#121a28">
<meta name="robots" content="noindex">
<title>连不上服务器 · 鱼跃彼岸</title>
<script>(function(){try{var m=localStorage.getItem("leapashore:appearance");var d=m==="dark"||(m!=="light"&&matchMedia("(prefers-color-scheme: dark)").matches);document.documentElement.dataset.appearance=d?"dark":"light";document.querySelector('meta[name="theme-color"]').content=d?"#090c12":"#121a28"}catch(e){}})()</script>
<style>
:root { color-scheme: light; --rail: #121a28; --rail-ink: #f2f5f9; --rail-ink-2: #aab5c6; --bg: #ffffff; --ink: #111722; --ink-2: #485263; --action: #111722; --action-hover: #2a3445; --on-action: #ffffff; --mark: #ffe680; --mark-ink: #4d3a00; }
html[data-appearance="dark"] { color-scheme: dark; --rail: #090c12; --rail-ink: #eef1f6; --rail-ink-2: #9ea9ba; --bg: #10141b; --ink: #eef1f6; --ink-2: #b6bfcd; --action: #eef1f6; --action-hover: #ffffff; --on-action: #10141b; --mark: #6b5400; --mark-ink: #ffe48a; }
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; text-size-adjust: 100%; }
body { margin: 0; min-height: 100vh; min-height: 100dvh; background: var(--bg); color: var(--ink); font: 400 0.875rem/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "HarmonyOS Sans SC", "MiSans", "Microsoft YaHei UI", "Microsoft YaHei", "Noto Sans SC", "Noto Sans CJK SC", sans-serif; -webkit-font-smoothing: antialiased; }
::selection { background: var(--mark); color: var(--mark-ink); }
:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }
.rail { position: fixed; inset: 0 auto 0 0; display: flex; align-items: flex-start; gap: 10px; width: calc(236px + env(safe-area-inset-left, 0px)); padding: calc(20px + env(safe-area-inset-top, 0px)) 20px 20px calc(20px + env(safe-area-inset-left, 0px)); background: var(--rail); color: var(--rail-ink); }
.rail b { display: block; font-size: 1rem; font-weight: 600; line-height: 1.25; letter-spacing: 0.04em; }
.rail span { display: block; font-size: 0.75rem; line-height: 1.3; color: var(--rail-ink-2); }
main { margin-left: calc(236px + env(safe-area-inset-left, 0px)); padding: calc(28px + env(safe-area-inset-top, 0px)) calc(28px + env(safe-area-inset-right, 0px)) 56px 28px; }
h1 { margin: 0; font-size: 1.5rem; font-weight: 600; line-height: 1.25; letter-spacing: -0.01em; }
p { margin: 6px 0 0; max-width: 34em; color: var(--ink-2); }
button { height: 32px; margin-top: 24px; padding: 0 12px; border: 0; border-radius: 6px; background: var(--action); color: var(--on-action); font-family: inherit; font-size: 0.8125rem; font-weight: 500; line-height: 1; cursor: pointer; }
button:hover { background: var(--action-hover); }
button:active { transform: translateY(1px); }
@media (max-width: 900px) {
  .rail { inset: 0 0 auto 0; align-items: center; width: auto; height: calc(48px + env(safe-area-inset-top, 0px)); padding: env(safe-area-inset-top, 0px) calc(16px + env(safe-area-inset-right, 0px)) 0 calc(16px + env(safe-area-inset-left, 0px)); }
  .rail svg { width: 24px; height: 24px; }
  .rail span { display: none; }
  main { margin-left: 0; padding: calc(68px + env(safe-area-inset-top, 0px)) calc(16px + env(safe-area-inset-right, 0px)) 32px calc(16px + env(safe-area-inset-left, 0px)); }
  h1 { font-size: 1.375rem; }
  button { height: 36px; }
}
@media (prefers-reduced-motion: reduce) { button:active { transform: none; } }
</style>
</head>
<body>
<header class="rail">
<svg width="28" height="28" viewBox="0 0 28 28" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true"><path d="M3.5 22C4 10.5 13 5 19.5 12.8"/><path d="M11 22.5h14"/><circle cx="20.5" cy="16.2" r="3.1" fill="var(--rail)"/></svg>
<div><b>鱼跃彼岸</b><span>LeapAshore</span></div>
</header>
<main>
<h1>现在连不上服务器</h1>
<p>可能是这台设备断网了，也可能是服务器一时没有响应。</p>
<p>鱼跃彼岸不保存离线副本，截止日期和申请记录要连上以后才能看。</p>
<button type="button" id="retry">重试</button>
</main>
<script>document.getElementById("retry").addEventListener("click",function(){location.reload()});addEventListener("online",function(){location.reload()})</script>
</body>
</html>
`;

self.addEventListener("install", (event) => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET" || request.mode !== "navigate") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname === "/api" || url.pathname.startsWith("/api/")) return;
  event.respondWith(
    fetch(request).catch(
      () =>
        new Response(OFFLINE_PAGE, {
          status: 503,
          headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" },
        }),
    ),
  );
});
