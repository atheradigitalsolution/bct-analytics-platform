# LGX — Kepabeanan (`custom_lgx_customs`)

> Versi 19.0.1.0.0 · lisensi LGPL-3 · `capability_tags`: logistics, customs, ppjk, indonesia, import-duty, btki
> Depends: custom_lgx_ff

## Purpose

Deklarasi PIB/PEB dan dokumen TPB, HS code BTKI, perhitungan BM/PPN impor/PPh 22, Ahli Kepabeanan bersertifikat, jaminan transaksional, dan eksposur PPJK.

## Business Flow

**Identitas prinsipal memakai NIB + NPWP + jenis akses, bukan NIK.** PMK
219/2019 mengganti konsep NIK/NP PPJK dengan "Akses Kepabeanan" yang melekat
pada NIB dari OSS dan NPWP. Modul ini sengaja TIDAK menyediakan field "NIK
Kepabeanan", dan tidak boleh ditambahkan kemudian.

**Jaminan adalah entitas transaksional, bukan atribut master PPJK.** Customs
bond bukan syarat izin; ia melekat per transaksi atau per fasilitas (impor
sementara, BC 2.6.1, keberatan). Memodelkannya sebagai field pada master PPJK
akan membuat jaminan yang sudah dapat ditarik tidak pernah ditarik, karena tidak
ada record yang jatuh tempo.

**Eksposur PPJK adalah risiko finansial nyata.** PMK 219/2019 Pasal 24 ayat 2:
PPJK bertanggung jawab atas bea masuk terutang bila importir tidak ditemukan.
Karena itu total nilai deklarasi berjalan per prinsipal adalah laporan, bukan
sekadar angka yang bisa dihitung kalau diminta.

**Bea masuk dan pajak impor masuk job sebagai TALANGAN**, bukan sebagai biaya.
Ia dibayarkan atas nama importir dan ditagihkan kembali apa adanya; melewatkannya
ke laba rugi akan menggelembungkan HPP berkali lipat pada job impor.

## Key Models

`lgx.customs.declaration` / `.line` · PIB, PEB, dokumen TPB dan PLB
`lgx.hs.code` · tarif BTKI dengan masa berlaku
`lgx.customs.expert` · Ahli Kepabeanan bersertifikat
`lgx.customs.guarantee` · jaminan TRANSAKSIONAL

## Public Methods

`lgx.customs.declaration.action_submit/receive/respond/release`
`lgx.customs.declaration.action_generate_job_charges()` · pungutan menjadi baris TALANGAN
`lgx.customs.declaration.lgx_ppjk_exposure(date_from, date_to, office)`
`lgx.customs.guarantee._cron_flag_guarantees()`

## Integration Points

Memeriksa masa berlaku sertifikat ahli SENDIRI di modul ini, tidak menunggu mesin generik `custom_lgx_doc`: LGX-C01 menuntut blokir, dan aturan yang menahan uang tidak boleh menunggu fase berikutnya.

## Gotchas

**TIDAK ADA field "NIK Kepabeanan", dan tidak boleh ditambahkan.** PMK 219/2019 mengganti NIK/NP PPJK dengan Akses Kepabeanan yang melekat pada NIB (dari OSS) dan NPWP.

**Urutan perhitungan menentukan hasilnya:** `Nilai Impor (DPP) = Nilai Pabean + Bea Masuk`. PPN impor, PPnBM dan PPh 22 dihitung dari NILAI IMPOR, bukan dari CIF. Menghitungnya langsung dari CIF selalu menghasilkan angka lebih kecil, dan selisihnya baru ketahuan saat SPPB tidak kunjung terbit.

**Kurs yang dipakai adalah kurs KMK, bukan kurs pembukuan.** Nilai rupiah PIB yang dihitung dengan kurs pembukuan adalah kesalahan yang langsung terlihat saat pemeriksaan.

**Jaminan adalah entitas transaksional.** Memodelkannya sebagai atribut master PPJK membuat jaminan yang sudah dapat ditarik tidak pernah ditarik — tidak ada record yang jatuh tempo.

**Kantor pabean wajib punya `partner_id`** sebelum pungutan dapat disalin ke job: baris talangan tanpa pihak adalah utang yang tidak dapat direkonsiliasi.

**Daftar HS code bawaan hanya CONTOH** (8 pos). BTKI penuh (~11.000) adalah pekerjaan jalur master data — butir A25, prasyarat masuk Fase 2 yang sebenarnya.
