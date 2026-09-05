import { notFound } from "next/navigation";

import { MAX_EXTEND_DAYS, getTenant } from "@/lib/orchestrator";

export const dynamic = "force-dynamic";

/**
 * The SSO door into Odoo. Empty means it is not configured, and the link is then
 * simply not rendered — a dead link to a login door is worse than no link. Same
 * reasoning, and the same variable, as the nav entry in layout.tsx.
 */
const ODOO_DOOR = process.env.HUB_PORTAL_ODOO_DOOR_URL ?? "";

/**
 * One client, with the buttons custom_super_admin has always had and could
 * never use. Each posts to a route handler that signs to the orchestrator;
 * nothing here talks to the database.
 */
export default async function TenantPage({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { slug } = await params;
  const sp = await searchParams;
  // The orchestrator answers a refused extension with a sentence written for a
  // person. Showing only the status code would make a well-explained refusal
  // look identical to an outage.
  const errorCode = typeof sp.error === "string" ? sp.error : null;
  const errorDetail = typeof sp.detail === "string" ? sp.detail : null;
  const t = await getTenant(slug);
  if (t === null) notFound();

  const ent = t.entitlement;
  const rows: [string, string][] = [
    ["Database", t.db_name],
    ["Status", t.state],
    ["Paket", t.plan_code ?? "—"],
    ["Berlaku sampai", t.valid_until ?? "tanpa batas"],
    ["Sumber Insight", t.insight_source_kind],
    ["Kontak", t.contact_email ?? "—"],
    ["Dibuat", t.created_at],
    ["Diaktifkan", t.activated_at ?? "—"],
    ["Ditangguhkan", t.suspended_at ?? "—"],
  ];

  return (
    <>
      <h1>{t.display_name}</h1>
      <p className="lede">
        <code>{t.slug}</code> ·{" "}
        <span className={ent?.active ? "pill ok" : "pill bad"}>
          {ent?.active ? "aktif" : "tidak aktif"}
        </span>{" "}
        {(ent?.products ?? []).map((p) => <span key={p} className="pill">{p}</span>)}
      </p>

      <table>
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k}><th style={{ width: "14rem" }}>{k}</th><td>{v}</td></tr>
          ))}
        </tbody>
      </table>

      <h2>Tindakan</h2>
      <p>
        {/* Each is a form POST, not a link. A GET that suspends a client is a
            client suspended by a crawler. */}
        <form className="inline" method="POST" action={`/api/tenants/${t.slug}/resume`}>
          <button type="submit">Aktifkan</button>
        </form>{" "}
        <form className="inline" method="POST" action={`/api/tenants/${t.slug}/suspend`}>
          <button type="submit">Tangguhkan</button>
        </form>{" "}
        <form className="inline" method="POST" action={`/api/tenants/${t.slug}/archive`}>
          <button className="danger" type="submit">Arsipkan</button>
        </form>
      </p>
      <p className="lede">
        Perubahan status langsung mengubah klaim <code>subscription_active</code> pada
        login dan penyegaran sesi berikutnya — klien yang ditangguhkan diarahkan ke
        halaman langganan, bukan ke dasbor.
      </p>

      {errorCode ? (
        <p className="pill bad">
          Ditolak ({errorCode}){errorDetail ? `: ${errorDetail}` : ""}
        </p>
      ) : null}

      <h2>Perpanjang akses</h2>
      <p className="lede">
        Sebelum ini <code>valid_until</code> hanya bergerak satu cara: faktur dibayar.
        Operator yang harus memberi akses tanpa pembayaran — pilot, itikad baik, faktur
        yang sedang disengketakan — tidak punya tombol apa pun, dan yang tersisa dalam
        jangkauannya adalah mencatat pembayaran yang tidak pernah terjadi. Tombol ini ada
        supaya perbuatan itu berhenti di action log, bukan masuk ke buku besar.
      </p>
      <form method="POST" action={`/api/tenants/${t.slug}/extend`}>
        <label>
          Hari{" "}
          <input type="number" name="days" min={1} max={MAX_EXTEND_DAYS} defaultValue={30} required />
        </label>{" "}
        <label>
          Alasan{" "}
          <input
            type="text"
            name="reason"
            minLength={8}
            maxLength={500}
            size={48}
            required
            placeholder="mis. pilot diperpanjang sesuai kesepakatan, tiket 412"
          />
        </label>{" "}
        <button type="submit">Perpanjang</button>
      </form>
      <p className="lede">
        Maksimal {MAX_EXTEND_DAYS} hari sekali perpanjang, tidak pernah memperpendek masa
        yang sudah berjalan, dan <strong>tidak</strong> membangunkan tenant yang
        ditangguhkan — penangguhan punya alasannya sendiri dan tombolnya sendiri.
        Alasan yang ditulis di sini masuk ke action log dan dibaca orang lain berbulan-bulan
        kemudian.
      </p>

      <h2>Langganan dan penagihan</h2>
      <p className="lede">
        {/* MEMBUAT DAN MENGUBAH LANGGANAN SENGAJA TIDAK DISALIN KE SINI. Ia menyentuh
            partner, mata uang, jadwal faktur, jurnal, dan riwayat pesan — form Odoo sudah
            melakukan semuanya, dan salinan kedua tidak akan pernah selengkap yang pertama.
            Yang hilang selama ini bukan kemampuannya melainkan JALANNYA: halaman ini
            menampilkan langganan tanpa satu pun tautan menuju tempat ia bisa disunting.
            Jadi yang dibangun adalah tautan, bukan formulir kedua. */}
        Membuat, mengubah paket, menerbitkan faktur, dan mencatat pembayaran dilakukan di
        konsol Odoo, tempat jurnal, pajak, dan jejak auditnya hidup.
        {ODOO_DOOR ? (
          <>
            {" "}
            <a href={`${ODOO_DOOR}`} rel="noopener noreferrer">
              Buka konsol Odoo
            </a>{" "}
            lalu <code>ATHERA Billing → Langganan</code>.
          </>
        ) : null}
      </p>
    </>
  );
}
