/**
 * Format uang dan tanggal untuk permukaan penagihan.
 *
 * Terpisah dari `format.ts` karena berkas itu memformat ANGKA METRIK dari lapisan semantik —
 * satuan, ringkas, dan toleran terhadap null karena mart memang bisa kosong. Uang tidak boleh
 * diringkas dan tidak boleh dibulatkan: "1,7 jt" pada sebuah tagihan adalah cacat, bukan gaya.
 *
 * `amount_total` tiba sebagai STRING dari `pg`, bukan number. Itu disengaja oleh driver: NUMERIC
 * Postgres bisa melampaui presisi double JavaScript, dan mengubahnya menjadi number lebih dulu
 * berarti membulatkan uang sebelum sempat menampilkannya. Jadi parsing terjadi di sini, sekali.
 */

const RUPIAH = new Intl.NumberFormat("id-ID", {
  style: "currency",
  currency: "IDR",
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

export function formatMoney(value: string | number | null, currency: string | null): string {
  if (value === null) return "—";
  const n = typeof value === "string" ? Number(value) : value;
  if (!Number.isFinite(n)) return "—";
  if (currency !== null && currency !== "IDR") {
    return new Intl.NumberFormat("id-ID", {
      style: "currency",
      currency,
      minimumFractionDigits: 0,
      maximumFractionDigits: 2,
    }).format(n);
  }
  return RUPIAH.format(n);
}

const TANGGAL = new Intl.DateTimeFormat("id-ID", {
  day: "numeric",
  month: "long",
  year: "numeric",
  timeZone: "Asia/Jakarta",
});

export function formatDate(value: Date | null): string {
  return value === null ? "—" : TANGGAL.format(value);
}

/** Untuk atribut `value` pada `<input type="date">`, yang hanya menerima ISO. */
export function isoDate(value: Date): string {
  return value.toISOString().slice(0, 10);
}

export const STATUS_LABEL: Record<string, string> = {
  paid: "Lunas",
  overdue: "Jatuh tempo terlewat",
  posted: "Belum dibayar",
};

export const CLAIM_STATE_LABEL: Record<string, string> = {
  new: "Menunggu verifikasi operator",
  verified: "Terverifikasi",
  rejected: "Ditolak",
};
