import "server-only";

import { Pool } from "pg";

/**
 * The landing's price source: the registry, read through the
 * `cms.published_plan` view under `marketing_site_reader`. That role has SELECT
 * on the view and NO grant on `tenant_registry.plans` — so this site can read
 * the published price catalogue and can never write it, and there is no query
 * this file could be made to run that reaches a tenant row. Prices are edited
 * only in the hub-portal console; here they are read-only.
 *
 * A null `price_month` means the plan is sold as custom — the card shows
 * "Hubungi kami", never a number.
 */

const globalForPool = globalThis as unknown as { athera_pricing_pool?: Pool };

function pool(): Pool {
  if (!globalForPool.athera_pricing_pool) {
    const connectionString = process.env.MARKETING_SITE_DSN;
    if (!connectionString) throw new Error("MARKETING_SITE_DSN is not set");
    globalForPool.athera_pricing_pool = new Pool({
      connectionString,
      max: Number(process.env.MARKETING_SITE_PRICING_POOL_MAX ?? 2),
      connectionTimeoutMillis: 5000,
      idleTimeoutMillis: 30000,
    });
  }
  return globalForPool.athera_pricing_pool;
}

export interface PublishedPlan {
  code: string;
  display_name: string;
  products: string[];
  price_month: string | null;
  currency: string;
}

export async function getPublishedPlans(): Promise<PublishedPlan[]> {
  const { rows } = await pool().query<PublishedPlan>(
    `SELECT code, display_name, products, price_month, currency
       FROM cms.published_plan
      ORDER BY code`,
  );
  return rows;
}

export function planByCode(plans: PublishedPlan[], code: string): PublishedPlan | undefined {
  return plans.find((p) => p.code === code);
}

export function formatPrice(price: string | null, currency: string): string {
  if (price === null) return "Hubungi kami";
  const n = Number(price);
  if (n === 0) return "Gratis";
  return new Intl.NumberFormat("id-ID", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(n);
}
