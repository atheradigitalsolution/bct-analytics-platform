/**
 * Umpan balik satu-arah: dari route handler penagihan ke halaman yang menampilkannya.
 *
 * KENAPA BERKAS INI ADA. `POST /api/billing/claim` sudah sejak awal mengalihkan ke
 * `/billing?ok=1`, `/billing?error=faktur`, `/billing/<id>?error=isian` dan
 * `/billing/<id>?error=simpan` — dan tidak satu pun halaman tujuan membaca `searchParams`. Klien
 * yang menekan "Kirim konfirmasi" karena itu melihat halaman tagihan yang sama persis seperti
 * sebelum ia menekan tombol, apa pun yang terjadi: berhasil, ditolak validasi, atau gagal
 * disimpan. Untuk klien yang sedang diblokir karena tagihan, itu berarti satu-satunya tindakan
 * yang bisa mengakhiri blokirnya tidak memberi tanda apa pun bahwa ia terjadi.
 *
 * KENAPA KODENYA ADA DI SATU TEMPAT. Route handler menulis kode, halaman membacanya. Dua daftar
 * literal yang tersebar akan berpisah pada perubahan pertama, dan cara ia gagal adalah senyap:
 * sebuah pengalihan dengan kode yang tidak dikenali menghasilkan halaman tanpa pesan — yaitu
 * persis bug yang berkas ini perbaiki. Route handler mengimpor konstanta ini, jadi kompilator
 * yang memeriksa, bukan pembaca.
 *
 * KENAPA PESANNYA DI SERVER DAN BUKAN DI URL. Query string bisa disunting siapa saja. Kalau
 * teksnya ikut di URL, alamat portal ini menjadi alat menampilkan kalimat pilihan penyerang di
 * dalam halaman ber-merek ATHERA. Yang menyeberang hanyalah kode pendek dari daftar tertutup;
 * kode yang tidak ada di daftar tidak menampilkan apa pun.
 */

export type NoticeTone = "ok" | "error";

export interface Notice {
  tone: NoticeTone;
  title: string;
  detail: string;
}

/** Nilai `?ok=`. Satu-satunya nilai yang diterima; string lain diabaikan. */
export const CLAIM_OK = "1";

/** Nilai `?error=` yang boleh ditulis route handler penagihan. */
export const CLAIM_ERROR = {
  /** `invoice_id` tidak menunjuk faktur milik tenant sesi ini. */
  INVOICE: "faktur",
  /** Jumlah, tanggal, atau bank pengirim tidak lolos validasi bentuk. */
  INPUT: "isian",
  /** Penulisan ke antrean klaim gagal — termasuk penolakan trigger tenant. */
  SAVE: "simpan",
} as const;

const CLAIM_NOTICE: Record<string, Notice> = {
  [CLAIM_OK]: {
    tone: "ok",
    title: "Konfirmasi pembayaran Anda sudah kami terima.",
    detail:
      "Operator akan mencocokkannya dengan rekening koran. Status faktur berubah setelah " +
      "pencocokan itu selesai, bukan seketika — konfirmasi Anda muncul di daftar di bawah " +
      "dengan status “Menunggu verifikasi operator”.",
  },
  [CLAIM_ERROR.INVOICE]: {
    tone: "error",
    title: "Konfirmasi tidak tercatat: faktur tidak ditemukan.",
    detail:
      "Faktur yang dirujuk tidak ada pada akun ini. Buka fakturnya dari daftar di bawah, lalu " +
      "kirim konfirmasi dari halaman rinciannya.",
  },
  [CLAIM_ERROR.INPUT]: {
    tone: "error",
    title: "Konfirmasi tidak tercatat: isian belum lengkap.",
    detail:
      "Jumlah harus lebih besar dari nol, tanggal transfer harus berupa tanggal yang sah, dan " +
      "bank pengirim wajib diisi. Perbaiki lalu kirim ulang — data yang sudah Anda ketik tidak " +
      "terkirim ke mana pun.",
  },
  [CLAIM_ERROR.SAVE]: {
    tone: "error",
    title: "Konfirmasi tidak tercatat: gagal menyimpan.",
    detail:
      "Ini kegagalan di sisi kami, bukan pada isian Anda. Coba lagi; kalau tetap gagal, " +
      "sampaikan nomor faktur dan tanggal transfer lewat kontak di halaman rincian faktur.",
  },
};

/** Nilai `?reason=` yang ditulis middleware saat memantulkan ke `/subscription`. */
export const REFUSAL_REASON = {
  INACTIVE: "subscription_inactive",
  NOT_ENTITLED: "product_not_entitled",
} as const;

function first(value: string | string[] | undefined): string {
  if (typeof value === "string") return value;
  if (Array.isArray(value) && typeof value[0] === "string") return value[0];
  return "";
}

/**
 * Terjemahkan `?ok=` / `?error=` menjadi sebuah `Notice`, atau `null`.
 *
 * Nilai di luar daftar menghasilkan `null` — bukan pesan “kode tidak dikenal”, yang hanya akan
 * memberi tahu penyunting URL bahwa ia sedang mendekati sesuatu.
 */
export function claimNotice(
  params: Record<string, string | string[] | undefined>,
): Notice | null {
  const ok = first(params.ok);
  if (ok !== "") return CLAIM_NOTICE[ok] ?? null;
  const error = first(params.error);
  if (error !== "") return CLAIM_NOTICE[error] ?? null;
  return null;
}

/**
 * Terjemahkan `?reason=` milik middleware.
 *
 * `expected` adalah kebenaran yang halaman turunkan sendiri dari sesi. Kalau query string tidak
 * cocok dengannya, query string yang dibuang — sebuah URL yang disunting tidak boleh mengubah
 * alasan yang ditampilkan, dan halaman `/subscription` sudah menurunkan alasan sebenarnya dari
 * klaim token. Ini menjadikan `?reason=` apa yang middleware katakan bahwa ia adalah: petunjuk
 * kata-kata, bukan sumber kebenaran.
 */
export function refusalMatchesSession(
  params: Record<string, string | string[] | undefined>,
  expected: string,
): boolean {
  const reason = first(params.reason);
  return reason !== "" && reason === expected;
}
