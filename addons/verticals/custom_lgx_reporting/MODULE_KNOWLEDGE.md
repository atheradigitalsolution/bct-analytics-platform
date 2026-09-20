# LGX — Laporan & Analitik (`custom_lgx_reporting`)

> Versi 19.0.1.0.0 · lisensi LGPL-3 · `capability_tags`: logistics, reporting, profitability, cycle-time, analytics
> Depends: custom_lgx_billing, custom_lgx_ff, custom_lgx_tms

## Purpose

Laba per segmen, waktu siklus per tahap, akurasi provisi, dan utilisasi armada — dari view SQL, bukan dari hitungan ulang di spreadsheet.

## Business Flow

**Angka yang dibawa ke rapat harus datang dari satu tempat.** Laporan di sini
adalah view SQL di atas data transaksi, bukan model yang diisi proses terpisah:
laporan yang punya salinan datanya sendiri adalah laporan yang suatu saat
berbeda dari sumbernya, dan pada saat itu tidak ada cara memutuskan mana yang
benar.

**Porsi biaya estimasi yang belum menjadi aktual ditampilkan berdampingan dengan
margin.** Itu ukuran seberapa dipercaya angka margin bulan berjalan, dan
menampilkan margin tanpa angka itu adalah menampilkan setengah kalimat.

**Waktu siklus disajikan sebagai median dan persentil 90, bukan rata-rata.**
Rata-rata waktu bongkar pelabuhan tidak berarti apa-apa ketika distribusinya
berekor panjang — dan di pelabuhan ia selalu berekor panjang.

## Key Models

`lgx.report.job.profit` · view SQL laba per job dan segmen
`lgx.report.cycle.time` · view SQL waktu siklus antar milestone
`lgx.report.provision.accuracy` · view SQL akurasi provisi per kategori charge

## Public Methods

Tidak ada method publik; ketiganya `_auto = False` dengan `_table_query`.

## Integration Points

Membaca `lgx_job`, `lgx_milestone` dan `lgx_job_charge` langsung lewat SQL.

## Gotchas

**View SQL, bukan model terisi proses.** Laporan yang punya salinan datanya sendiri adalah laporan yang suatu saat berbeda dari sumbernya, dan pada saat itu tidak ada cara memutuskan mana yang benar tanpa menghitung ulang keduanya dengan tangan.

**`create="false"` BUKAN atribut yang sah pada `<pivot>` di Odoo 19** — hanya pada `<list>` dan `<form>`. Pelanggarannya muncul sebagai "Invalid view ... definition" tanpa menyebut atributnya.

**Waktu siklus dibaca sebagai median dan persentil, bukan rata-rata.** Distribusi waktu bongkar pelabuhan berekor panjang, dan rata-rata pada distribusi berekor panjang menyembunyikan justru kasus yang membuat pelanggan menelepon.

**`accrual_share_pct` ditampilkan berdampingan dengan margin.** Itu ukuran seberapa dipercaya angka margin bulan berjalan; margin tanpa angka itu adalah setengah kalimat.
