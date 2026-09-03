import "server-only";

import { Pool } from "pg";

/**
 * Penagihan, dibaca lewat SATU view.
 *
 * Portal ini tersambung sebagai `tenant_orchestrator` — role hak-minimal untuk `tenant_registry`.
 * Ia TIDAK punya grant apa pun pada tabel Odoo; yang diberikan hanya SELECT pada
 * `billing.subscription_overview`, yang dibuat dan di-grant oleh modul `custom_athera_billing`
 * (models/billing_overview.py). Pola yang sama dengan `cms.published_plan` untuk harga.
 *
 * HALAMAN INI BACA-SAJA, DAN ITU DISENGAJA. Menerbitkan faktur, mencatat pembayaran, dan
 * menangguhkan klien punya akibat akuntansi dan hukum; jalurnya adalah konsol Odoo, yang sudah
 * membawa jurnal, pajak, dan jejak auditnya. Menyalin tombol-tombol itu ke sini berarti dua jalan
 * menuju satu perbuatan, dan yang kedua tidak akan pernah selengkap yang pertama.
 */

const globalForPool = globalThis as unknown as { hub_billing_pool?: Pool };

function pool(): Pool {
  if (!globalForPool.hub_billing_pool) {
    const connectionString = process.env.HUB_PORTAL_CMS_DSN;
    if (!connectionString) throw new Error("HUB_PORTAL_CMS_DSN is not set");
    globalForPool.hub_billing_pool = new Pool({
      connectionString,
      max: Number(process.env.HUB_PORTAL_POOL_MAX ?? 4),
      connectionTimeoutMillis: 5000,
    });
  }
  return globalForPool.hub_billing_pool;
}

export interface BillingRow {
  tenant_slug: string;
  display_name: string | null;
  plan_code: string | null;
  subscription_state: string;
  tenant_state: string | null;
  valid_until: Date | null;
  next_invoice_date: Date | null;
  price_month: string | null;
  currency: string | null;
  invoice_count: number;
  open_invoice_count: number;
  outstanding: string;
  last_invoice_date: Date | null;
  oldest_due_date: Date | null;
}

export async function listBilling(): Promise<BillingRow[]> {
  const { rows } = await pool().query<BillingRow>(
    `SELECT tenant_slug, display_name, plan_code, subscription_state, tenant_state,
            valid_until, next_invoice_date, price_month, currency,
            invoice_count, open_invoice_count, outstanding,
            last_invoice_date, oldest_due_date
       FROM billing.subscription_overview
      ORDER BY open_invoice_count DESC, tenant_slug`,
  );
  return rows;
}
