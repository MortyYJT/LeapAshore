import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
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
