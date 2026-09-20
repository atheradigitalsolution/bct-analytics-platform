# LGX — Pajak Indonesia untuk Logistik (`custom_lgx_tax_id`)

> Versi 19.0.1.0.0 · lisensi LGPL-3 · `capability_tags`: logistics, indonesian-tax, ppn, pph23, pph15, coretax, nitku
> Depends: custom_lgx_billing, custom_coretax

## Purpose

PPN besaran tertentu JPT, dasar PPh 23 yang mengecualikan reimbursement, keputusan PPh 23 versus PPh 15, ekspor jasa 0% dengan validasi keras, dan NITKU cabang pada faktur.

## Business Flow

**Modul ini MEMPERLUAS, tidak menduplikasi.** Repo sudah memuat
``custom_coretax`` (NSFP, e-Faktur XML, Bukti Potong), ``custom_coretax_bupot``
(Bupot PPh Unifikasi termasuk Pasal 15 dan 23) dan ``custom_pph_witholding``
(registry tarif dan mesin perhitungan). Yang belum ada di sana, dan hanya ada di
sini, adalah pengetahuan yang khusus logistik.

**NSFP DISIMPAN dari respons DJP, tidak pernah dihasilkan sendiri.** Sejak
Coretax, nomor seri faktur pajak 17 digit diberikan server saat faktur di-upload
dan disetujui (PER-11/PJ/2025 Pasal 37). Tidak ada lagi permintaan jatah nomor
seri, dan logika "range NSFP" lama harus dibuang. Modul ini karena itu tidak
memuat satu pun ``ir.sequence`` untuk nomor pajak — dan itu dapat diperiksa
dengan grep.

**Dasar PPh 23 mengecualikan reimbursement.** PMK 141/2015: jumlah bruto tidak
termasuk reimbursement yang dapat dibuktikan dengan faktur tagihan dan/atau
bukti pembayaran dari pihak ketiga. Yang menghubungkannya ke model data adalah
``lgx.job.charge.nature``.

**Arah pemotongan menentukan NPWP siapa yang diuji.** Kenaikan 100% menjadi 4%
selalu bergantung pada NPWP PENERIMA PENGHASILAN — vendor pada bukti potong
keluaran, perusahaan sendiri pada potongan yang diterima dari pelanggan. Menguji
``partner_id.vat`` pada faktur penjualan adalah kesalahan arah, dan hasilnya
salah setiap kali pelanggan tidak ber-NPWP sementara perusahaan ber-NPWP.

**Dua hal sengaja TIDAK otomatis penuh** (§11.1 langkah 3 dan 5): tagihan tanpa
freight charge, dan angkutan umum yang dibebaskan. Keduanya berada di wilayah
yang belum pasti secara regulasi, dan keputusan diam-diam di sana menciptakan
risiko sengketa yang baru ketahuan saat pemeriksaan.

## Key Models

`lgx.wht.rate` · master tarif pot-put dengan masa berlaku
`account.move` · perlakuan PPN, dasar pot-put, NITKU, dan validasi keras sebelum posting

## Public Methods

`account.move._compute_lgx_vat_treatment()` · alur keputusan §11.1
`account.move._lgx_wht_recipient()` · siapa PENERIMA PENGHASILAN pada dokumen ini
`account.move._lgx_check_export_service_documents()` · dipanggil dari `_post`
`lgx.wht.rate.lgx_find(wht_type, on_date, company)`

## Integration Points

Membaca `lgx.job.charge.nature` dan `.is_freight_charge`; NITKU diambil dari `operating.unit.lgx_nitku`.

## Gotchas

**TIDAK ADA `ir.sequence` di modul ini, dan itu dapat diperiksa dengan grep.** NSFP 17 digit datang dari respons DJP dan disimpan `custom_coretax.account_move.x_custom_nsfp` (PER-11/PJ/2025 Pasal 37). Logika "range NSFP" lama harus dibuang.

**Arah pemotongan menentukan NPWP SIAPA yang diuji.** Kenaikan 100% menjadi 4% selalu bergantung pada NPWP penerima penghasilan: vendor pada bukti potong keluaran, perusahaan sendiri pada potongan yang diterima. Menguji `partner_id.vat` pada faktur penjualan adalah kesalahan arah, dan hasilnya salah setiap kali pelanggan tidak ber-NPWP sementara perusahaan ber-NPWP.

**Dua hal sengaja TIDAK otomatis penuh:** tagihan tanpa freight charge (butir A3 — tidak ditemukan aturan eksplisit), dan pembebasan angkutan umum (praktik pemeriksaan masih memakai indikator plat kuning). Keduanya memunculkan peringatan dan menuntut dasar tertulis.

**PPh 15 penerbangan dalam negeri 1,8% TIDAK FINAL** (SE-35/PJ.4/1996) — dapat dikreditkan. Butir A4 sudah ditutup; sumber sekunder yang menyebutnya final keliru, dan mengikutinya berarti kehilangan kredit pajak yang sah.

**Modul ini MEMPERLUAS `custom_coretax`, `custom_coretax_bupot` dan `custom_pph_witholding`** yang sudah ada di repo — tidak menduplikasinya.
