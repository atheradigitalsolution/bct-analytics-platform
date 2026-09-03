import "server-only";

import { Pool } from "pg";

/**
 * Pricing CMS — the console's write half over `tenant_registry.plans`.
 *
 * Prices live in ONE place: the registry. The public landing reads them
 * through the `cms.published_plan` view under `marketing_site_reader`, which
 * has no grant on the base table — so the landing can never write, and the
 * console is the only editor. This module reuses the CMS pool, which connects
 * as `tenant_orchestrator`; that role already holds UPDATE on
 * `tenant_registry.plans` and INSERT on `tenant_registry.action_log`, so no
 * new grant is introduced here.
 *
 * Every price change writes an `action_log` row in the SAME transaction as the
 * update. That is deliberate: the registry state has been mutated in the past
 * without an audit trail, and pricing is exactly the kind of change that must
 * never happen silently.
 *
 * The product vocabulary (`insight|odoo|agent`) and the set of plans are frozen
 * by contract 07 and by a CHECK constraint — this editor touches only
 * `price_month`, `currency`, and `is_active`, never `products`.
 */

const globalForPool = globalThis as unknown as { hub_pricing_pool?: Pool };

function pool(): Pool {
  if (!globalForPool.hub_pricing_pool) {
    const connectionString = process.env.HUB_PORTAL_CMS_DSN;
    if (!connectionString) throw new Error("HUB_PORTAL_CMS_DSN is not set");
    globalForPool.hub_pricing_pool = new Pool({
      connectionString,
      max: Number(process.env.HUB_PORTAL_POOL_MAX ?? 4),
      connectionTimeoutMillis: 5000,
    });
  }
  return globalForPool.hub_pricing_pool;
}

export interface Plan {
  code: string;
  display_name: string;
  products: string[];
  price_month: string | null; // numeric(14,2) — pg returns string; null = custom / "Hubungi kami"
  currency: string;
  is_active: boolean;
}

export async function listPlans(): Promise<Plan[]> {
  const { rows } = await pool().query<Plan>(
    `SELECT code, display_name, products, price_month, currency, is_active
       FROM tenant_registry.plans
      ORDER BY code`,
  );
  return rows;
}

export class PricingError extends Error {}

/**
 * Set a plan's monthly price. `priceMonth === null` means custom ("Hubungi
 * kami"). A non-null price must be a finite, non-negative number. Update and
 * audit row commit together, or not at all.
 */
export async function setPlanPrice(
  code: string,
  priceMonth: number | null,
  currency: string,
  actor: string,
): Promise<void> {
  if (!/^[a-z][a-z0-9_]{1,31}$/.test(code)) throw new PricingError("invalid_plan_code");
  if (priceMonth !== null && (!Number.isFinite(priceMonth) || priceMonth < 0)) {
    throw new PricingError("invalid_price");
  }
  if (!/^[A-Z]{3}$/.test(currency)) throw new PricingError("invalid_currency");

  const client = await pool().connect();
  try {
    await client.query("BEGIN");
    const upd = await client.query(
      `UPDATE tenant_registry.plans
          SET price_month = $2, currency = $3
        WHERE code = $1
      RETURNING code`,
      [code, priceMonth, currency],
    );
    if (upd.rowCount === 0) {
      await client.query("ROLLBACK");
      throw new PricingError("unknown_plan");
    }
    await client.query(
      `INSERT INTO tenant_registry.action_log (action, actor, outcome, detail)
       VALUES ('plan_price_set', $1, 'success',
               jsonb_build_object('plan', $2::text, 'price_month', $3::numeric,
                                  'currency', $4::text, 'via', 'hub-portal'))`,
      [actor, code, priceMonth, currency],
    );
    await client.query("COMMIT");
  } catch (e) {
    try { await client.query("ROLLBACK"); } catch { /* ignore */ }
    throw e;
  } finally {
    client.release();
  }
}
