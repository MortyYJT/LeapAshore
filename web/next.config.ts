import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // A lockfile also exists in a parent directory; pin the workspace root so Next does not guess.
  turbopack: {
    root: __dirname,
  },
  // The dev server only trusts `localhost` by default. Opening the app through 127.0.0.1 or a LAN
  // address makes Next block its own dev assets and the HMR socket, so React never hydrates and the
  // page renders but no control responds. Entries match the hostname only: no scheme, no port.
  allowedDevOrigins: ["127.0.0.1", "10.139.217.141"],
};

export default nextConfig;
