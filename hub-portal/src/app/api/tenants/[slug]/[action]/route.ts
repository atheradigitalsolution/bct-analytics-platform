import { NextResponse } from "next/server";

import { absolute } from "@/lib/redirect";
import { call } from "@/lib/orchestrator";
import { getSession } from "@/lib/session";

export const dynamic = "force-dynamic";

/**
 * The lifecycle buttons, and nothing else.
 *
 * `action` comes out of the URL, so it is matched against a FIXED TABLE rather
 * than interpolated into a path. Without that, `/api/tenants/x/../../whatever`
 * would let the browser choose which orchestrator endpoint this signs for —
 * and it signs with the shared secret, so it would be an oracle for calling
 * anything the orchestrator exposes.
 *
 * `body` is a FUNCTION of the submitted form, not a constant, because `extend`
 * carries operator input. The other three keep fixed bodies: there is nothing
 * for a person to say about "resume".
 */
type Spec = {
  method: string;
  path: (s: string) => string;
  body: (form: FormData) => unknown;
};

const ACTIONS: Record<string, Spec> = {
  suspend: {
    method: "POST",
    path: (s) => `/v1/tenants/${s}/suspend`,
    body: () => ({ reason: "suspended from the console" }),
  },
  resume: { method: "POST", path: (s) => `/v1/tenants/${s}/resume`, body: () => ({}) },
  archive: {
    method: "DELETE",
    path: (s) => `/v1/tenants/${s}`,
    body: () => ({ retention_days: 30 }),
  },
  /**
   * Access time granted outside the invoice cycle.
   *
   * WHY THIS BUTTON EXISTS. `valid_until` moved in exactly one way before now:
   * an invoice was paid. An operator who had to grant access without a payment —
   * a pilot, a goodwill week, an invoice under dispute — had nothing to click,
   * and the only thing within reach was to record a payment that never happened.
   * The missing button did not prevent that; it pushed it into the ledger.
   *
   * The values are passed through rather than validated here. The orchestrator
   * bounds both `days` and `reason` and is the layer that actually protects the
   * column; re-checking here would create a second set of rules to keep in step,
   * and the one that matters would still be the far one.
   */
  extend: {
    method: "POST",
    path: (s) => `/v1/tenants/${s}/extend`,
    body: (form) => ({
      days: Number(form.get("days") ?? 0),
      reason: String(form.get("reason") ?? ""),
    }),
  },
};

const SLUG_RE = /^[a-z][a-z0-9_]{1,30}$/;

export async function POST(
  request: Request,
  { params }: { params: Promise<{ slug: string; action: string }> },
) {
  const { slug, action } = await params;
  const spec = ACTIONS[action];
  if (!spec || !SLUG_RE.test(slug)) {
    return NextResponse.json({ error: "invalid_request" }, { status: 400 });
  }

  // Read once. `request.formData()` consumes the body, and a second call throws.
  let form = new FormData();
  try {
    form = await request.formData();
  } catch {
    // No body, which is the normal case for the three fixed actions.
  }

  // The actor reaches the orchestrator's append-only action log, so "who
  // suspended this client" names a person rather than this service.
  const session = await getSession();
  const actor = session?.sub ?? "hub-portal";

  const { status, data } = await call(spec.method, spec.path(slug), spec.body(form), actor);
  const url = await absolute(`/tenants/${slug}`);
  if (status >= 400) {
    url.searchParams.set("error", String(status));
    // The orchestrator's refusals are sentences meant for a person — "say why in
    // a sentence someone can read later". Dropping that on the floor and showing
    // a bare 400 would make a well-explained refusal indistinguishable from an
    // outage, which is the failure this whole wave has been about.
    const detail = (data as { detail?: unknown } | null)?.detail;
    if (typeof detail === "string") url.searchParams.set("detail", detail.slice(0, 300));
  }
  return NextResponse.redirect(url, { status: 303 });
}
