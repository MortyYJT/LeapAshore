import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // The browser reaches the API through this origin, so the httpOnly `offerpilot_client` cookie is
  // same-origin and no CORS or credentials plumbing is needed. The cost is that the backend must be
  // running: `make dev` starts both, and `screenshots` refuses to drive the browser without it.
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
};

export default nextConfig;
