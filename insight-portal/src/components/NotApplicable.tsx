import { Card } from "./Panel";

/**
 * What a viewer sees on a view their own data cannot fill.
 *
 * Reaching one of these means a bookmark, a shared link or a typed address: the navigation stopped
 * offering the tab as soon as `lib/capabilities.ts` decided the mart behind it holds no rows for
 * this session. The page therefore explains itself rather than rendering a grid of dashes, which
 * is indistinguishable from a dashboard that is broken.
 *
 * IT NAMES THE MART. "Tidak ada data" is not actionable by anybody; "mart_ppob_transaction holds
 * no rows for this tenant" tells an operator exactly which pipeline to look at and tells a client
 * exactly what to ask about.
 *
 * `decided` separates two states that must not be worded the same way. A decided verdict is a fact
 * about the tenant's data. An undecided one means the semantic layer did not answer and the view
 * is being offered anyway - a platform problem, and not something the reader can fix by trying
 * different filters.
 */
export function NotApplicable({
  id,
  view,
  mart,
  decided,
  children,
}: {
  id: string;
  /** The view's own title, as it appears in the navigation. */
  view: string;
  /** The mart the view reads, named so the message points at something checkable. */
  mart: string;
  decided: boolean;
  /** Optional extra sentence specific to the view. */
  children?: React.ReactNode;
}) {
  if (!decided) {
    return (
      <Card id={id} title="Belum bisa dipastikan">
        <p className="text-xs text-ink-2">
          Lapisan semantik tidak menjawab saat portal menanyakan apakah tenant ini memiliki data
          untuk tampilan {view}. Tab tetap ditawarkan daripada disembunyikan diam-diam. Muat ulang
          halaman; bila terus berulang, ini gangguan platform, bukan sesuatu yang bisa Anda
          perbaiki.
        </p>
      </Card>
    );
  }
  return (
    <Card id={id} title={"Tampilan " + view + " tidak berlaku untuk data Anda"}>
      <div className="space-y-2 text-xs text-ink-2">
        <p>
          Tampilan ini dibangun di atas{" "}
          <code className="rounded px-1" style={{ background: "var(--surface-2)" }}>
            {mart}
          </code>
          , dan mart itu tidak memuat satu baris pun untuk tenant ini. Bukan berarti angkanya nol
          &mdash; berarti tidak ada transaksi jenis ini yang pernah masuk ke gudang data untuk
          dihitung.
        </p>
        {children}
        <p>
          Itu sebabnya tab ini tidak muncul di navigasi Anda. Jika bisnis Anda memang menjalankan
          hal ini dan halaman tetap kosong, yang perlu diperiksa adalah pipeline-nya, bukan halaman
          ini.
        </p>
      </div>
    </Card>
  );
}
