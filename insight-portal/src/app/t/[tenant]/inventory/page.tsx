import { Suspense } from "react";
import { redirect } from "next/navigation";

import { FreshnessSummary } from "@/components/Freshness";
import { Card, Kpi, MetricSection, Unavailable } from "@/components/Panel";
import { PanelSkeleton } from "@/components/PanelSkeleton";
import { ViewShell } from "@/components/ViewShell";
import { toQueryFilters, type PortalFilters } from "@/lib/filters";
import { gapsFor } from "@/lib/gaps";
import { loadOuOptions } from "@/lib/ou";
import type { PanelQuery } from "@/lib/panel";
import { metasOf, runPanels } from "@/lib/panels";
import { getSession } from "@/lib/session";
import { loadFilters } from "@/lib/view";

export const dynamic = "force-dynamic";

/**
 * Inventory.
 *
 * `mart_stock_position` is a POSITION, not a daily series: it carries no date column, so
 * `stock_net_quantity` declares no `date_range` filter and this view deliberately ignores the date
 * part of the persistent filter. That is stated on the page rather than left for a viewer to
 * discover by changing the dates and watching nothing happen.
 *
 * Three of the four panels the brief asks for - value, ageing, turnover - have no metric. The
 * "slow movers" panel is rendered as "lowest net movement" and labelled as such: ordering ascending
 * by a declared measure is the semantic layer's ORDER BY, but calling the result slow movers would
 * claim a business definition nobody declared.
 */
export default async function InventoryPage({
  params,
}: {
  params: Promise<{ tenant: string }>;
}) {
  await params;
  const session = await getSession();
  if (session === null) redirect("/login");
  const filters = await loadFilters();
  const ouOptions = await loadOuOptions(session, filters);

  return (
    <ViewShell
      session={session}
      active="inventory"
      title="Persediaan"
      intro="Posisi stok bersih per produk dan Operating Unit. Filter tanggal tidak berlaku di sini: mart_stock_position adalah posisi, bukan deret harian, sehingga metrik ini tidak mendeklarasikan filter rentang tanggal."
      filters={filters}
      ouOptions={ouOptions}
    >
      <Suspense fallback={<PanelSkeleton />}>
        <InventoryBody filters={filters} tenant={session.tenant_id} />
      </Suspense>
    </ViewShell>
  );
}

async function InventoryBody({ filters, tenant }: { filters: PortalFilters; tenant: string }) {
  // No date_range: this metric does not declare one, and sending it would be a 400 rather than a
  // filter that quietly did nothing.
  const scope = toQueryFilters(filters, { dateRange: false });
  const specs = {
    total: { metric: "stock_net_quantity", dimensions: [], filters: scope },
    topProducts: {
      metric: "stock_net_quantity",
      dimensions: ["product_key"],
      filters: scope,
      order_by: "-value",
      limit: 12,
    },
    lowestProducts: {
      metric: "stock_net_quantity",
      dimensions: ["product_key"],
      filters: scope,
      order_by: "value",
      limit: 12,
    },
    byOu: {
      metric: "stock_net_quantity",
      dimensions: ["operating_unit_id"],
      filters: scope,
      order_by: "-value",
    },
  } satisfies Record<string, PanelQuery>;

  const results = await runPanels(specs);
  const { metas } = metasOf(Object.values(results));
  const drillBase = "/t/" + tenant + "/drill";

  return (
    <div className="space-y-4">
      <FreshnessSummary metas={metas} />

      <div className="grid gap-3 sm:grid-cols-2">
        <Kpi
          label="Kuantitas bersih keseluruhan"
          result={results.total}
          hint="Masuk dikurangi keluar, dalam satuan - bukan nilai rupiah"
        />
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <MetricSection
          id="stock-top"
          title="12 produk dengan pergerakan bersih tertinggi"
          result={results.topProducts}
          chart="category"
          query={specs.topProducts}
          filename="stok-tertinggi"
          drillHref={drillBase + "?metric=stock_net_quantity&by=product_key,operating_unit_id&order=-value&limit=500"}
        />
        <MetricSection
          id="stock-lowest"
          title="12 produk dengan pergerakan bersih terendah"
          description="Diurutkan menaik oleh lapisan semantik. Ini bukan definisi bisnis untuk slow mover - definisi itu memerlukan metrik tersendiri."
          result={results.lowestProducts}
          chart="category"
          query={specs.lowestProducts}
          filename="stok-terendah"
          drillHref={drillBase + "?metric=stock_net_quantity&by=product_key,operating_unit_id&order=value&limit=500"}
        />
        <MetricSection
          id="stock-ou"
          title="Posisi stok per Operating Unit"
          result={results.byOu}
          chart="category"
          query={specs.byOu}
          filename="stok-per-ou"
          drillHref={drillBase + "?metric=stock_net_quantity&by=operating_unit_id,product_key&order=-value&limit=500"}
        />
      </div>

      <Card
        id="inventory-gaps"
        title="Belum tersedia pada tampilan ini"
        subtitle="Nilai, umur dan perputaran persediaan tidak memiliki metrik. Tidak ada satu pun yang diperkirakan di sini."
      >
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {gapsFor("inventory").map((gap) => (
            <Unavailable key={gap.requires} gap={gap} />
          ))}
        </div>
      </Card>
    </div>
  );
}
