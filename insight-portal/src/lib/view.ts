import "server-only";

import { cookies } from "next/headers";

import { config } from "./config";
import { parseFilters, type PortalFilters } from "./filters";

/** The persisted filter for this request. */
export async function loadFilters(): Promise<PortalFilters> {
  const jar = await cookies();
  return parseFilters(jar.get(config.filtersCookieName)?.value);
}

/**
 * What a view needs in order to be worth offering to a tenant.
 *
 * `metric` and `dimension` are both declared names from contract 03; the probe in
 * `lib/capabilities.ts` sends them through `/v1/query` like any panel, so a view is offered when
 * the semantic layer returns at least one group for this session and hidden when it returns none.
 * Nothing here names a tenant, an industry or a plan.
 */
export interface ViewAnchor {
  metric: string;
  /** A declared dimension of `metric`. Grouping is what makes "no rows" mean "no rows". */
  dimension: string;
}

export interface ViewDef {
  slug: string;
  label: string;
  /**
   * Absent means the view is part of every tenant's dashboard and is rendered unconditionally.
   * Present means the view answers a question only some tenants have, and is offered only when
   * that tenant's own data can answer it.
   */
  anchor?: ViewAnchor;
}

/**
 * Every view this application can render, and the condition under which each is offered.
 *
 * WHY THIS IS NOT A FLAT LIST ANY MORE. It was, and the result was a feed mill logging in to a
 * dashboard whose navigation offered "Operasi PPOB" and whose Ringkasan Eksekutif led with two
 * PPOB figures. `mart_ppob_transaction` holds no rows for that tenant, so the figures were zero
 * and the tab was empty — the dashboard was not showing anyone else's data, it was asserting that
 * PPOB is a thing this client does. Reported as "Insight NDI menampilkan data PPOB", which is
 * exactly how it reads from the outside.
 *
 * WHY IT IS PROBED RATHER THAN CONFIGURED. The obvious fix is a per-tenant list of views, or a
 * `vertical` column somewhere. Both put the answer in a second place that has to be remembered:
 * onboarding a client would silently mean "and also add them to the view map", and the failure of
 * forgetting is invisible — the client simply never sees a view their data would have filled. The
 * warehouse already knows which marts hold rows for a tenant, so that is what is asked.
 *
 * The consequence is deliberate and worth stating: a tenant that starts selling PPOB gets the tab
 * on its own, and one that stops loses it. See `CAPABILITY_TTL_SECONDS` for how long that takes.
 */
export const VIEW_CATALOGUE: readonly ViewDef[] = [
  { slug: "overview", label: "Ringkasan Eksekutif" },
  { slug: "sales", label: "Penjualan" },
  { slug: "inventory", label: "Persediaan" },
  { slug: "finance", label: "Keuangan" },
  {
    slug: "pricing",
    label: "Harga & Margin",
    anchor: { metric: "sales_by_price_tier", dimension: "hj_level" },
  },
  {
    slug: "ppob",
    label: "Operasi PPOB",
    anchor: { metric: "ppob_transaction_count", dimension: "date_month" },
  },
] as const;

export function viewDef(slug: string): ViewDef | undefined {
  return VIEW_CATALOGUE.find((view) => view.slug === slug);
}
