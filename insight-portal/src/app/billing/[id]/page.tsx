import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { getInvoice } from "@/lib/billing";
import { config } from "@/lib/config";
import { claimNotice } from "@/lib/feedback";
import { NoticeBanner } from "@/components/Notice";
import { formatDate, formatMoney, isoDate, STATUS_LABEL } from "@/lib/money";
import { getSession } from "@/lib/session";

export const dynamic = "force-dynamic";

/**
 * Rincian satu faktur, plus jalur "saya sudah bayar".
 *
 * KENAPA 404 DAN BUKAN 403 UNTUK FAKTUR MILIK TENANT LAIN. `getInvoice()` mengembalikan `null`
 * untuk faktur yang tidak ada MAUPUN faktur milik orang lain, dan halaman ini tidak bisa
 * membedakan keduanya karena database tidak memberitahunya. Itu disengaja: 403 akan menjawab
 * "faktur ini ada, tapi bukan milikmu", yang mengubah URL menjadi alat menghitung faktur orang
 * lain. Alasannya sama dengan bodi 403 contract 02 yang tidak mengungkap apakah tenant lain ada.
 *
 * TIDAK ADA UNDUH PDF, DAN ITU KEPUTUSAN. PDF faktur dirender mesin laporan Odoo dan disimpan di
 * filestore, bukan di kolom database. Membacanya dari sini berarti me-mount volume data Odoo ke
 * dalam aplikasi yang menghadap klien — pelebaran blast radius yang besar demi kenyamanan.
 * Halaman ini dirancang untuk dicetak (browser -> PDF); jalur yang benar adalah controller Odoo
 * di balik tiket SSO, dan itu brief tersendiri.
 */
export default async function InvoiceDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const session = await getSession();
  if (session === null) redirect("/login?next=/billing");

  // `POST /api/billing/claim` memantulkan validasi yang gagal ke sini dengan `?error=isian` atau
  // `?error=simpan`. Sampai 2026-09-04 tidak ada yang membacanya: formulir kembali kosong tanpa
  // satu kata pun tentang kenapa. Lihat src/lib/feedback.ts.
  const notice = claimNotice(await searchParams);

  const { id } = await params;
  // Segmen URL hanya menjadi ANGKA. Ia tidak pernah menjadi tenant, dan tidak ada parameter lain
  // di halaman ini yang bisa mengubah tenant mana yang dikueri.
  const invoice = await getInvoice(session, Number.parseInt(id, 10));
  if (invoice === null) notFound();

  const unpaid = invoice.client_status !== "paid";
  /**
   * KETIGANYA, bukan dua. Sebelumnya `bankAccountHolder` tidak ikut diperiksa, jadi konfigurasi
   * yang setengah terisi menampilkan nomor rekening dengan baris "Atas nama" kosong — instruksi
   * transfer tanpa nama penerima, yang adalah bentuk yang persis ditiru penipuan faktur. Isi
   * ketiganya di .env mesin dan halaman ini langsung memakainya; tidak ada perubahan kode lain
   * yang dibutuhkan.
   */
  const hasBank =
    config.bankName !== "" &&
    config.bankAccountNumber !== "" &&
    config.bankAccountHolder !== "";
  const contact = config.billingContact.trim();
  const contactIsEmail = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(contact);
  const contactUrl = config.billingContactUrl.trim();

  return (
    <main id="main" className="mx-auto max-w-2xl px-4 py-8">
      {notice !== null ? <NoticeBanner notice={notice} /> : null}

      <p className="text-xs">
        <Link className="underline text-ink-3" href="/billing">
          &larr; Kembali ke tagihan
        </Link>
      </p>

      <h1 className="mt-3 text-lg font-semibold text-ink">Faktur {invoice.invoice_number}</h1>

      <section
        className="mt-4 rounded-lg border p-4"
        style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}
      >
        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
          <div>
            <dt className="text-xs text-ink-3">Tanggal faktur</dt>
            <dd className="text-ink">{formatDate(invoice.invoice_date)}</dd>
          </div>
          <div>
            <dt className="text-xs text-ink-3">Jatuh tempo</dt>
            <dd className="text-ink">{formatDate(invoice.invoice_date_due)}</dd>
          </div>
          <div>
            <dt className="text-xs text-ink-3">Dasar pengenaan</dt>
            <dd className="text-ink">{formatMoney(invoice.amount_untaxed, invoice.currency)}</dd>
          </div>
          <div>
            <dt className="text-xs text-ink-3">Pajak</dt>
            <dd className="text-ink">{formatMoney(invoice.amount_tax, invoice.currency)}</dd>
          </div>
          <div>
            <dt className="text-xs text-ink-3">Total</dt>
            <dd className="font-semibold text-ink">
              {formatMoney(invoice.amount_total, invoice.currency)}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-ink-3">Sisa tagihan</dt>
            <dd className="text-ink">{formatMoney(invoice.amount_residual, invoice.currency)}</dd>
          </div>
          <div>
            <dt className="text-xs text-ink-3">Status</dt>
            <dd className="text-ink">{STATUS_LABEL[invoice.client_status] ?? invoice.client_status}</dd>
          </div>
        </dl>
      </section>

      {unpaid ? (
        <>
          <section
            className="mt-4 rounded-lg border p-4"
            style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}
          >
            <h2 className="text-sm font-semibold text-ink">Cara membayar</h2>
            {hasBank ? (
              <>
                <p className="mt-2 text-sm text-ink-2">
                  Transfer manual ke rekening berikut, lalu konfirmasikan lewat formulir di bawah.
                </p>
                <dl className="mt-3 space-y-1 text-sm">
                  <div className="flex gap-2">
                    <dt className="w-32 text-xs text-ink-3">Bank</dt>
                    <dd className="text-ink">{config.bankName}</dd>
                  </div>
                  <div className="flex gap-2">
                    <dt className="w-32 text-xs text-ink-3">Nomor rekening</dt>
                    <dd className="font-mono text-ink">{config.bankAccountNumber}</dd>
                  </div>
                  <div className="flex gap-2">
                    <dt className="w-32 text-xs text-ink-3">Atas nama</dt>
                    <dd className="text-ink">{config.bankAccountHolder}</dd>
                  </div>
                  <div className="flex gap-2">
                    <dt className="w-32 text-xs text-ink-3">Berita transfer</dt>
                    <dd className="font-mono text-ink">{invoice.invoice_number}</dd>
                  </div>
                </dl>
              </>
            ) : contact !== "" ? (
              /* CABANG YANG SEBENARNYA DILIHAT ORANG.
                 INSIGHT_PORTAL_BANK_* akan tetap kosong untuk waktu yang tidak ditentukan
                 (keputusan user 2026-09-04: nomor rekening diisi langsung di .env mesin, dan
                 datanya belum ada), jadi ini bukan kondisi sementara yang langka — ini yang
                 dilihat SETIAP klien yang mau membayar. Sebelumnya bunyinya "Hubungi operator
                 ATHERA" tanpa menyebutkan satu pun cara menghubunginya, yaitu jalan buntu yang
                 terlihat seperti petunjuk.

                 Alamat di bawah bukan karangan: `config.billingContact` jatuh ke alamat yang
                 sudah dipublikasikan di situs perusahaan. Tidak ada nomor telepon karena situs
                 pun belum punya. */
              <>
                <p className="mt-2 text-sm text-ink-2">
                  Rincian rekening belum tersedia di portal ini, jadi transfer belum bisa
                  dilakukan dari halaman ini.
                </p>
                <p className="mt-2 text-sm text-ink-2">
                  Mintalah instruksi pembayaran dengan menyebut nomor faktur{" "}
                  <span className="font-mono text-ink">{invoice.invoice_number}</span> ke{" "}
                  {contactIsEmail ? (
                    <a
                      className="underline text-ink"
                      href={`mailto:${contact}?subject=${encodeURIComponent(
                        `Instruksi pembayaran faktur ${invoice.invoice_number}`,
                      )}`}
                    >
                      {contact}
                    </a>
                  ) : (
                    <span className="text-ink">{contact}</span>
                  )}
                  {contactUrl !== "" ? (
                    <>
                      {" "}atau lewat{" "}
                      <a
                        className="underline text-ink"
                        href={contactUrl}
                        rel="noreferrer noopener"
                        target="_blank"
                      >
                        halaman kontak kami
                      </a>
                    </>
                  ) : null}
                  .
                </p>
                <p className="mt-2 text-xs text-ink-3">
                  Kalau Anda sudah menerima instruksi transfer lewat jalur lain dan sudah
                  membayar, konfirmasinya tetap bisa dikirim lewat formulir di bawah.
                </p>
              </>
            ) : (
              /* Tidak ada rekening DAN tidak ada kontak. Sebuah ajakan membayar yang tidak bisa
                 diselesaikan lebih buruk daripada tidak ada ajakan sama sekali, jadi halaman
                 mengatakan apa adanya dan berhenti di situ. */
              <p className="mt-2 text-sm text-ink-2">
                Instruksi pembayaran untuk faktur ini sedang kami siapkan dan akan muncul di
                halaman ini begitu siap. Anda tidak melewatkan langkah apa pun; tidak ada yang
                perlu Anda lakukan sekarang.
              </p>
            )}
          </section>

          <section
            className="mt-4 rounded-lg border p-4"
            style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}
          >
            <h2 className="text-sm font-semibold text-ink">Saya sudah bayar</h2>
            <p className="mt-1 text-xs text-ink-3">
              Konfirmasi ini dikirim ke operator untuk dicocokkan dengan rekening koran. Status
              faktur tidak berubah otomatis &mdash; rekonsiliasi tetap dilakukan operator.
            </p>
            <form method="post" action="/api/billing/claim" className="mt-3 space-y-3">
              <input type="hidden" name="invoice_id" value={invoice.id} />
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label htmlFor="amount" className="block text-xs font-medium text-ink-2">
                    Jumlah ditransfer
                  </label>
                  <input
                    id="amount"
                    name="amount"
                    type="number"
                    min="1"
                    step="1"
                    required
                    defaultValue={Number(invoice.amount_residual)}
                    className="mt-1 w-full rounded border px-2 py-1.5 text-sm"
                    style={{ borderColor: "var(--border)", background: "var(--surface-2)" }}
                  />
                </div>
                <div>
                  <label htmlFor="paid_on" className="block text-xs font-medium text-ink-2">
                    Tanggal transfer
                  </label>
                  <input
                    id="paid_on"
                    name="paid_on"
                    type="date"
                    required
                    defaultValue={isoDate(new Date())}
                    className="mt-1 w-full rounded border px-2 py-1.5 text-sm"
                    style={{ borderColor: "var(--border)", background: "var(--surface-2)" }}
                  />
                </div>
                <div>
                  <label htmlFor="bank_name" className="block text-xs font-medium text-ink-2">
                    Bank pengirim
                  </label>
                  <input
                    id="bank_name"
                    name="bank_name"
                    type="text"
                    required
                    maxLength={64}
                    className="mt-1 w-full rounded border px-2 py-1.5 text-sm"
                    style={{ borderColor: "var(--border)", background: "var(--surface-2)" }}
                  />
                </div>
                <div>
                  <label htmlFor="reference" className="block text-xs font-medium text-ink-2">
                    Nomor referensi
                  </label>
                  <input
                    id="reference"
                    name="reference"
                    type="text"
                    maxLength={64}
                    className="mt-1 w-full rounded border px-2 py-1.5 text-sm"
                    style={{ borderColor: "var(--border)", background: "var(--surface-2)" }}
                  />
                </div>
              </div>
              <div>
                <label htmlFor="note" className="block text-xs font-medium text-ink-2">
                  Catatan (opsional)
                </label>
                <textarea
                  id="note"
                  name="note"
                  rows={2}
                  maxLength={500}
                  className="mt-1 w-full rounded border px-2 py-1.5 text-sm"
                  style={{ borderColor: "var(--border)", background: "var(--surface-2)" }}
                />
              </div>
              <button
                type="submit"
                className="rounded px-3 py-1.5 text-sm font-medium"
                style={{ background: "var(--surface-2)", border: "1px solid var(--border)" }}
              >
                Kirim konfirmasi
              </button>
            </form>
          </section>
        </>
      ) : (
        <p className="mt-4 text-sm text-ink-2">Faktur ini sudah lunas. Terima kasih.</p>
      )}
    </main>
  );
}
