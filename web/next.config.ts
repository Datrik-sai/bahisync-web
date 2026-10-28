import type { NextConfig } from "next";

// The browser talks to /api/* on the same origin; Next forwards it to the
// Python engine. Set BAHISYNC_API_URL in production (e.g. https://api.bahisync.in).
const API_URL = process.env.BAHISYNC_API_URL || "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/api/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        ],
      },
    ];
  },
};

export default nextConfig;
