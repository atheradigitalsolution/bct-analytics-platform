import Link from "next/link";

import { VIEWS } from "@/lib/view";

/**
 * The view switcher.
 *
 * The tenant in every link comes from the verified session that the layout resolved, never from
 * the current URL. A viewer therefore cannot navigate themselves into another tenant by editing an
 * address bar and following a link that helpfully preserved the edit.
 *
 * It scrolls horizontally on a phone rather than collapsing into a menu behind a button: five
 * items is not enough to justify hiding four of them behind a tap, and a hamburger would need
 * client JavaScript for a list that fits.
 */
export function Nav({
  tenant,
  active,
  roles,
  subject,
  odooDoor,
}: {
  tenant: string;
  active: string;
  roles: string[];
  subject: string;
  /** Absolute URL of the SSO door, or null when this plan does not include Odoo. */
  odooDoor?: string | null;
}) {
  return (
    <header
      className="sticky top-0 z-10 border-b"
      style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}
    >
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 sm:px-4">
        <span className="text-sm font-semibold text-ink">ATHERA Insight</span>
        <span
          className="rounded px-1.5 py-0.5 text-[11px] font-medium"
          style={{ background: "var(--accent-soft)", color: "var(--series-1)" }}
        >
          tenant {tenant}
        </span>
        <span className="hidden text-[11px] text-ink-3 sm:inline">
          {subject} - {roles.length === 0 ? "tanpa peran" : roles.join(", ")}
        </span>
        {/* Akun & Tagihan.
            Ia ada DI BARIS UTILITAS, bukan di deretan tab di bawah, dan itu bukan selera tata
            letak. Tab di bawah semuanya `/t/<tenant>/<view>` dan semuanya butuh hak `insight`;
            halaman tagihan berlaku untuk setiap paket dan tetap terbuka ketika langganan sudah
            berhenti. Menaruhnya di deretan yang sama akan menjanjikan bahwa ia patuh pada aturan
            yang sama, padahal tidak.

            Tautan ini menyebut `/billing` tanpa tenant, dan itu disengaja: cakupan tenant
            diputuskan dari sesi yang terverifikasi di sisi server, bukan dari segmen URL. Tidak
            ada yang perlu ditempelkan ke sini untuk membuatnya menunjuk ke akun yang benar.

            Ini murni presentasi. `middleware.ts` tidak disentuh — pengecualian `/billing` dari
            kedua penolakan contract 07 sudah ada sebelum tautan ini, dan tautan tidak memberi
            akses apa pun yang belum diberikan. */}
        <Link href="/billing" className="ml-auto text-xs underline text-ink-2">
          Akun &amp; Tagihan
        </Link>
        {odooDoor ? (
          <a
            href={odooDoor}
            className="text-xs underline text-ink-2"
            /* Another origin, and one that hands out a session. `noopener` so the opened document
               cannot reach back through window.opener; `noreferrer` so the door is not told which
               view the visitor came from. */
            rel="noopener noreferrer"
          >
            Buka Odoo
          </a>
        ) : null}
        {/* `ml-auto` sekarang dipegang tautan tagihan, yang selalu dirender. Sebelumnya ia
            berpindah-pindah antara tautan Odoo dan tombol keluar tergantung paket. */}
        <form method="post" action="/api/auth/logout">
          <button type="submit" className="text-xs underline text-ink-2">
            Keluar
          </button>
        </form>
      </div>
      <nav aria-label="Tampilan" className="mx-auto max-w-6xl px-3 sm:px-4">
        <ul className="-mb-px flex gap-1 overflow-x-auto">
          {VIEWS.map((view) => {
            const current = view.slug === active;
            return (
              <li key={view.slug} className="shrink-0">
                <Link
                  href={"/t/" + tenant + "/" + view.slug}
                  aria-current={current ? "page" : undefined}
                  className="inline-block whitespace-nowrap border-b-2 px-2.5 py-1.5 text-xs sm:text-sm"
                  style={{
                    borderColor: current ? "var(--series-1)" : "transparent",
                    color: current ? "var(--series-1)" : "var(--text-secondary)",
                    fontWeight: current ? 600 : 400,
                  }}
                >
                  {view.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </header>
  );
}
