import type { ReactNode } from "react";

import { config } from "@/lib/config";
import type { PortalFilters } from "@/lib/filters";
import type { Session } from "@/lib/jwt";
import type { ViewDef } from "@/lib/view";

import { FilterBar } from "./FilterBar";
import { Nav } from "./Nav";

/**
 * The frame every view renders inside: navigation, the persistent filter, then the panels.
 *
 * The frame renders from values the page has already resolved - it issues no query of its own - so
 * it can stream to the browser while the panel grid is still being fetched. That is where the
 * perceived load time of this dashboard actually goes: the shell paints, the filter is usable, and
 * the figures arrive into it.
 *
 * TWO OF THOSE VALUES COST A QUERY UPSTREAM, and pretending otherwise is how the note here used to
 * read. `loadOuOptions` has always asked the semantic layer which Operating Units an `all_ou`
 * session may narrow to, and `loadCapabilities` now asks which optional views this tenant's data
 * can fill. `loadShell` joins them so the page awaits the slower of the two rather than their sum,
 * and the capability answer is cached for far longer than any figure - see CAPABILITY_TTL_SECONDS.
 */
export function ViewShell({
  session,
  active,
  title,
  intro,
  filters,
  ouOptions,
  views,
  formNext,
  children,
}: {
  session: Session;
  active: string;
  title: string;
  intro: string;
  filters: PortalFilters;
  ouOptions: number[];
  /** The tabs this session is offered, from `loadShell`. */
  views: readonly ViewDef[];
  /** Where the filter form returns to. Defaults to this view; a drill passes its full query. */
  formNext?: string;
  children: ReactNode;
}) {
  const next = formNext ?? "/t/" + session.tenant_id + "/" + active;
  return (
    <div className="min-h-screen">
      <Nav
        tenant={session.tenant_id}
        active={active}
        roles={session.roles}
        subject={session.sub}
        views={views}
        odooDoor={
          config.odooDoorUrl !== "" && session.products.includes("odoo")
            ? config.odooDoorUrl
            : null
        }
      />
      <main id="main" className="mx-auto max-w-6xl px-3 py-4 sm:px-4">
        <h1 className="text-lg font-semibold text-ink sm:text-xl">{title}</h1>
        <p className="mt-1 max-w-3xl text-xs text-ink-2">{intro}</p>
        <div className="mt-3">
          <FilterBar filters={filters} session={session} next={next} ouOptions={ouOptions} />
        </div>
        <div className="mt-4">{children}</div>
        <footer className="mt-8 border-t pt-3 text-[11px] text-ink-3" style={{ borderColor: "var(--border)" }}>
          <p>
            Setiap angka pada halaman ini berasal dari <code>POST /v1/query</code> pada lapisan
            semantik. Portal ini tidak menulis SQL, tidak menghitung ulang metrik, dan tidak memiliki
            kredensial basis data apa pun.
          </p>
          <p className="mt-1">
            Cakupan tenant ditetapkan dari token yang terverifikasi di sisi server. Parameter URL,
            header, cookie, dan kolom formulir tidak dapat mengubahnya.
          </p>
        </footer>
      </main>
    </div>
  );
}
