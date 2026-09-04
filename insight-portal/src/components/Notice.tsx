import type { Notice } from "@/lib/feedback";

/**
 * Spanduk umpan balik satu tindakan.
 *
 * `role="status"` untuk yang berhasil dan `role="alert"` untuk yang gagal: keduanya diumumkan
 * pembaca layar, tetapi `alert` menyela dan `status` menunggu jeda. Sebuah konfirmasi pembayaran
 * yang berhasil tidak perlu menyela; sebuah kegagalan perlu.
 *
 * Warnanya dari variabel tema yang sama dengan sisa portal, dan pesannya selalu disertai kata —
 * warna sendirian bukan informasi bagi pembaca yang tidak membedakan merah dan hijau.
 */
export function NoticeBanner({ notice }: { notice: Notice }) {
  const critical = notice.tone === "error";
  return (
    <div
      role={critical ? "alert" : "status"}
      className="mb-4 rounded-lg border px-4 py-3"
      style={{
        borderColor: critical ? "var(--status-critical)" : "var(--border)",
        background: "var(--surface-1)",
      }}
    >
      <p
        className="text-sm font-semibold"
        style={{ color: critical ? "var(--status-critical)" : "var(--status-ok, inherit)" }}
      >
        {critical ? "▲" : "✓"} {notice.title}
      </p>
      <p className="mt-1 text-xs leading-relaxed text-ink-2">{notice.detail}</p>
    </div>
  );
}
