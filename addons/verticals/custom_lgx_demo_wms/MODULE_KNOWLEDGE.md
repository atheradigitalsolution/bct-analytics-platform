# LGX — Data Demo Gudang 3PL (`custom_lgx_demo_wms`)

> Versi 19.0.1.0.0 · lisensi LGPL-3 · `capability_tags`: logistics, demo-data, wms, 3pl
> Depends: custom_lgx_wms_billing

## Purpose

Dua pemilik barang di satu gudang, stok yang tidak masuk neraca, potret okupansi 30 hari, dan satu proses penagihan penyimpanan.

## Business Flow

Data demo: dua pemilik barang di satu gudang, stok yang tidak masuk neraca, potret okupansi 30 hari, dan satu proses penagihan penyimpanan.

## Key Models

Tidak mendefinisikan model. Seluruh isinya dibangkitkan `post_init_hook` di `hooks.py`.

## Public Methods

`post_init_hook(env)` · idempoten; keluar lebih awal bila datanya sudah ada.

## Integration Points

Dipasang TERPISAH dari modul segmen supaya mendemokan satu segmen tidak menarik seluruh pohon modul, dan supaya data demo tidak pernah ikut terpasang di database klien hanya karena modul operasinya dipasang.

## Gotchas

**Dua pemilik barang, bukan satu.** Segregasi stok tidak dapat didemokan dengan satu klien: yang harus terlihat adalah stok klien A tidak muncul di laporan klien B, dan itu butuh B yang benar-benar ada.

Potret dibangkitkan MUNDUR 30 hari lewat `_cron_take_snapshot(for_date=...)`, karena cron harian hanya memotret hari ini. Tanpa itu tagihan pallet-hari bernilai nol.
