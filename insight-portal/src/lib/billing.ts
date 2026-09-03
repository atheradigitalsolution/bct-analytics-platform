import "server-only";

import { Pool, type PoolClient } from "pg";

import type { Session } from "./claims";

/**
 * Penagihan sisi klien — satu-satunya tempat portal ini menyentuh database secara langsung.
 *
 * KENAPA BUKAN LEWAT `semantic-api`. Itu jalur contract 03 untuk mart, dan faktur ATHERA kepada
 * kliennya tidak pernah ada di mart: CDC memberi makan dari database KLIEN (`bct`, `acme`), bukan
 * dari `athera_admin` tempat pembukuan ATHERA sendiri hidup. Tidak ada mart yang bisa membawanya.
 * Memaksanya lewat CDC -> dbt juga menambah basi hingga satu jam pada status pembayaran, dan
 * "apakah pembayaran saya sudah masuk" adalah pertanyaan yang tidak boleh dijawab dengan data
 * satu jam lalu.
 *
 * KENAPA INI TIDAK MELANGGAR "dashboard tidak boleh menembus Odoo". Aturan itu mengatur jalur
 * ANALITIK atas data klien — volume besar, butuh masking dan RLS. Ini jalur control-plane atas
 * catatan ATHERA sendiri: tiga baris per tenant. Pola yang sama sudah dipakai `hub-portal`
 * (billing.subscription_overview) dan `marketing-site` (cms.published_plan).
 *
 * TENANT TIDAK PERNAH MENJADI ARGUMEN STRING. Setiap fungsi di sini menerima `Session`, dan
 * `Session` hanya bisa lahir dari `verifyToken()`. Tidak ada jalan bagi sebuah string dari URL,
 * header, atau body untuk sampai ke sini — itu bentuk yang sama dengan `lib/semantic.ts`, yang
 * tidak menerima argumen tenant sama sekali.
 */

const globalForPool = globalThis as unknown as { insight_billing_pool?: Pool };

function pool(): Pool {
  if (!globalForPool.insight_billing_pool) {
    const connectionString = process.env.INSIGHT_PORTAL_BILLING_DSN;
    if (!connectionString) throw new Error("INSIGHT_PORTAL_BILLING_DSN is not set");
    globalForPool.insight_billing_pool = new Pool({
      connectionString,
      max: Number(process.env.INSIGHT_PORTAL_BILLING_POOL_MAX ?? 4),
      connectionTimeoutMillis: 5000,
      idleTimeoutMillis: 30_000,
    });
  }
  return globalForPool.insight_billing_pool;
}

/**
 * Jalankan sesuatu dengan konteks tenant terpasang di sesi database.
 *
 * `set_config(..., true)` — parameter ketiga `is_local` — berarti nilainya hilang saat transaksi
 * berakhir, jadi koneksi yang kembali ke pool tidak pernah membawa tenant sebelumnya. Sebuah
 * kebocoran di sini akan terlihat seperti klien melihat faktur klien lain secara acak di bawah
 * beban, yaitu bug yang paling sulit dipercaya saat dilaporkan.
 *
 * `set_config` DAN BUKAN `SET LOCAL`: Postgres tidak menerima parameter terikat pada `SET`, jadi
 * `SET LOCAL athera.tenant_slug = '${slug}'` adalah satu-satunya bentuk yang mungkin — dan itu
 * berarti menyusun SQL dari sebuah nilai. `set_config($1, ...)` menerima parameter terikat.
 */
async function withTenant<T>(session: Session, fn: (c: PoolClient) => Promise<T>): Promise<T> {
  const client = await pool().connect();
  try {
    await client.query("BEGIN");
    await client.query("SELECT set_config('athera.tenant_slug', $1, true)", [session.tenant_id]);
    const result = await fn(client);
    await client.query("COMMIT");
    return result;
  } catch (error) {
    await client.query("ROLLBACK").catch(() => undefined);
    throw error;
  } finally {
    client.release();
  }
}

export interface InvoiceRow {
  id: number;
  tenant_slug: string;
  invoice_number: string;
  invoice_date: Date | null;
  invoice_date_due: Date | null;
  amount_untaxed: string;
  amount_tax: string;
  amount_total: string;
  amount_residual: string;
  currency: string | null;
  client_status: "paid" | "overdue" | "posted";
}

export interface SubscriptionRow {
  tenant_slug: string;
  display_name: string | null;
  plan_code: string | null;
  subscription_state: string;
  tenant_state: string | null;
  valid_until: Date | null;
  next_invoice_date: Date | null;
  price_month: string | null;
  currency: string | null;
  sisa_hari: number | null;
}

export interface ClaimRow {
  id: number;
  invoice_number: string | null;
  amount: string;
  paid_on: Date | null;
  bank_name: string | null;
  reference: string | null;
  state: string;
  create_date: Date | null;
}

/**
 * `WHERE tenant_slug = $1` di sini TIDAK berlebihan meski view sudah menyaring dirinya sendiri.
 * Itu pagar kedua, dan keduanya dilepas satu per satu dalam uji untuk membuktikan masing-masing
 * benar-benar menahan sesuatu. Pagar yang tidak pernah diuji dengan cara dilepas adalah pagar
 * yang tidak diketahui masih terpasang.
 */
export async function listInvoices(session: Session): Promise<InvoiceRow[]> {
  return withTenant(session, async (c) => {
    const { rows } = await c.query<InvoiceRow>(
      `SELECT id, tenant_slug, invoice_number, invoice_date, invoice_date_due,
              amount_untaxed, amount_tax, amount_total, amount_residual,
              currency, client_status
         FROM billing.tenant_invoice
        WHERE tenant_slug = $1
        ORDER BY invoice_date DESC NULLS LAST, id DESC`,
      [session.tenant_id],
    );
    return rows;
  });
}

/** `null` untuk faktur yang tidak ada MAUPUN faktur milik tenant lain — pemanggil tidak belajar bedanya. */
export async function getInvoice(session: Session, id: number): Promise<InvoiceRow | null> {
  if (!Number.isInteger(id) || id <= 0) return null;
  return withTenant(session, async (c) => {
    const { rows } = await c.query<InvoiceRow>(
      `SELECT id, tenant_slug, invoice_number, invoice_date, invoice_date_due,
              amount_untaxed, amount_tax, amount_total, amount_residual,
              currency, client_status
         FROM billing.tenant_invoice
        WHERE tenant_slug = $1 AND id = $2`,
      [session.tenant_id, id],
    );
    return rows[0] ?? null;
  });
}

export async function getSubscription(session: Session): Promise<SubscriptionRow | null> {
  return withTenant(session, async (c) => {
    const { rows } = await c.query<SubscriptionRow>(
      `SELECT tenant_slug, display_name, plan_code, subscription_state, tenant_state,
              valid_until, next_invoice_date, price_month, currency, sisa_hari
         FROM billing.tenant_subscription
        WHERE tenant_slug = $1`,
      [session.tenant_id],
    );
    return rows[0] ?? null;
  });
}

export async function listClaims(session: Session): Promise<ClaimRow[]> {
  return withTenant(session, async (c) => {
    const { rows } = await c.query<ClaimRow>(
      `SELECT id, invoice_number, amount, paid_on, bank_name, reference, state, create_date
         FROM billing.tenant_payment_claim
        WHERE tenant_slug = $1
        ORDER BY id DESC`,
      [session.tenant_id],
    );
    return rows;
  });
}

export interface ClaimInput {
  invoiceId: number;
  invoiceNumber: string;
  amount: number;
  paidOn: string;
  bankName: string;
  reference: string;
  note: string;
}

/**
 * Catat "klien mengaku sudah bayar". SATU-SATUNYA tulisan yang portal ini boleh lakukan.
 *
 * Perhatikan apa yang TIDAK dilakukan: tidak menyentuh `account_move`, tidak mengubah
 * `payment_state`, tidak memperpanjang `valid_until`. Klaim adalah pesan kepada operator, bukan
 * pembayaran. Role database yang dipakai portal memang tidak punya hak untuk melakukan yang lain,
 * jadi ini bukan sekadar janji kode — ia batas yang ditegakkan Postgres.
 *
 * `tenant_slug` dikirim apa adanya dan SENGAJA diabaikan oleh trigger `force_claim_tenant`, yang
 * menimpanya dengan GUC. Kalau baris ini suatu hari salah tulis, database yang membetulkannya.
 */
export async function recordClaim(session: Session, input: ClaimInput): Promise<void> {
  await withTenant(session, async (c) => {
    /**
     * TANPA `RETURNING`, dan itu bukan penyederhanaan.
     *
     * `INSERT ... RETURNING id` menuntut hak SELECT pada tabel, dan memberikannya berarti role
     * portal bisa membaca — atau setidaknya menghitung — klaim milik tenant lain. Ditemukan saat
     * uji ujung-ke-ujung menjawab "gagal simpan" dengan grant yang justru sudah benar: yang salah
     * adalah kuerinya, yang meminta lebih dari yang perlu. Portal tidak memakai id itu; ia
     * mengarahkan klien kembali ke daftar tagihan.
     */
    const result = await c.query(
      `INSERT INTO athera_payment_claim
         (tenant_slug, invoice_id, invoice_number, amount, paid_on, bank_name, reference, note,
          claimed_by_uid, state, create_date, write_date)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'new', now(), now())`,
      [
        session.tenant_id, input.invoiceId, input.invoiceNumber, input.amount,
        input.paidOn, input.bankName, input.reference, input.note, session.odoo_uid,
      ],
    );
    if (result.rowCount !== 1) throw new Error("klaim tidak tercatat");
  });
}
