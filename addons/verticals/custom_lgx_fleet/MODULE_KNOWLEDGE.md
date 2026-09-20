# LGX — Armada (`custom_lgx_fleet`)

> Versi 19.0.1.0.0 · lisensi LGPL-3 · `capability_tags`: logistics, fleet, odol, compliance, indonesia
> Depends: custom_lgx_base, fleet

## Purpose

Perluasan fleet.vehicle: JBI/JBB dan dimensi bak untuk validasi ODOL, KIR, STNK, Kartu Pengawasan, GPS, dan pool kendaraan.

## Business Flow

**Kapasitas legal, bukan kapasitas aktual.** Zero ODOL mengubah model bisnis
trucking: tarif harus dihitung di atas JBI, bukan di atas apa yang sebenarnya
muat. Karena itu JBI dan dimensi bak adalah field master, dan perencanaan muatan
memvalidasi terhadapnya.

⚠ Tanggal penegakan disimpan sebagai ``ir.config_parameter``
``lgx.odol_enforcement_date`` dengan default 1 Januari 2027. Tanggal itu berasal
dari pernyataan pejabat dan siaran pers, **bukan peraturan yang sudah terbit**
(Lampiran A butir A12b). Sebelum tanggal itu sistem hanya memperingatkan; sejak
tanggal itu ia menolak. Keduanya diubah lewat konfigurasi, tanpa menyentuh kode.

Masa berlaku dokumen kendaraan diperlakukan sebagai DATA, bukan konstanta:
angka "6 bulan" untuk KIR beredar luas di sumber sekunder dan belum terkonfirmasi
ke PM 19/2021 fulltext (butir A5).

## Key Models

`fleet.vehicle` · JBI/JBB, dimensi bak, KIR, STNK, Kartu Pengawasan, GPS, pool
`lgx.vehicle.category` · kategori dan konfigurasi sumbu

## Public Methods

`fleet.vehicle.lgx_check_load(cargo_weight_kg, on_date)` · mengembalikan (level, pesan); level: `ok` / `unknown` / `warning` / `blocked`
`fleet.vehicle.lgx_odol_enforcement_date()` · dari `ir.config_parameter`
`fleet.vehicle._cron_warn_vehicle_documents()`

## Integration Points

`custom_lgx_tms.lgx.trip._compute_odol` memanggil `lgx_check_load`; `custom_lgx_doc` menyediakan mesin peringatan generik yang berdampingan dengan `lgx_document_status` di sini.

## Gotchas

**`unknown` BUKAN `ok`.** Kendaraan tanpa data JBI dinyatakan tidak dapat divalidasi. "Belum diperiksa" yang diperlakukan sebagai "aman" adalah cara sebuah armada berangkat kelebihan muatan dengan sistem yang tampak hijau.

**Tanggal penegakan Zero ODOL adalah PARAMETER, dan default 2027-01-01 berasal dari pernyataan pejabat serta siaran pers — bukan peraturan yang sudah terbit** (butir A12b). Di materi klien sebut sebagai kebijakan yang diumumkan.

**Yang ditegakkan di jalan adalah JBI, bukan JBB.** JBB adalah batas rancang bangun; JBI adalah yang tertulis di STNK dan yang diperiksa jembatan timbang.

⚠ Masa berlaku KIR ("6 bulan") belum terkonfirmasi ke PM 19/2021 fulltext (butir A5) — karena itu ia parameter, bukan konstanta.
