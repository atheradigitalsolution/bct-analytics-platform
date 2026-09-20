# LGX — Data Demo Forwarding (`custom_lgx_demo_ff`)

> Versi 19.0.1.0.0 · lisensi LGPL-3 · `capability_tags`: logistics, demo-data, freight-forwarding
> Depends: custom_lgx_ff, custom_lgx_customs, custom_lgx_pricing, custom_lgx_billing

## Purpose

Pelanggan, carrier, rate card, penawaran, job impor dan ekspor berikut shipment, kontainer bernomor sah ISO 6346, dan deklarasi pabean.

## Business Flow

Data demo: job impor Shanghai→Jakarta lengkap dengan konsolidasi, dua kontainer bernomor sah ISO 6346, deklarasi PIB jalur hijau, dan pungutan impor sebagai talangan.

## Key Models

Tidak mendefinisikan model. Seluruh isinya dibangkitkan `post_init_hook` di `hooks.py`.

## Public Methods

`post_init_hook(env)` · idempoten; keluar lebih awal bila datanya sudah ada.

## Integration Points

Dipasang TERPISAH dari modul segmen supaya mendemokan satu segmen tidak menarik seluruh pohon modul, dan supaya data demo tidak pernah ikut terpasang di database klien hanya karena modul operasinya dipasang.

## Gotchas

Nomor kontainer DIHITUNG digit periksanya, bukan dikarang: nomor demo yang ditolak validasi sendiri adalah demo yang berhenti di menit kedua.

Tanggal relatif terhadap hari pemasangan — data demo bertanggal mati akan tampak sudah lewat berminggu-minggu saat benar-benar didemokan.
