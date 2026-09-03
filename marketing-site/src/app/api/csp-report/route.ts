import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const MAX_BYTES = 16 * 1024; // anti-abuse: CSP reports are tiny; reject anything large.

/**
 * CSP violation collector. Zero new infrastructure: it logs one structured JSON
 * line to STDOUT (the container log), which promtail already scrapes into Loki.
 * No file is written, nothing is echoed back to the browser, and the report is
 * never stored anywhere this endpoint can be made to read from.
 *
 * Accepts both wire formats:
 *   - report-uri (legacy):     Content-Type: application/csp-report
 *                              body: {"csp-report": {...}}
 *   - Reporting API (report-to): Content-Type: application/reports+json
 *                              body: [{"type":"csp-violation","body":{...}}, ...]
 *
 * Always answers 204 fast. Cross-origin report beacons need no CORS to be
 * delivered, so no preflight handling is required.
 */
function logViolation(host: string, r: Record<string, unknown>): void {
  // Field names differ slightly between the two formats; read both.
  const g = (a: string, b: string) => r[a] ?? r[b] ?? null;
  const line = {
    kind: "csp-report",
    host,
    blocked_uri: g("blocked-uri", "blockedURL"),
    violated_directive: g("violated-directive", "effectiveDirective") ?? r["disposition"] ?? null,
    document_uri: g("document-uri", "documentURL"),
    ts: new Date().toISOString(),
  };
  // One line to stdout -> container log -> promtail -> Loki.
  console.log(JSON.stringify(line));
}

export async function POST(request: Request): Promise<NextResponse> {
  const len = Number(request.headers.get("content-length") ?? "0");
  if (len > MAX_BYTES) return new NextResponse(null, { status: 413 });

  const text = await request.text();
  if (text.length > MAX_BYTES) return new NextResponse(null, { status: 413 });

  const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host") ?? "unknown";

  try {
    const parsed = JSON.parse(text);
    if (Array.isArray(parsed)) {
      // Reporting API: array of reports; keep only csp-violation entries.
      for (const rep of parsed) {
        const body = rep && typeof rep === "object" ? (rep.body ?? rep) : {};
        if (!rep?.type || rep.type === "csp-violation") logViolation(host, body as Record<string, unknown>);
      }
    } else if (parsed && typeof parsed === "object") {
      // report-uri: single {"csp-report": {...}}
      const body = (parsed["csp-report"] ?? parsed) as Record<string, unknown>;
      logViolation(host, body);
    }
  } catch {
    // Malformed report: count it, do not fail loudly.
    console.log(JSON.stringify({ kind: "csp-report", host, error: "unparseable", ts: new Date().toISOString() }));
  }
  return new NextResponse(null, { status: 204 });
}
