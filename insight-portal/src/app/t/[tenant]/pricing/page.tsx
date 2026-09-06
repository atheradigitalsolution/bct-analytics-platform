import { Suspense } from "react";
import { redirect } from "next/navigation";

import { FreshnessSummary } from "@/components/Freshness";
import { Card, Kpi, MetricSection, Unavailable } from "@/components/Panel";
import { NotApplicable } from "@/components/NotApplicable";
import { PanelSkeleton } from "@/components/PanelSkeleton";
import { ViewShell } from "@/components/ViewShell";
import { capabilityOf, loadShell } from "@/lib/capabilities";
import { toQueryFilters, type PortalFilters } from "@/lib/filters";
import { gapsFor } from "@/lib/gaps";
import { loadOuOptions } from "@/lib/ou";
import type { PanelQuery } from "@/lib/panel";
import { metasOf, runPanels } from "@/lib/panels";
import { getSession } from "@/lib/session";
import { loadFilters } from "@/lib/view";

export const dynamic = "force-dynamic";

/**
 * Price tiers and gross margin.
 *
 * WHAT THIS VIEW IS FOR. A client that sells the same product at nine published prices needs to
 * know which tier the money actually came in at, and what was left after cost. Neither question is
 * answerable from `mart_sales_daily`: it carries no tier and no cost. Both are answerable from
 * `mart_sales_price_tier_daily`, which snapshots `ndi_hj_level` and the line's cost at the moment
 * the price was computed - Odoo 19 stores no `pricelist_item_id` on `sale.order.line`, so a tier
 * that was not captured then cannot be reconstructed now.
 *
 * MARGIN IS `gross_margin_pct`, A DECLARED RATIO. It is not gross margin divided by sales in this
 * file. The metric divides two sums with a NULLIF guard, so a tier that sold nothing yields null
 * rather than zero, and the ratio weights a 10-TON line above a 10-SAK line the way summing does.
 *
 * COST IS THE SNAPSHOT, NOT TODAY'S. Valuing January's sales at September's `standard_price` is
 * the ordinary way this figure goes quietly wrong; the mart carries `lines_without_hpp` so the
 * uncovered part can be stated, and the unavailable panel at the foot says why it is not stated
 * here as a percentage.
 *
 * THE TIER NUMBER RUNS THE OTHER WAY FROM THE PRICE. A larger tier number is a cheaper price -
 * verified against this deployment's data rather than assumed, in `sales_below_default_tier_pct`'s
 * own description - which is why "below the customer's default" is `hj_level >` the default and
 * why nothing on this page presents the tier as an ordinal quality ranking.
 */
export default async function PricingPage({ params }: { params: Promise<{ tenant: string }> }) {
  await params;
  const session = await getSession();
  if (session === null) redirect("/login");
  const filters = await loadFilters();
  const { ouOptions, capabilities, views } = await loadShell(
    session,
    loadOuOptions(session, filters),
  );
  const capability = capabilityOf(capabilities, "pricing");

  return (
    <ViewShell
      session={session}
      active="pricing"
      title="Harga & Margin"
      intro="Penjualan dan margin kotor menurut tingkat harga HJ1-HJ9 yang benar-benar dipakai pada baris transaksi, dari mart_sales_price_tier_daily. Ukurannya sebelum pajak; harga pokok diambil dari snapshot pada baris, bukan biaya hari ini."
      filters={filters}
      ouOptions={ouOptions}
      views={views}
    >
      {capability.available ? (
        <Suspense fallback={<PanelSkeleton />}>
          <PricingBody filters={filters} tenant={session.tenant_id} />
        </Suspense>
      ) : (
        <NotApplicable
          id="pricing-not-applicable"
          view="Harga & Margin"
          mart="mart_sales_price_tier_daily"
          decided={capability.decided}
        />
      )}
    </ViewShell>
  );
}

async function PricingBody({ filters, tenant }: { filters: PortalFilters; tenant: string }) {
  const range = toQueryFilters(filters);
  const specs = {
    salesTotal: { metric: "sales_by_price_tier", dimensions: [], filters: range },
    marginTotal: { metric: "gross_margin_by_price_tier", dimensions: [], filters: range },
    marginPct: { metric: "gross_margin_pct", dimensions: [], filters: range },
    belowDefault: { metric: "sales_below_default_tier_pct", dimensions: [], filters: range },
    salesByTier: {
      metric: "sales_by_price_tier",
      dimensions: ["hj_level_label"],
      filters: range,
      order_by: "hj_level_label",
    },
    marginPctByTier: {
      metric: "gross_margin_pct",
      dimensions: ["hj_level_label"],
      filters: range,
      order_by: "hj_level_label",
    },
    salesByMonth: {
      metric: "sales_by_price_tier",
      dimensions: ["date_month"],
      filters: range,
      order_by: "date_month",
    },
    salesByCustomerType: {
      metric: "sales_by_price_tier",
      dimensions: ["customer_type"],
      filters: range,
      order_by: "-value",
    },
    marginByRegion: {
      metric: "gross_margin_by_price_tier",
      dimensions: ["sales_region"],
      filters: range,
      order_by: "-value",
    },
    salesByChannel: {
      metric: "sales_by_price_tier",
      dimensions: ["sales_channel"],
      filters: range,
      order_by: "-value",
    },
    belowDefaultByCustomerType: {
      metric: "sales_below_default_tier_pct",
      dimensions: ["customer_type"],
      filters: range,
      order_by: "-value",
    },
  } satisfies Record<string, PanelQuery>;

  const results = await runPanels(specs);
  const { metas } = metasOf(Object.values(results));
  const drillBase = "/t/" + tenant + "/drill";

  return (
    <div className="space-y-4">
      <FreshnessSummary metas={metas} />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Kpi
          label="Penjualan sebelum pajak"
          result={results.salesTotal}
          hint="price_subtotal, bukan price_total - memakai price_total menaikkan angka sebesar PPN"
        />
        <Kpi
          label="Margin kotor"
          result={results.marginTotal}
          hint="Penjualan dikurangi HPP yang disnapshot pada baris saat transaksi"
        />
        <Kpi label="Persentase margin kotor" result={results.marginPct} />
        <Kpi
          label="Di bawah tingkat default pelanggan"
          result={results.belowDefault}
          hint="Nomor tingkat lebih besar berarti harga lebih murah - arah ini diverifikasi terhadap data"
        />
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <MetricSection
          id="pricing-sales-tier"
          title="Penjualan per tingkat harga"
          description="Dimensi hj_level_label. Baris yang tingkat harganya tidak tercatat muncul sebagai kelompok tersendiri dan tidak dibuang."
          result={results.salesByTier}
          chart="category"
          query={specs.salesByTier}
          filename="penjualan-per-tingkat-harga"
          drillHref={
            drillBase +
            "?metric=sales_by_price_tier&by=hj_level_label,product_key&order=-value&limit=500"
          }
          drillLabel="Telusuri ke produk per tingkat"
        />
        <MetricSection
          id="pricing-margin-tier"
          title="Persentase margin kotor per tingkat harga"
          description="gross_margin_pct. Tingkat yang tidak menjual apa pun pada rentang ini bernilai kosong, bukan nol - penyebut nol dijaga NULLIF di lapisan semantik."
          result={results.marginPctByTier}
          chart="category"
          query={specs.marginPctByTier}
          filename="margin-per-tingkat-harga"
        />
        <MetricSection
          id="pricing-sales-month"
          title="Penjualan berjenjang harga per bulan"
          description="Jangan menjumlahkan panel ini dengan pendapatan neto: mart_revenue_daily sudah memuat kanal POS, sehingga POS akan terhitung dua kali."
          result={results.salesByMonth}
          chart="time"
          query={specs.salesByMonth}
          filename="penjualan-tingkat-harga-bulanan"
          drillHref={
            drillBase +
            "?metric=sales_by_price_tier&by=date_day,hj_level_label&order=-value&limit=500"
          }
          drillLabel="Telusuri ke tingkat harian"
        />
        <MetricSection
          id="pricing-sales-customer-type"
          title="Penjualan per jenis pelanggan"
          result={results.salesByCustomerType}
          chart="category"
          query={specs.salesByCustomerType}
          filename="penjualan-per-jenis-pelanggan"
          drillHref={
            drillBase +
            "?metric=sales_by_price_tier&by=customer_type,hj_level_label&order=-value&limit=500"
          }
        />
        <MetricSection
          id="pricing-margin-region"
          title="Margin kotor per wilayah penjualan"
          result={results.marginByRegion}
          chart="category"
          query={specs.marginByRegion}
          filename="margin-per-wilayah"
          drillHref={
            drillBase +
            "?metric=gross_margin_by_price_tier&by=sales_region,customer_type&order=-value&limit=500"
          }
        />
        <MetricSection
          id="pricing-sales-channel"
          title="Penjualan per kanal"
          description="mart_sales_price_tier_daily meng-UNION kanal sale dan pos; keduanya dijumlahkan dengan sengaja pada KPI di atas, dan dipisah di sini."
          result={results.salesByChannel}
          chart="category"
          query={specs.salesByChannel}
          filename="penjualan-tingkat-harga-per-kanal"
        />
        <MetricSection
          id="pricing-below-default"
          title="Di bawah tingkat default, per jenis pelanggan"
          description="Penyebutnya line_count, jadi baris yang tingkat atau default-nya tidak diketahui ikut menekan rasio ke bawah. Ini indikator disiplin harga, bukan tuduhan."
          result={results.belowDefaultByCustomerType}
          chart="category"
          query={specs.belowDefaultByCustomerType}
          filename="di-bawah-tingkat-default"
        />
      </div>

      <Card
        id="pricing-gaps"
        title="Belum tersedia pada tampilan ini"
        subtitle="Diminta oleh brief, tidak dihitung di sini."
      >
        <div className="grid gap-3 sm:grid-cols-2">
          {gapsFor("pricing").map((gap) => (
            <Unavailable key={gap.requires} gap={gap} />
          ))}
        </div>
      </Card>
    </div>
  );
}
