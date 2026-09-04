import Link from "next/link";
import { redirect } from "next/navigation";

import { listClaims, listInvoices, getSubscription } from "@/lib/billing";
import { CLAIM_STATE_LABEL, formatDate, formatMoney, STATUS_LABEL } from "@/lib/money";
import { getSession } from "@/lib/session";

export const dynamic = "force-dynamic";

/**
 * Halaman tagihan klien.
 *
 * Berlaku untuk SETIAP paket, termasuk yang tidak mencakup Insight, dan tetap terbuka ketika
 * langganan sudah tidak aktif — middleware mengecualikan `/billing` dari kedua penolakan
 * contract 07 justru karena itu. Yang tidak dikecualikan adalah autentikasi: tanpa sesi, orang
 * ini tidak sampai ke sini sama sekali.
 *
 * Tidak ada satu pun angka di halaman ini yang berasal dari URL. Tenant diambil dari `Session`,
 * dan `Session` hanya lahir dari token yang sudah diverifikasi terhadap JWKS gateway.
 */
export default async function BillingPage() {
  const session = await getSession();
  if (session === null) redirect("/login?next=/billing");

  const [subscription, invoices, claims] = await Promise.all([
    getSubscription(session),
    listInvoices(session),
    listClaims(session),
  ]);

  const outstanding = invoices.filter((i) => i.client_status !== "paid");

  // KE MANA "kembali" itu, dan kenapa ini bukan satu href tetap.
  //
  // `Nav.tsx` hanya dirender di bawah `/t/<tenant>/*`, jadi halaman ini tidak mewarisi navigasi
  // apa pun: tanpa baris di bawah, `/billing` adalah jalan buntu untuk SETIAP pengunjung, bukan
  // hanya untuk klien yang diblokir.
  //
  // Tujuannya harus mengikuti entitlement, bukan diasumsikan. Menautkan tanpa syarat ke
  // `/t/<tenant>/overview` mengirim klien yang langganannya berhenti ke rute yang middleware
  // contract 07 langsung pantulkan kembali ke `/subscription` — sebuah tombol yang kelihatan
  // membawa pulang tetapi selalu mendarat di halaman blokir. Syaratnya persis sama dengan yang
  // dipakai `/subscription` untuk memutuskan pantulannya, supaya kedua halaman tidak pernah
  // saling melempar.
  const entitled = session.subscription_active && session.products.includes("insight");
  const backHref = entitled ? `/t/${session.tenant_id}/overview` : "/subscription";
  const backLabel = entitled ? "Kembali ke dasbor" : "Kembali ke status langganan";

  return (
    <main id="main" className="mx-auto max-w-4xl px-4 py-8">
      <header className="mb-6">
        <Link className="text-xs text-ink-3 underline hover:text-ink-2" href={backHref}>
          &larr; {backLabel}
        </Link>
        <p className="mt-2 text-xs uppercase tracking-wide text-ink-3">ATHERA &mdash; Akun &amp; Tagihan</p>
        <h1 className="mt-1 text-lg font-semibold text-ink">
          {subscription?.display_name ?? session.tenant_id}
        </h1>
      </header>

      {/* ---- Langganan berjalan ---- */}
      <section
        className="rounded-lg border p-4"
        style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}
      >
        <h2 className="text-sm font-semibold text-ink">Langganan berjalan</h2>
        {subscription === null ? (
          <p className="mt-2 text-sm text-ink-2">
            Belum ada langganan tercatat untuk akun ini. Hubungi operator ATHERA.
          </p>
        ) : (
          <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
            <div>
              <dt className="text-xs text-ink-3">Paket</dt>
              <dd className="text-ink">{subscription.plan_code ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-xs text-ink-3">Status</dt>
              <dd className="text-ink">{subscription.subscription_state}</dd>
            </div>
            <div>
              <dt className="text-xs text-ink-3">Berlaku sampai</dt>
              <dd className="text-ink">{formatDate(subscription.valid_until)}</dd>
            </div>
            <div>
              <dt className="text-xs text-ink-3">Sisa hari</dt>
              <dd className="text-ink">
                {subscription.sisa_hari === null ? "tanpa batas" : `${subscription.sisa_hari} hari`}
              </dd>
            </div>
          </dl>
        )}
        {/* Produk yang benar-benar dibayar. Ditampilkan karena inilah yang menentukan pintu mana
            yang terbuka, dan klien berhak tahu apa yang ia beli. */}
        <p className="mt-3 text-xs text-ink-3">
          Produk aktif: {session.products.length > 0 ? session.products.join(", ") : "tidak ada"}
        </p>
      </section>

      {/* ---- Faktur ---- */}
      <section className="mt-6">
        <h2 className="text-sm font-semibold text-ink">
          Faktur{outstanding.length > 0 ? ` — ${outstanding.length} belum lunas` : ""}
        </h2>
        {invoices.length === 0 ? (
          <p className="mt-2 text-sm text-ink-2">Belum ada faktur untuk akun ini.</p>
        ) : (
          <div
            className="mt-2 overflow-x-auto rounded-lg border"
            style={{ borderColor: "var(--border)" }}
          >
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-ink-3" style={{ background: "var(--surface-2)" }}>
                  <th className="px-3 py-2 font-medium">Nomor</th>
                  <th className="px-3 py-2 font-medium">Tanggal</th>
                  <th className="px-3 py-2 font-medium">Jatuh tempo</th>
                  <th className="px-3 py-2 text-right font-medium">Jumlah</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {invoices.map((inv) => (
                  <tr key={inv.id} className="border-t" style={{ borderColor: "var(--border)" }}>
                    <td className="px-3 py-2 text-ink">{inv.invoice_number}</td>
                    <td className="px-3 py-2 text-ink-2">{formatDate(inv.invoice_date)}</td>
                    <td className="px-3 py-2 text-ink-2">{formatDate(inv.invoice_date_due)}</td>
                    <td className="px-3 py-2 text-right text-ink">
                      {formatMoney(inv.amount_total, inv.currency)}
                    </td>
                    <td className="px-3 py-2">
                      <span
                        className="text-xs"
                        style={{
                          color:
                            inv.client_status === "overdue"
                              ? "var(--status-critical)"
                              : inv.client_status === "paid"
                                ? "var(--status-ok, inherit)"
                                : "inherit",
                        }}
                      >
                        {STATUS_LABEL[inv.client_status] ?? inv.client_status}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right">
                      <Link className="text-xs underline" href={`/billing/${inv.id}`}>
                        Rincian
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* ---- Konfirmasi pembayaran yang sudah dikirim ---- */}
      {claims.length > 0 ? (
        <section className="mt-6">
          <h2 className="text-sm font-semibold text-ink">Konfirmasi pembayaran yang Anda kirim</h2>
          <ul className="mt-2 space-y-2">
            {claims.map((c) => (
              <li
                key={c.id}
                className="rounded border px-3 py-2 text-sm"
                style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}
              >
                <span className="text-ink">{c.invoice_number ?? "—"}</span>{" "}
                <span className="text-ink-2">
                  {formatMoney(c.amount, null)} &middot; {formatDate(c.paid_on)} &middot; {c.bank_name}
                </span>
                <span className="ml-2 text-xs text-ink-3">
                  &mdash; {CLAIM_STATE_LABEL[c.state] ?? c.state}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </main>
  );
}
