import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // A server-rendered route (the school list with its filters, a school, a program, the admin's desk)
  // that was opened in the last five minutes is drawn from the router's memory when the visitor comes
  // back to the same address, with no request. Next's default for these is 0: every return re-rendered
  // the page on the server and showed the placeholder meanwhile. What they show is the catalogue, which
  // changes when an admin imports or confirms a page; a visitor sees such a change within five minutes or
  // on a reload, and the two things that change it from this browser (an admin's confirm or withdraw,
  // and signing in or out) call `router.refresh()`, which empties that memory. The applicant's own data
  // never comes from these routes; it is read in the browser and kept in lib/resource-cache.ts.
  experimental: { staleTimes: { dynamic: 300 } },
  // The browser reaches the API through this origin, so the httpOnly `leapashore_client` cookie is
  // same-origin and no CORS or credentials plumbing is needed. The cost is that the backend must be
  // running: `make dev` starts both, and `screenshots` refuses to drive the browser without it.
  // The assessment page was removed (openspec account-login): its four facts are asked after the first
  // registration, the rest live on 我的, and the result page moved to /tiers.
  async redirects() {
    return [
      { source: "/assess", destination: "/tiers", permanent: false },
      { source: "/assess/result", destination: "/tiers", permanent: false },
    ];
  },
  // The service worker must never be served from a cache: a release has to replace it on the next
  // visit (public/sw.js). `Service-Worker-Allowed` is not needed, since it sits at the root.
  async headers() {
    return [{ source: "/sw.js", headers: [{ key: "Cache-Control", value: "no-cache, no-store, must-revalidate" }] }];
  },
  // Next gzips what it proxies and holds a streamed body back until it has a full block, so the
  // advisor's events reached the browser all at once in development. Compression is the proxy's job
  // in production anyway (deploy/Caddyfile: `encode gzip`), where /api never passes through Next.
  compress: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: "http://127.0.0.1:8000/api/:path*" }];
  },
  // A lockfile also exists in a parent directory; pin the workspace root so Next does not guess.
  turbopack: {
    root: __dirname,
  },
  // The dev server only trusts `localhost` by default. Opening the app through 127.0.0.1 or a LAN
  // address makes Next block its own dev assets and the HMR socket, so React never hydrates and the
  // page renders but no control responds. Entries match the hostname only: no scheme, no port.
  allowedDevOrigins: ["127.0.0.1", "10.139.217.141"],
  // Next takes ownership of its output directory and deletes parts of it. When `next build` and
  // `next dev` shared `.next`, running the build check while the dev server was up wiped the server's
  // chunks: the page still rendered from HTML and CSS but never hydrated, so every control was dead
  // with no visible error. `make build` now points the build at its own directory.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  // The production image runs the self-contained server Next emits under .next/standalone, so the
  // runtime layer needs no node_modules. Opt-in, so local builds keep their usual layout.
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
};

export default nextConfig;
