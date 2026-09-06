/**
 * Panels the brief asks for that no declared metric can answer.
 *
 * Every entry renders an explicit unavailable state naming the metric that would be required.
 * None is computed here, and none is approximated from a metric that is merely nearby.
 *
 * Three reasons appear below and they are not interchangeable:
 *
 *   - `no_metric` - a legitimate figure to want, possibly with the rows sitting in the warehouse,
 *     but contract 03 declares no metric for it. Deriving it here would be business logic
 *     reimplemented in TypeScript, which the brief forbids in as many words.
 *   - `not_in_build` - the source does not exist at all. The operator chose a four-addon set, so
 *     there are no Coretax/e-Faktur or PPh withholding modules and no data behind a tax summary.
 *   - `no_data` - the metric could exist and the model is there, but the warehouse does not hold
 *     enough history for the figure to mean anything. Year-on-year is the case: the marts span
 *     2025-09-01 to 2026-08-31, so no month has a prior-year counterpart and every value would be
 *     null. Rendering an all-null chart would look like a broken panel rather than a stated limit.
 *
 * A ratio is called out wherever it is one, because "a ratio computed in a React component is a
 * brief violation" is the specific line this file exists to keep true. Where Backend has since
 * declared the ratio as a metric - `ppob_success_rate`, `revenue_mom_growth` - the panel renders
 * from the semantic layer and the entry is gone from this file rather than being kept as a
 * decorative caveat.
 */

export type GapReason = "no_metric" | "not_in_build" | "no_data";

export interface MetricGap {
  /** What the brief asks for. */
  panel: string;
  /** The metric or model that would answer it, for the Lead to hand to Backend. */
  requires: string;
  reason: GapReason;
  /** Why this application does not produce the number itself. */
  detail: string;
}

export const GAPS: Record<string, MetricGap[]> = {
  overview: [
    {
      panel: "Marjin kotor",
      requires: "gross_margin_pct",
      reason: "no_data",
      detail:
        "Metriknya SUDAH ADA - gross_margin_pct membaca mart_sales_price_tier_daily, yang membawa HPP yang disnapshot pada baris saat transaksi. Yang belum ada adalah barisnya untuk tenant ini: mart itu terisi dari data tingkat harga, dan tanpa satu baris pun di sana pembilang maupun penyebutnya kosong. Tenant yang memiliki barisnya melihat kartu marjin di baris KPI, bukan panel ini.",
    },
    {
      panel: "Umur piutang",
      requires: "ar_ageing_bucket_amount",
      reason: "no_metric",
      detail:
        "Ember umur piutang adalah fungsi tanggal jatuh tempo dan pelunasan. account_balance memuat payment_state tetapi bukan tanggal jatuh tempo, sehingga umur tidak dapat diturunkan darinya.",
    },
    {
      panel: "Posisi kas",
      requires: "cash_position",
      reason: "no_metric",
      detail:
        "Memerlukan saldo jurnal bank dan kas. account_balance memuat account_id tetapi warehouse tidak memiliki dim_account, sehingga tidak ada yang membedakan akun kas dari akun lain.",
    },
  ],
  sales: [
    {
      panel: "Corong penjualan",
      requires: "sales_funnel_stage_count",
      reason: "no_metric",
      detail:
        "Corong memerlukan jumlah per tahap (penawaran, pesanan, faktur, pelunasan). sales_total dan sales_untaxed hanya berbeda pajak, jadi menyajikannya sebagai tahap corong adalah pemalsuan.",
    },
    {
      panel: "Pertumbuhan tahun-ke-tahun (YoY)",
      requires: "revenue_yoy_growth",
      reason: "no_data",
      detail:
        "Warehouse memuat 2025-09-01 sampai 2026-08-31. Tidak ada bulan yang memiliki pembanding bulan yang sama tahun sebelumnya, sehingga setiap nilai YoY akan null. Pertumbuhan bulanan (MoM) ditampilkan sebagai gantinya dan diberi label MoM.",
    },
  ],
  inventory: [
    {
      panel: "Umur persediaan",
      requires: "stock_ageing_bucket_qty",
      reason: "no_metric",
      detail:
        "mart_stock_position adalah posisi dan tidak memuat kolom tanggal sama sekali, sehingga umur tidak dapat diturunkan darinya.",
    },
    {
      panel: "Perputaran persediaan",
      requires: "stock_turnover_ratio",
      reason: "no_metric",
      detail:
        "Perputaran adalah harga pokok penjualan dibagi rata-rata persediaan: sebuah rasio, dan kedua sukunya tidak tersedia.",
    },
  ],
  finance: [
    {
      panel: "Ringkasan PPN dan PPh",
      requires: "ppn_output_tax, pph_withheld",
      reason: "not_in_build",
      detail:
        "Operator memilih empat addon. Tidak ada modul Coretax/e-Faktur maupun pemotongan PPh pada build ini, sehingga tidak ada data pajak untuk diringkas. Panel ini sengaja dikosongkan, bukan dikarang.",
    },
  ],
  ppob: [],
  pricing: [
    {
      panel: "Cakupan HPP dan tingkat harga",
      requires: "price_tier_coverage_pct",
      reason: "no_metric",
      detail:
        "mart_sales_price_tier_daily membawa lines_without_hpp, lines_without_hj_level dan lines_default_tier_unknown justru agar bagian yang tidak terhitung bisa dinyatakan, tetapi tidak ada metrik yang mengikatnya. Menghitungnya di sini berarti membagi dua kolom di React, dan porsi yang tidak terhitung adalah tepat angka yang paling berbahaya untuk dikarang.",
    },
    {
      panel: "Volume dalam kilogram",
      requires: "sales_qty_base",
      reason: "not_in_build",
      detail:
        "Kolomnya tidak ada: sale.order.line pada skema tenant ini tidak menyimpan qty base. Mengikat metrik ke product_uom_qty akan menjumlahkan SAK, TON dan KG lalu menyebut hasilnya kilogram - satu-satunya kesalahan pada halaman ini yang tidak akan terlihat salah.",
    },
  ],
};

/** Gaps that stop being gaps once a tenant has the data behind them. Keyed by view, then panel. */
const RESOLVED_BY_PRICING: Readonly<Record<string, readonly string[]>> = {
  overview: ["gross_margin_pct"],
};

/**
 * The unavailable panels for a view.
 *
 * `options.pricing` removes the entries that a tenant with price-tier data can actually answer.
 * This is not cosmetic tidying: an "unavailable" panel is an assertion that the number is not
 * produced, and leaving it on a page that shows the number two rows above would make the strongest
 * statement on the screen the false one.
 */
export function gapsFor(view: string, options: { pricing?: boolean } = {}): MetricGap[] {
  const all = GAPS[view] ?? [];
  if (options.pricing !== true) return [...all];
  const resolved = RESOLVED_BY_PRICING[view] ?? [];
  return all.filter((gap) => !resolved.includes(gap.requires));
}

/**
 * Every metric this application queries, for the Lead to check against contract 03. All fifteen are
 * declared in the live registry; the portal queries no figure that is not on this list.
 */
export const METRICS_CONSUMED: ReadonlyArray<string> = [
  "revenue_net",
  "stock_valuation",
  "revenue_mom_growth",
  "sales_total",
  "sales_untaxed",
  "stock_net_quantity",
  "account_balance",
  "ppob_transaction_count",
  "ppob_commission_revenue",
  "ppob_sla_breach_count",
  "ppob_success_rate",
  "sales_by_price_tier",
  "gross_margin_by_price_tier",
  "gross_margin_pct",
  "sales_below_default_tier_pct",
];
