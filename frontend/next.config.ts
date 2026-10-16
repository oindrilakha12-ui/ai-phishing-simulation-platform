import type { NextConfig } from "next";

// The browser only ever talks to this Next.js origin. /api/* is proxied to FastAPI, so auth
// cookies are first-party and CORS isn't needed in normal use.
const BACKEND_URL = process.env.BACKEND_URL ?? "http://127.0.0.1:8001";
const isDev = process.env.NODE_ENV !== "production";

// Content-Security-Policy for the app shell. Note: the email preview iframe uses `srcdoc`
// with `sandbox` (no scripts) AND carries its own stricter CSP meta tag.
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self' data:",
  "connect-src 'self'",
  "frame-src 'self'",
  "frame-ancestors 'none'",
  "form-action 'self'",
  "base-uri 'self'",
  "object-src 'none'",
].join("; ");

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  async rewrites() {
    return [
      { source: "/api/v1/:path*", destination: `${BACKEND_URL}/api/v1/:path*` },
      { source: "/health/:path*", destination: `${BACKEND_URL}/health/:path*` },
    ];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Content-Security-Policy", value: csp },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
};

export default nextConfig;
