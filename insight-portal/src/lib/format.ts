/**
 * Display formatting only.
 *
 * Formatting a number the semantic layer returned is presentation. Deriving a new number is not,
 * and nothing in this file does it: there is no addition, no division and no aggregation here.
 * `Intl.NumberFormat` with a fixed locale keeps the server render and the client hydration
 * identical, which a locale read from the request would not.
 */

const IDR = new Intl.NumberFormat("id-ID", {
  style: "currency",
  currency: "IDR",
  maximumFractionDigits: 0,
});

const IDR_COMPACT = new Intl.NumberFormat("id-ID", {
  style: "currency",
  currency: "IDR",
  notation: "compact",
  maximumFractionDigits: 1,
});

const PLAIN = new Intl.NumberFormat("id-ID", { maximumFractionDigits: 2 });
const PLAIN_COMPACT = new Intl.NumberFormat("id-ID", {
  notation: "compact",
  maximumFractionDigits: 1,
});

/** Format one measure using the unit the API reported for it. */
export function formatValue(value: number, unit: string | null): string {
  if (unit === "IDR") return IDR.format(value);
  if (unit === "unit") return PLAIN.format(value) + " unit";
  return PLAIN.format(value);
}

export function formatCompact(value: number, unit: string | null): string {
  if (unit === "IDR") return IDR_COMPACT.format(value);
  return PLAIN_COMPACT.format(value);
}

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
  "Jul", "Agu", "Sep", "Okt", "Nov", "Des",
];

/** `2026-01-01` to `Jan 2026`. Pure string work; no timezone conversion is applied to a date-only value. */
export function formatMonth(value: string): string {
  if (!/^\d{4}-\d{2}/.test(value)) return value;
  const year = value.slice(0, 4);
  const month = Number.parseInt(value.slice(5, 7), 10);
  return (MONTHS[month - 1] ?? value) + " " + year;
}

export function formatDay(value: string): string {
  if (!/^\d{4}-\d{2}-\d{2}/.test(value)) return value;
  const day = value.slice(8, 10);
  const month = Number.parseInt(value.slice(5, 7), 10);
  return day + " " + (MONTHS[month - 1] ?? "") + " " + value.slice(0, 4);
}

/**
 * The pipeline timestamp, shown as an absolute instant in UTC.
 *
 * Deliberately absolute. A relative rendering ("4 minutes ago") would be the viewer's clock doing
 * arithmetic on a pipeline fact, and the one thing this dashboard must not do about freshness is
 * substitute a clock for the pipeline. Staleness itself comes from `meta.is_stale`, which the
 * warehouse decided.
 */
export function formatRefreshedAt(value: string | null): string {
  if (value === null) return "tidak diketahui";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  const pad = (n: number): string => String(n).padStart(2, "0");
  return (
    parsed.getUTCFullYear() +
    "-" + pad(parsed.getUTCMonth() + 1) +
    "-" + pad(parsed.getUTCDate()) +
    " " + pad(parsed.getUTCHours()) +
    ":" + pad(parsed.getUTCMinutes()) +
    ":" + pad(parsed.getUTCSeconds()) +
    " UTC"
  );
}

/** "60 detik" / "15 menit" / "60 menit". Describes the SLA the API reported; derives nothing. */
export function formatSla(seconds: number): string {
  if (seconds < 60) return seconds + " detik";
  if (seconds % 3600 === 0 && seconds >= 3600) return seconds / 3600 + " jam";
  return Math.round(seconds / 60) + " menit";
}

const DIMENSION_LABELS: Record<string, string> = {
  date_day: "Tanggal",
  date_month: "Bulan",
  tenant_id: "Tenant",
  operating_unit_id: "Operating Unit",
  partner_key: "Mitra",
  product_key: "Produk",
  product_id: "ID Produk",
  company_id: "Perusahaan",
  revenue_channel: "Kanal",
  biller_key: "Biller",
  biller_code: "Kode Biller",
  biller_category: "Kategori Biller",
  state: "Status",
  value: "Nilai",
};

export function dimensionLabel(name: string): string {
  return DIMENSION_LABELS[name] ?? name;
}

/**
 * Render a dimension cell.
 *
 * `operating_unit_id === -1` is the explicit UNASSIGNED member of `dim_operating_unit`, not a
 * missing value, and it is labelled as such so a viewer does not read it as a bug.
 */
export function formatDimension(dimension: string, value: string | number | null): string {
  if (value === null) return "—";
  if (dimension === "operating_unit_id" && value === -1) return "Tanpa Operating Unit";
  if (dimension === "date_month" && typeof value === "string") return formatMonth(value);
  if (dimension === "date_day" && typeof value === "string") return formatDay(value);
  return String(value);
}
