import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Pin tracing to this package because the parent directory has another lockfile.
  outputFileTracingRoot: process.cwd(),
  turbopack: { root: process.cwd() },
};

export default nextConfig;
