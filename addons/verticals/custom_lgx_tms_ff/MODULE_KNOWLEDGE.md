# LGX — Jembatan Trucking ⇄ Forwarding (`custom_lgx_tms_ff`)

> Versi 19.0.1.0.0 · lisensi LGPL-3 · `capability_tags`: logistics, trucking, forwarding, container-haulage, bridge
> Depends: custom_lgx_tms, custom_lgx_ff

## Purpose

Menautkan trip haulage ke kontainer forwarding, dan memutakhirkan tanggal gerbang kontainer dari pergerakan trip.

## Business Flow

Modul kecil dengan satu alasan keberadaan: ``custom_lgx_tms`` sengaja TIDAK
bergantung pada ``custom_lgx_ff``. Klien trucking murni tidak boleh dipaksa
memasang seluruh lapisan forwarding hanya untuk mengelola trip.

Tetapi ketika keduanya memang dipasang, trip haulage jelas mengangkut kontainer
yang sama yang dilacak forwarding — dan tanggal keluar/masuk gerbang yang
menentukan detensi justru diketahui oleh trip, bukan oleh staf forwarding.
Membiarkan keduanya terpisah berarti tanggal gerbang diketik dua kali, lalu
berbeda, lalu perhitungan detensi salah.

Jembatan ini yang menyambungkannya — dan ia adalah dependency yang jujur:
ia bergantung pada keduanya, sementara keduanya tidak bergantung satu sama lain.

## Key Models

`lgx.trip` · diperluas dengan `container_id` (Many2one ke `lgx.container`)

## Public Methods

`lgx.trip.action_dispatch()` · mengisi `gate_out_date` kontainer
`lgx.trip.action_settle()` · mengisi `gate_in_date` kontainer

## Integration Points

Menyambungkan `lgx.trip` ke `lgx.container`; tidak menambah tabel baru.

## Gotchas

**Modul ini ada supaya `custom_lgx_tms` TIDAK perlu bergantung pada `custom_lgx_ff`.** Klien trucking murni tidak boleh dipaksa memasang seluruh lapisan forwarding hanya untuk mengelola trip. Jembatan ini adalah dependency yang jujur: ia bergantung pada keduanya, sementara keduanya tidak bergantung satu sama lain.

**Tanggal gerbang yang diketik dua kali adalah tanggal yang suatu saat berbeda**, dan perhitungan detensi ikut salah. Yang benar-benar mengetahuinya adalah trip — pengemudilah yang keluar terminal dan mengembalikan kontainer.

`auto_install = True`: terpasang sendiri begitu kedua modul induknya ada.
