# LGX — Trucking & Dispatch (`custom_lgx_tms`)

> Versi 19.0.1.0.0 · lisensi LGPL-3 · `capability_tags`: logistics, trucking, dispatch, pod, odol, driver-advance
> Depends: custom_lgx_job, custom_lgx_fleet

## Purpose

Trip multi-stop, dispatch dengan deteksi bentrok, validasi ODOL, POD digital, uang jalan dengan batas dari master rute, dan pertanggungjawaban berbukti.

## Business Flow

**`lgx.trip` adalah model sendiri dan TIDAK bergantung pada `stock_fleet`.**
`stock_fleet` mengaitkan dispatch ke `stock.picking.batch`, yang mengandaikan ada
pergerakan stok di pembukuan sendiri. Untuk perusahaan trucking murni yang
mengangkut barang milik orang lain, tidak ada stok yang bergerak — memaksakan
`stock.picking` akan menciptakan pergerakan stok palsu, dan memaksa klien
trucking memasang seluruh modul Inventory hanya untuk mengelola trip.

**POD adalah pemicu tagihan, jadi ia menahan status.** Di trucking, bukti terima
bertanda tangan adalah satu-satunya dasar penagihan; POD hilang berarti
pendapatan hilang. Trip karena itu tidak dapat masuk `delivered` selama ada stop
`dropoff` tanpa POD.

**Uang jalan adalah titik kebocoran terbesar, dan tiga kontrolnya struktural:**
batasnya dihitung dari master rute dan bukan diketik bebas; satu pengemudi tidak
boleh punya lebih dari satu uang jalan terbuka; trip tidak dapat ditutup sebelum
pertanggungjawaban selesai. Selisihnya otomatis menjadi piutang atau utang
pengemudi — bukan dibulatkan hilang.

**`lgx.driver` hidup di modul ini, bukan di `custom_lgx_driver`.** Penyimpangan
sadar dari spesifikasi: dispatch harus dapat menolak pengemudi ber-SIM mati pada
saat penugasan, dan itu berarti master pengemudi harus ada sebelum modul
pengemudi dipasang. `custom_lgx_driver` memperluasnya dengan hr.employee, log jam
kerja, dan backend aplikasi lapangan.

## Key Models

`lgx.trip` / `lgx.trip.stop` / `lgx.trip.expense` · trip multi-stop dan biayanya
`lgx.trip.advance` · uang jalan dengan batas dari master rute
`lgx.driver` · master pengemudi dan masa berlaku SIM
`lgx.route` / `lgx.route.tariff` · rute dan tarifnya

## Public Methods

`lgx.trip.action_assign/dispatch/in_transit/deliver/settle/close/cancel`
`lgx.trip._check_vehicle_conflict()` / `._check_driver_eligible()` / `._check_odol()`
`lgx.trip.action_create_advance()` · nilai disarankan dari `lgx.route.tariff.standard_advance`
`lgx.trip.advance.action_approve/pay/settle`
`lgx.route.tariff.lgx_find(route, category, partner, on_date)`

## Integration Points

Menambah penghalang `_lgx_completion_blockers` pada job: POD yang hilang dan uang jalan yang belum ditutup. `custom_lgx_driver` memperluas `lgx.driver` dengan hr.employee dan log jam kerja.

## Gotchas

**`lgx.driver` hidup di modul INI, bukan di `custom_lgx_driver`.** Penyimpangan sadar dari spesifikasi: dispatch harus dapat menolak pengemudi ber-SIM mati pada saat penugasan, dan itu berarti master pengemudi harus ada sebelum modul pengemudi dipasang.

**`container_no` adalah Char, BUKAN Many2one ke `lgx.container`.** `custom_lgx_tms` sengaja tidak bergantung pada `custom_lgx_ff`. Many2one ke model milik modul yang bukan dependency kebetulan bekerja selama keduanya terpasang, lalu gagal saat salah satunya di-upgrade sendirian — dan itu ketahuan pertama kali di produksi. Tautan sesungguhnya ada di jembatan `custom_lgx_tms_ff`.

**POD butuh BUKTI DAN NAMA PENERIMA.** Tanda tangan tanpa nama penerima adalah coretan; nama tanpa bukti adalah pernyataan. Yang menagih adalah keduanya sekaligus.

**Tiga kontrol uang jalan bersifat struktural**, bukan prosedural: batas dari master rute, satu uang jalan terbuka per pengemudi, dan trip tidak dapat ditutup sebelum pertanggungjawaban selesai.

**`lgx.trip` TIDAK bergantung pada `stock_fleet`.** Untuk trucking murni yang mengangkut barang milik orang lain, memaksakan `stock.picking` akan menciptakan pergerakan stok palsu dan memaksa klien memasang seluruh modul Inventory.
