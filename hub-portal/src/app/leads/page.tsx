import { listLeads, type LeadRow } from "@/lib/leads";

export const dynamic = "force-dynamic";

/**
 * Waktu kiriman dibaca dari komponen lokalnya, tidak lewat `toISOString()`.
 * Alasan yang sama dengan halaman penagihan: pergeseran ke UTC menggeser tanggal
 * satu hari pada server ber-zona timur, dan "kapan lead ini masuk" adalah hal yang
 * dipakai orang untuk memutuskan siapa yang dihubungi lebih dulu.
 */
function stamp(d: Date | null): string {
  if (!d) return "—";
  const x = new Date(d);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${x.getFullYear()}-${p(x.getMonth() + 1)}-${p(x.getDate())} ${p(x.getHours())}:${p(x.getMinutes())}`;
}

function age(d: Date | null): string {
  if (!d) return "";
  const hours = Math.floor((Date.now() - new Date(d).getTime()) / 3_600_000);
  if (hours < 1) return "baru saja";
  if (hours < 24) return `${hours} jam lalu`;
  return `${Math.floor(hours / 24)} hari lalu`;
}

function statusPill(row: LeadRow) {
  if (row.status === "promoted") return <span className="pill ok">dipromosikan</span>;
  if (row.status === "rejected") return <span className="pill bad">ditolak</span>;
  return <span className="pill warn">belum ditangani</span>;
}

/** Kiriman formulir publik — produk 1 bertemu produk 2. Baca-saja. */
export default async function LeadsPage() {
  const rows = await listLeads();
  const untouched = rows.filter((r) => r.status === "submitted");
  const oldest = untouched.at(-1)?.submitted_at ?? null;

  return (
    <>
      <h1>Kiriman formulir</h1>
      <p className="lede">
        {rows.length} kiriman, {untouched.length} belum ditangani
        {oldest ? ` (tertua ${age(oldest)})` : ""}. Dibaca dari{" "}
        <code>onboarding.public_submission_overview</code>. Sebelum halaman ini ada, endpoint
        intake sudah menulis ke basis data tanpa satu pun antarmuka yang membacanya — kiriman
        yang tidak pernah dibaca tidak berbeda dari kiriman yang tidak pernah datang.
      </p>
      <p className="lede">
        Halaman ini <strong>baca-saja</strong>. Mempromosikan kiriman menjadi journey membuat
        partner, journey, dan lampiran BRD sekaligus; jalannya adalah{" "}
        <code>Onboarding → Kiriman Publik → Promote</code> di konsol Odoo, tempat jejak auditnya
        hidup.
      </p>
      <table>
        <thead>
          <tr>
            <th>Masuk</th>
            <th>Perusahaan</th>
            <th>Kontak</th>
            <th>Minat</th>
            <th>Sistem sekarang</th>
            <th>Status</th>
            <th>Asal</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td>
                {stamp(r.submitted_at)}
                <div className="lede">{age(r.submitted_at)}</div>
              </td>
              <td>
                <strong>{r.company_name ?? "—"}</strong>
                {r.company_size ? <div className="lede">{r.company_size}</div> : null}
                {r.message ? (
                  <div className="lede" title={r.message}>
                    {r.message.length > 140 ? `${r.message.slice(0, 140)}…` : r.message}
                  </div>
                ) : null}
              </td>
              <td>
                {r.partner_name ?? "—"}
                {r.contact_email ? (
                  <div className="lede">
                    <a href={`mailto:${r.contact_email}`}>{r.contact_email}</a>
                  </div>
                ) : null}
                {r.contact_phone ? <div className="lede">{r.contact_phone}</div> : null}
                {/* Persetujuan pemrosesan data. Kiriman tanpa tanda ini tidak boleh
                    dihubungi untuk pemasaran; ditampilkan supaya keputusan itu ada di
                    depan mata orang yang akan menekan tombol balas. */}
                {r.consent_given ? null : <span className="pill bad">tanpa persetujuan</span>}
              </td>
              <td>
                {r.interest ?? "—"}
                {r.vertical_target_hint ? (
                  <div className="lede">{r.vertical_target_hint}</div>
                ) : null}
              </td>
              <td>{r.current_system ?? "—"}</td>
              <td>
                {statusPill(r)}
                {r.journey_stage ? <div className="lede">{r.journey_stage}</div> : null}
                {r.rejection_reason ? <div className="lede">{r.rejection_reason}</div> : null}
              </td>
              <td>{r.source ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 ? (
        <p className="lede">
          Belum ada kiriman. Formulirnya ada di <code>/kontak</code> pada situs publik; kalau ia
          terisi tetapi tabel ini tetap kosong, yang salah adalah tujuan rutenya, bukan
          formulirnya.
        </p>
      ) : null}
    </>
  );
}
