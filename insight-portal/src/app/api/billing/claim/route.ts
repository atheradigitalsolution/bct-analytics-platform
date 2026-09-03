import { type NextRequest } from "next/server";

import { getInvoice, recordClaim } from "@/lib/billing";
import { redirectTo } from "@/lib/redirect";
import { getSession } from "@/lib/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * "Saya sudah bayar" — satu-satunya tulisan yang portal klien ini boleh lakukan.
 *
 * TIGA PAGAR SEBELUM SATU BARIS DITULIS, dan ketiganya berdiri sendiri:
 *
 *  1. Sesi harus sah. Middleware sudah menolak yang tidak, tetapi handler ini memeriksa lagi —
 *     sebuah endpoint tulis yang bergantung pada middleware untuk autentikasinya adalah endpoint
 *     yang menjadi terbuka pada hari seseorang menyunting `matcher`.
 *  2. Faktur harus MILIK tenant sesi ini. `getInvoice()` mengembalikan `null` untuk faktur tenant
 *     lain, jadi `invoice_id` dari formulir tidak bisa dipakai menempelkan klaim pada faktur orang
 *     lain. Tanpa ini, kolom `invoice_id` adalah persis lubang yang isolasi tenant ada untuk
 *     menutupnya.
 *  3. Trigger `force_claim_tenant` di database menimpa `tenant_slug` dengan GUC sesi. Bahkan
 *     kalau kedua pagar di atas suatu hari salah, baris yang mendarat tetap milik tenant yang
 *     sesinya menulis.
 *
 * CSRF: cookie sesi ber-SameSite=Strict, jadi POST lintas-situs tidak membawa kredensial apa pun
 * dan tidak pernah sampai ke pagar pertama. Itu sebabnya tidak ada token CSRF terpisah di sini,
 * dan itu keputusan sadar, bukan kelalaian.
 *
 * YANG TIDAK DILAKUKAN: tidak menyentuh `payment_state`, `amount_residual`, atau `valid_until`.
 * Role database yang dipakai memang tidak berhak melakukannya, jadi batas ini ditegakkan Postgres
 * dan bukan hanya dijanjikan oleh berkas ini.
 */
export async function POST(request: NextRequest) {
  const session = await getSession();
  if (session === null) return redirectTo("/login?next=/billing");

  const form = await request.formData();

  const invoiceId = Number.parseInt(String(form.get("invoice_id") ?? ""), 10);
  const invoice = await getInvoice(session, invoiceId);
  if (invoice === null) return redirectTo("/billing?error=faktur");

  const amount = Number(form.get("amount"));
  const paidOn = String(form.get("paid_on") ?? "");
  const bankName = String(form.get("bank_name") ?? "").trim().slice(0, 64);
  const reference = String(form.get("reference") ?? "").trim().slice(0, 64);
  const note = String(form.get("note") ?? "").trim().slice(0, 500);

  // Validasi bentuk, bukan validasi kebenaran. Apakah uangnya benar-benar masuk adalah pertanyaan
  // yang hanya rekening koran bisa jawab, dan itu memang pekerjaan operator.
  const validAmount = Number.isFinite(amount) && amount > 0 && amount < 1e15;
  const validDate = /^\d{4}-\d{2}-\d{2}$/.test(paidOn) && !Number.isNaN(Date.parse(paidOn));
  if (!validAmount || !validDate || bankName === "") {
    return redirectTo(`/billing/${invoice.id}?error=isian`);
  }

  try {
    await recordClaim(session, {
      invoiceId: invoice.id,
      invoiceNumber: invoice.invoice_number,
      amount,
      paidOn,
      bankName,
      reference,
      note,
    });
  } catch {
    // Termasuk penolakan trigger saat GUC tidak terpasang. Klien tidak diberi tahu bedanya;
    // yang perlu ia tahu adalah konfirmasinya tidak tercatat dan harus dicoba lagi.
    return redirectTo(`/billing/${invoice.id}?error=simpan`);
  }

  return redirectTo("/billing?ok=1");
}
