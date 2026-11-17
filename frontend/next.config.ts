import type { NextConfig } from "next";

const backendUrl = (process.env.BACKEND_URL || "http://127.0.0.1:8000").replace(
  /\/$/,
  "",
);
const config: NextConfig = {
  // Next's proxy body buffer must exceed the backend file limit plus multipart overhead.
  experimental: { proxyClientMaxBodySize: "12mb" },
  async rewrites() {
    return [
      { source: "/api/v1/:path*", destination: `${backendUrl}/api/v1/:path*` },
    ];
  },
};
export default config;
