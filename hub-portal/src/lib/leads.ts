import "server-only";

import { Pool } from "pg";

/**
 * Kiriman formulir publik, dibaca lewat SATU view.
 *
 * Pola yang sama dengan `billing.ts` dan `cms.ts`: portal tersambung sebagai
 * `tenant_orchestrator`, role hak-minimal yang tidak punya grant apa pun pada tabel
 * Odoo. Yang diberikan hanya SELECT pada `onboarding.public_submission_overview`,
 * dibuat dan di-grant oleh `custom_onboarding_journey`.
 *
 * KENAPA HALAMAN INI ADA. Endpoint intake sudah berjalan sejak lama dan menulis ke
 * basis data dengan rajin, tetapi tidak ada satu pun antarmuka yang membacanya.
 * Lead yang tidak pernah dibaca sama saja dengan lead yang tidak pernah datang —
 * bedanya hanya, yang ini menimbulkan keyakinan bahwa formulirnya bekerja.
 *
 * `raw_payload_json` TIDAK ADA di view dan tidak akan pernah ada di sini. Ia payload
 * mentah dari pihak yang tidak dikenal; kolom di bawah adalah proyeksi yang sudah
 * disaring saat penulisan. `npwp` dan nomor rekening tidak diterima oleh endpoint
 * publik sama sekali, jadi tidak ada yang perlu ditutupi di lapisan ini.
 *
 * BACA-SAJA, seperti halaman penagihan. Mempromosikan kiriman menjadi journey
 * membuat partner, journey, dan lampiran BRD sekaligus; jalannya adalah wizard di
 * konsol Odoo yang sudah membawa jejak auditnya. Menyalin tombolnya ke sini berarti
 * dua jalan menuju satu perbuatan, dan yang kedua tidak akan pernah selengkap yang
 * pertama.
 */

const globalForPool = globalThis as unknown as { hub_leads_pool?: Pool };

function pool(): Pool {
  if (!globalForPool.hub_leads_pool) {
    const connectionString = process.env.HUB_PORTAL_CMS_DSN;
    if (!connectionString) throw new Error("HUB_PORTAL_CMS_DSN is not set");
    globalForPool.hub_leads_pool = new Pool({
      connectionString,
      max: Number(process.env.HUB_PORTAL_POOL_MAX ?? 4),
      connectionTimeoutMillis: 5000,
    });
  }
  return globalForPool.hub_leads_pool;
}

export interface LeadRow {
  id: number;
  submitted_at: Date;
  status: string;
  company_name: string | null;
  partner_name: string | null;
  contact_email: string | null;
  contact_phone: string | null;
  vertical_target_hint: string | null;
  company_size: string | null;
  interest: string | null;
  current_system: string | null;
  message: string | null;
  source: string | null;
  consent_given: boolean;
  payload_bytes: number;
  journey_id: number | null;
  journey_stage: string | null;
  rejection_reason: string | null;
}

export async function listLeads(limit = 200): Promise<LeadRow[]> {
  const { rows } = await pool().query<LeadRow>(
    `SELECT id, submitted_at, status, company_name, partner_name,
            contact_email, contact_phone, vertical_target_hint, company_size,
            interest, current_system, message, source, consent_given,
            payload_bytes, journey_id, journey_stage, rejection_reason
       FROM onboarding.public_submission_overview
      ORDER BY submitted_at DESC, id DESC
      LIMIT $1`,
    [limit],
  );
  return rows;
}
