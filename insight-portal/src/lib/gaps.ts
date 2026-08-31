/**
 * Panels the brief asks for that no declared metric can answer in this build.
 *
 * Every entry here is a panel that renders an explicit unavailable state naming the metric that
 * would be required. None of them is computed in this application, and none is approximated from a
 * metric that is merely nearby.
 *
 * Two different reasons appear below and they are not interchangeable:
 *
 *   - `no_metric` — the figure is a legitimate thing to want, the warehouse may even hold the
 *     underlying rows, but contract 03 does not declare a metric for it. Deriving it here would be
 *     reimplementing business logic in TypeScript, which the brief forbids in as many words. It is
 *     a request to Backend, and it has been raised with the Lead.
 *   - `not_in_build` — the source does not exist at all. The operator chose a four-addon set, so
 *     there are no Coretax/e-Faktur or PPh withholding modules and no data behind a tax summary.
 *     Fabricating one would be worse than an empty panel by a wide margin.
 *
 * A ratio is called out wherever it is one, because "a ratio computed in a React component is a
 * brief violation" is the specific line this file exists to keep true.
 */

export type GapReason = "no_metric" | "not_in_build";

export interface MetricGap {
  /** What the brief asks for. */
  panel: string;
  /** The metric name that would answer it, for the Lead to hand to Backend. */
  requires: string;
  reason: GapReason;
  /** Why this application does not produce the number itself. */
  detail: string;
}

export const GAPS: Record<string, MetricGap[]> = {
  overview: [
    {
      panel: "Marjin kotor (gross margin)",
      requires: "gross_margin",
      reason: "no_metric",
      detail:
        "Margin is revenue minus cost of goods sold, and no metric exposes cost. Dividing revenue by anything available here would be a ratio computed in the client.",
    },
    {
      panel: "Umur piutang (AR ageing)",
      requires: "ar_ageing_bucket_amount",
      reason: "no_metric",
      detail:
        "Ageing buckets are a function of due date and settlement, which live in account.move.line. No metric binds that model.",
    },
    {
      panel: "Posisi kas (cash position)",
      requires: "cash_position",
      reason: "no_metric",
      detail:
        "Requires bank and cash journal balances. No metric exposes account balances in this build.",
    },
  ],
  sales: [
    {
      panel: "Corong penjualan (sales funnel)",
      requires: "sales_funnel_stage_count",
      reason: "no_metric",
      detail:
        "A funnel needs stage counts (quotation to order to invoice to payment). sales_total and sales_untaxed differ only by tax, so presenting them as funnel stages would be a fabrication.",
    },
    {
      panel: "Pertumbuhan tahun-ke-tahun (YoY growth %)",
      requires: "revenue_yoy_growth",
      reason: "no_metric",
      detail:
        "Both periods are shown side by side below, which is rendering. The growth percentage is a ratio and is not computed here.",
    },
  ],
  inventory: [
    {
      panel: "Nilai persediaan (stock value)",
      requires: "stock_valuation",
      reason: "no_metric",
      detail:
        "stock_net_quantity is a quantity in units. Multiplying it by a price fetched from somewhere else would be inventory valuation reimplemented in a React component.",
    },
    {
      panel: "Umur persediaan (stock ageing)",
      requires: "stock_ageing_bucket_qty",
      reason: "no_metric",
      detail:
        "mart_stock_position is a position and carries no date column, so age cannot be derived from it at all.",
    },
    {
      panel: "Perputaran persediaan (turnover)",
      requires: "stock_turnover_ratio",
      reason: "no_metric",
      detail: "Turnover is cost of goods sold over average inventory: a ratio, and neither term is available.",
    },
  ],
  finance: [
    {
      panel: "Laba rugi (profit and loss)",
      requires: "pnl_account_balance",
      reason: "no_metric",
      detail:
        "marts.fct_account_move_line exists in the warehouse, but no metric in contract 03 binds it and mart_account_move_line is not built. There is no declared figure to render.",
    },
    {
      panel: "Neraca (balance sheet)",
      requires: "balance_sheet_account_balance",
      reason: "no_metric",
      detail:
        "Same source, same gap. A balance sheet assembled from raw journal lines here would be an accounting engine in the dashboard.",
    },
    {
      panel: "Ringkasan PPN dan PPh",
      requires: "ppn_output_tax, pph_withheld",
      reason: "not_in_build",
      detail:
        "The operator chose a four-addon set. There are no Coretax/e-Faktur or PPh withholding modules in this build, so there is no tax data to summarise. This panel is deliberately empty rather than fabricated.",
    },
  ],
  ppob: [
    {
      panel: "Tingkat keberhasilan biller (biller success rate)",
      requires: "ppob_success_rate",
      reason: "no_metric",
      detail:
        "Successful transactions over total transactions is a ratio. The count per state is shown below, which is rendering the rows the semantic layer returned; the rate itself is not computed here.",
    },
  ],
};

export function gapsFor(view: string): MetricGap[] {
  return GAPS[view] ?? [];
}

/** Every metric this application actually queries, for the Lead to check against contract 03. */
export const METRICS_CONSUMED: ReadonlyArray<string> = [
  "revenue_net",
  "sales_total",
  "sales_untaxed",
  "stock_net_quantity",
  "ppob_transaction_count",
  "ppob_commission_revenue",
  "ppob_sla_breach_count",
];
