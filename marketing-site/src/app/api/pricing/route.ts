import { NextResponse } from "next/server";

import { getPublishedPlans } from "@/lib/pricing";

export const dynamic = "force-dynamic";

/**
 * Public, read-only pricing API. Single source of truth is the registry
 * (`tenant_registry.plans`), read here through the `cms.published_plan` view
 * under `marketing_site_reader` — a role that cannot write and cannot reach a
 * tenant row. Any app's pricing page (insight., the odoo. edge view) reads
 * prices from here, so there is exactly one place prices live and one place
 * they are edited (hub-portal). Never returns tenant data — only the plan
 * catalogue.
 */
export async function GET() {
  const plans = await getPublishedPlans();
  return NextResponse.json(
    { plans },
    { headers: { "Cache-Control": "public, max-age=60, stale-while-revalidate=300" } },
  );
}
