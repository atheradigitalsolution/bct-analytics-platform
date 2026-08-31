import type { NextConfig } from "next";

/**
 * `output: "standalone"` is what makes the Docker image small and lets the runtime stage run as a
 * non-root user with no node_modules tree to own.
 *
 * The headers below are defence in depth, not the control: the session cookie is httpOnly and
 * SameSite=Strict, and no credential ever reaches the browser. CSP is set without `unsafe-eval`;
 * `unsafe-inline` is required for the style attributes Recharts emits and for Next's inline
 * bootstrap script in dev. Security owns the final CSP; this is a starting point, not a claim.
 */
const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  reactStrictMode: true,
  compress: true,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=(), payment=()",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
