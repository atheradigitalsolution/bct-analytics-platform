# LGX — Tarif, Penawaran, Kontrak (`custom_lgx_pricing`)

> Versi 19.0.1.0.0 · lisensi LGPL-3 · `capability_tags`: logistics, pricing, rate-card, quotation, contract
> Depends: custom_lgx_job

## Purpose

Rate card beli dan jual sebagai record terpisah, penawaran berversi, kontrak pelanggan, dan konversi penawaran menjadi job berikut akrual biayanya.

## Business Flow

**Harga beli dan harga jual adalah record terpisah**, bukan dua kolom pada
record yang sama. Keduanya punya sumber, pemilik, dan siklus pembaruan yang
berbeda: harga beli datang dari carrier dan berubah saat kontrak carrier
diperbarui; harga jual dimiliki penjualan dan berubah saat strategi harga
berubah. Menggabungkannya membuat setiap pembaruan tarif carrier menyentuh
harga jual yang sudah dijanjikan ke pelanggan.

**Konversi penawaran ke job membuat DUA baris charge per baris penawaran** —
satu pendapatan dari harga jual, satu biaya dari harga beli, keduanya berstatus
estimasi. Inilah yang membuat akrual biaya terbentuk sejak job lahir, bukan
menunggu tagihan vendor yang baru datang dua sampai enam minggu kemudian.

**Faktor volumetrik hidup di rate card**, bukan di kode. Angka 6000 untuk udara
adalah default IATA, tetapi tiap carrier boleh berbeda, dan pembulatan berbeda
lagi. Menaruhnya di kode berarti setiap carrier baru adalah rilis modul.

## Key Models

`lgx.rate.card` / `.line` / `lgx.rate.break` / `lgx.rate.surcharge` · tarif berversi
`lgx.quote` / `lgx.quote.line` · penawaran dengan harga beli dan jual berdampingan
`lgx.contract` · kontrak pelanggan; tarifnya dipakai lebih dulu dari rate card umum

## Public Methods

`lgx.rate.card.lgx_find_applicable(direction, on_date, ..., any_partner)` · yang paling khusus lebih dulu
`lgx.rate.card.lgx_chargeable_weight(...)` · mengembalikan (berat, DASAR YANG MENANG)
`lgx.rate.card.line.lgx_price_for(qty)` / `.lgx_amount_for(qty)` · jenjang + tagihan minimum
`lgx.rate.card.action_new_version()` · versi baru; versi lama TETAP hidup
`lgx.quote.action_load_rates()` / `.action_create_job()` · pengisian dan konversi
`lgx.contract.lgx_find_active(partner, on_date)`

## Integration Points

`lgx.job.quote_id` dan `.contract_id` dideklarasikan DI SINI, bukan di `custom_lgx_job`, supaya job tetap bisa berdiri tanpa lapisan komersial.

## Gotchas

**`any_partner=True` wajib untuk sisi BELI.** Saat penawaran disusun, carrier yang akan dipakai belum tentu sudah dipilih. Tanpa flag ini, pencarian tarif beli hanya menerima tarif umum, setiap kontrak carrier yang benar-benar dimiliki perusahaan tidak akan pernah terpakai, harga beli jatuh ke nol, margin tampak 100%, dan penawaran itu dikirim.

**`line_ids` dan `surcharge_ids` diberi `copy=True` secara eksplisit.** One2many di Odoo TIDAK ikut tersalin secara default, dan versi baru rate card tanpa baris tarif adalah record yang tidak bisa diaktifkan sama sekali.

**Konversi membuat DUA baris charge per baris penawaran.** Hanya membuat baris pendapatan menghasilkan job yang labanya tampak 100% sampai tagihan vendor datang berminggu-minggu kemudian.

**Vendor pada baris biaya diambil dari `partner_id` rate card beli.** Tanpa itu baris biaya lahir tanpa pihak dan job menolak dikonfirmasi — dan penolakan itu benar: akrual yang tidak bisa ditagih ke siapa pun memang tidak boleh terbentuk.
