# LGX — Penagihan Gudang 3PL (`custom_lgx_wms_billing`)

> Versi 19.0.1.0.0 · lisensi LGPL-3 · `capability_tags`: logistics, wms, storage-billing, occupancy, 3pl
> Depends: custom_lgx_wms, custom_lgx_billing

## Purpose

Potret okupansi harian yang idempoten, tarif penyimpanan dan handling berjenjang, serta proses penagihan periodik yang dapat dipratinjau dan dibatalkan.

## Business Flow

**Penyimpanan ditagih atas RUANG DIKALI WAKTU, bukan atas transaksi.** Untuk
menagih "pallet-hari", sistem harus tahu berapa pallet milik siapa yang ada di
gudang PADA SETIAP HARI — bukan hanya saldo akhir bulan. Itulah sebabnya ada
potret harian, dan itulah model paling sensitif terhadap volume di seluruh
sistem.

**Keputusan yang diambil di depan, bukan ditambal belakangan:**

* **Granularitas per PRODUK**, bukan per pallet. Per produk jauh lebih ringan,
  dan ``pallet_count`` tetap dihitung dari faktor konversi sehingga tarif per
  pallet tetap bisa ditagihkan. Kalau sebuah kontrak benar-benar menuntut
  identitas pallet, itu perubahan yang dianggarkan, bukan asumsi diam-diam.
* **Idempoten per (tanggal, klien, produk, lokasi, lot).** Menjalankan ulang
  cron untuk tanggal yang sama memperbarui baris, tidak menggandakannya —
  ditegakkan unique constraint di Postgres, bukan hanya oleh kehati-hatian cron.
* **Indeks pada (date, client_id)** sejak awal. Perkiraan volume:
  SKU aktif × lokasi terisi × 365 baris per tahun; untuk gudang 5.000 SKU itu
  jutaan baris.
* **Retensi 13 bulan** detail harian, lalu diringkas bulanan.

**Proses penagihan dapat dipratinjau sebelum diposting dan dibatalkan selama
belum difakturkan**, dan hasilnya dapat ditelusuri kembali ke potret harian yang
menjadi dasarnya. Tagihan gudang yang tidak dapat ditelusuri ke okupansi adalah
tagihan yang diperdebatkan setiap bulan.

## Key Models

`lgx.wms.occupancy.snapshot` · potret okupansi harian — model paling sensitif volume
`lgx.wms.storage.rule` / `.tier` · tarif penyimpanan berjenjang
`lgx.wms.handling.rule` · tarif handling
`lgx.wms.billing.run` / `.line` · proses penagihan periodik

## Public Methods

`lgx.wms.occupancy.snapshot._cron_take_snapshot(for_date)` · idempoten
`lgx.wms.occupancy.snapshot._cron_prune_snapshots()` · retensi 13 bulan
`lgx.wms.client._lgx_pallet_equivalent(product, quantity)`
`lgx.wms.storage.rule.lgx_rate_for(volume)` · jenjang
`lgx.wms.billing.run.action_compute/post_to_job/cancel`

## Integration Points

Menghasilkan `lgx.job.charge` pada job gudang klien, lalu diteruskan ke faktur lewat `custom_lgx_billing`. `billing_run_id` pada potret adalah jejak yang membuat tagihan dapat ditelusuri kembali ke okupansinya.

## Gotchas

**Idempotensi ditegakkan POSTGRES, bukan kehati-hatian cron.** Unique constraint pada (date, client, product, location, lot). Cron dijalankan ulang manual saat ada yang salah, dan itulah saat baris ganda lahir — lalu tagihan bulan itu dua kali lipat.

**Indeks (date, client_id) ada sejak baris pertama.** Perkiraan volume: SKU aktif × lokasi terisi × 365 per tahun. Menambah indeks setelah tabel berisi jutaan baris adalah operasi yang mengunci tabel.

**Granularitas PER PRODUK, bukan per pallet** (keputusan 4 di Fase 0). `pallet_count` dihitung dari faktor konversi sehingga tarif per pallet tetap bisa ditagihkan. Kontrak yang benar-benar menuntut identitas pallet adalah perubahan yang dianggarkan, bukan asumsi diam-diam.

**Masa bebas diterapkan saat PENAGIHAN, bukan saat memotret.** Potret merekam apa yang ada; penagihan memutuskan apa yang ditagihkan. Dengan begitu perubahan masa bebas di kontrak dapat diterapkan surut tanpa memotret ulang.

**Masa bebas dihitung dari potret PALING AWAL kombinasi produk+lot**, bukan dari awal periode. Kalau tidak, barang yang menginap berbulan-bulan akan mendapat masa bebas baru setiap bulan.

**Tagihan minimum muncul sebagai SELISIHNYA**, bukan sebagai pengganti. Menampilkannya sebagai pengganti menyembunyikan berapa sebenarnya okupansi klien — dan itu angka yang dibawa ke negosiasi perpanjangan kontrak.
