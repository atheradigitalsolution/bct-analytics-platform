# LGX — Data Demo Trucking (`custom_lgx_demo_tms`)

> Versi 19.0.1.0.0 · lisensi LGPL-3 · `capability_tags`: logistics, demo-data, trucking
> Depends: custom_lgx_tms, custom_lgx_driver, custom_lgx_pricing

## Purpose

Armada dengan JBI dan dokumen, pengemudi ber-SIM, rute bertarif, dan trip lengkap dengan POD serta uang jalan yang dipertanggungjawabkan.

## Business Flow

Data demo: dua kendaraan dengan JBI dan dokumen, dua pengemudi, rute bertarif, satu trip selesai penuh dengan POD dan uang jalan yang dipertanggungjawabkan.

## Key Models

Tidak mendefinisikan model. Seluruh isinya dibangkitkan `post_init_hook` di `hooks.py`.

## Public Methods

`post_init_hook(env)` · idempoten; keluar lebih awal bila datanya sudah ada.

## Integration Points

Dipasang TERPISAH dari modul segmen supaya mendemokan satu segmen tidak menarik seluruh pohon modul, dan supaya data demo tidak pernah ikut terpasang di database klien hanya karena modul operasinya dipasang.

## Gotchas

Satu trip sengaja dibiarkan MELEBIHI JBI dan berstatus draf, supaya validasi ODOL terlihat bekerja di layar. Demo yang semuanya mulus tidak menunjukkan apa pun tentang kontrol yang justru menjadi alasan sistem ini dibeli.

Satu kendaraan sengaja ber-KIR mati, supaya peringatan dokumen punya sesuatu untuk ditampilkan.
