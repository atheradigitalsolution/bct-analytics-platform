import Link from "next/link";

import { listBilling } from "@/lib/billing";

export const dynamic = "force-dynamic";

/** See the note on the same constant in tenants/[slug]/page.tsx. */
const ODOO_DOOR = process.env.HUB_PORTAL_ODOO_DOOR_URL ?? "";

/**
 * Kolom `date` Postgres tidak membawa zona waktu, tetapi driver mengembalikannya sebagai `Date`
 * pada tengah malam WAKTU LOKAL. `toISOString()` lalu menggesernya ke UTC dan setiap tanggal
 * tampil mundur satu hari di server ber-zona timur UTC — terukur: jatuh tempo 2026-06-15 dirender
 * 2026-06-14. Pada halaman tagihan itu salah menyebut kapan uang jatuh tempo, bukan kesalahan
 * tampilan. Jadi tanggal dibaca dari komponen lokalnya, tidak pernah lewat UTC.
 */
function isoLocal(d: Date): string {
  const x = new Date(d);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${x.getFullYear()}-${p(x.getMonth() + 1)}-${p(x.getDate())}`;
}

/** Hari sampai sebuah tanggal, negatif berarti sudah lewat. Dihitung dari tengah malam lokal. */
function daysUntil(d: Date | null): number | null {
  if (!d) return null;
  const target = new Date(d);
  target.setHours(0, 0, 0, 0);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((target.getTime() - today.getTime()) / 86_400_000);
}

function money(amount: string | null, currency: string | null): string {
  if (amount === null) return "—";
  const n = Number(amount);
  if (!Number.isFinite(n)) return "—";
  return new Intl.NumberFormat("id-ID", {
    style: "currency",
    currency: currency ?? "IDR",
    maximumFractionDigits: 0,
  }).format(n);
}

function date(d: Date | null): string {
  return d ? isoLocal(d) : "—";
}

/** Penagihan — produk 2. Baca-saja; perbuatan ada di konsol Odoo. */
export default async function BillingPage() {
  const rows = await listBilling();
  const arrears = rows.filter((r) => r.open_invoice_count > 0);
  const totalOutstanding = rows.reduce((sum, r) => sum + Number(r.outstanding || 0), 0);

  return (
    <>
      <h1>Penagihan</h1>
      <p className="lede">
        {rows.length} langganan, {arrears.length} punya tagihan terbuka, total{" "}
        {money(String(totalOutstanding), rows[0]?.currency ?? "IDR")} belum diterima. Angka dibaca
        dari <code>billing.subscription_overview</code> — view yang sama yang dipakai gerbang untuk
        memutuskan akses, jadi halaman ini tidak bisa menyimpang darinya.
      </p>
      <p className="lede">
        Halaman ini <strong>baca-saja</strong>. Menerbitkan faktur, mencatat pembayaran, dan
        menangguhkan klien dilakukan di konsol Odoo, tempat jurnal, pajak, dan jejak auditnya hidup.
        {ODOO_DOOR ? (
          <>
            {" "}
            {/* Halaman ini menampilkan langganan berbulan-bulan tanpa satu pun tautan
                menuju tempat ia bisa disunting, jadi "ada di konsol Odoo" adalah kalimat
                yang benar dan tidak berguna. Fitur yang hanya bisa dicapai oleh orang
                yang sudah tahu jalannya bukan fitur — alasan yang sama dipakai untuk
                menautkan /pricing dari nav. */}
            <a href={ODOO_DOOR} rel="noopener noreferrer">Buka konsol Odoo</a> lalu{" "}
            <code>ATHERA Billing → Langganan</code> untuk membuat atau mengubah, dan{" "}
            <code>ATHERA Billing → Ringkasan</code> untuk tampilan yang sama dengan halaman ini.
          </>
        ) : null}
      </p>
      <table>
        <thead>
          <tr>
            <th>Tenant</th>
            <th>Paket</th>
            <th>Langganan</th>
            <th>Tenant</th>
            <th>Faktur terbuka</th>
            <th>Belum dibayar</th>
            <th>Tertua jatuh tempo</th>
            <th>Faktur berikutnya</th>
            <th>Akses sampai</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const overdue = daysUntil(r.oldest_due_date);
            return (
              <tr key={r.tenant_slug}>
                <td>
                  {/* Ke halaman tenant, tempat tombol perpanjang akses berada. Dari
                      daftar tagihan menuju satu-satunya perbuatan yang bisa dilakukan
                      di portal ini adalah lompatan yang paling sering dibutuhkan. */}
                  <Link href={`/tenants/${r.tenant_slug}`}><strong>{r.tenant_slug}</strong></Link>
                  {r.display_name ? <div className="lede">{r.display_name}</div> : null}
                </td>
                <td>{r.plan_code ?? "—"}</td>
                <td>
                  <span className={r.subscription_state === "active" ? "pill ok" : "pill warn"}>
                    {r.subscription_state}
                  </span>
                </td>
                <td>
                  <span
                    className={
                      r.tenant_state === "active"
                        ? "pill ok"
                        : r.tenant_state === "suspended"
                          ? "pill bad"
                          : "pill warn"
                    }
                  >
                    {r.tenant_state ?? "—"}
                  </span>
                </td>
                <td>{r.open_invoice_count}</td>
                <td>{Number(r.outstanding) > 0 ? money(r.outstanding, r.currency) : "—"}</td>
                <td>
                  {date(r.oldest_due_date)}
                  {overdue !== null && overdue < 0 ? (
                    <span className="pill bad"> telat {Math.abs(overdue)} hari</span>
                  ) : null}
                </td>
                <td>{date(r.next_invoice_date)}</td>
                <td>{date(r.valid_until)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {rows.length === 0 ? (
        <p className="lede">
          Belum ada langganan. Buat di konsol Odoo: <code>ATHERA Billing → Langganan</code>.
        </p>
      ) : null}
    </>
  );
}
