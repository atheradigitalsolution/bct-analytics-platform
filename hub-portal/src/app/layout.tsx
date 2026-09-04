import type { Metadata } from "next";
import Link from "next/link";

import "./globals.css";

export const metadata: Metadata = { title: "ATHERA — Super Admin", robots: "noindex, nofollow" };
export const dynamic = "force-dynamic";

/**
 * The Odoo console, reached through the SSO door rather than directly.
 *
 * `odoo.<domain>` sits behind the gateway's routing gate now, so the console is not a bare
 * hostname a person types any more. Empty means the door is not configured and the link is simply
 * not rendered — a dead link to a login door is worse than no link.
 */
const ODOO_DOOR = process.env.HUB_PORTAL_ODOO_DOOR_URL ?? "";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="id">
      <body>
        <header>
          <div className="wrap">
            <Link className="brand" href="/">ATHERA · Super Admin</Link>
            <nav>
              <Link href="/">Klien</Link>
              <Link href="/cms">Konten</Link>
              <Link href="/billing">Penagihan</Link>
              {/* Editor harga. Ia sudah berfungsi penuh sejak dibangun tetapi tidak ditautkan
                  dari mana pun, jadi satu-satunya cara mencapainya adalah mengetik URL — sebuah
                  fitur yang hanya diketahui orang yang membangunnya bukanlah fitur.
                  Tidak ada gerbang baru di sini: `middleware.ts` sudah menuntut sesi super admin
                  untuk setiap lintasan kecuali /login dan /healthz, jadi tautan ini tidak
                  memperlihatkan apa pun kepada pengunjung yang tidak berhak. */}
              <Link href="/pricing">Harga</Link>
              {ODOO_DOOR === "" ? null : (
                <a href={ODOO_DOOR} rel="noopener noreferrer">Odoo</a>
              )}
            </nav>
            <a className="login" href="/api/auth/logout">Keluar</a>
          </div>
        </header>
        <main><div className="wrap">{children}</div></main>
      </body>
    </html>
  );
}
