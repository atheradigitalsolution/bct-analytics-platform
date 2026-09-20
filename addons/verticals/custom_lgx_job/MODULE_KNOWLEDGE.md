# LGX — Job (Tulang Punggung Komersial) (`custom_lgx_job`)

> Versi 19.0.1.0.0 · lisensi LGPL-3 · `capability_tags`: logistics, job-costing, profitability, accrual, indonesia
> Depends: custom_lgx_base, account

## Purpose

lgx.job, lgx.job.charge dengan nilai estimasi dan aktual berdampingan, milestone, dan laba per job yang memisahkan talangan dari jasa.

## Business Flow

Satu objek komersial dan keuangan untuk KETIGA segmen logistik. Operasi per
segmen — shipment, trip, picking — menggantung di bawahnya, tidak
menggantikannya.

**Setiap baris biaya punya nilai estimasi DAN nilai aktual.** Ini fitur inti,
bukan tambahan. Di forwarding, pendapatan diketahui saat job berjalan tetapi
tagihan vendor baru datang dua sampai enam minggu kemudian. Sistem yang hanya
mencatat biaya saat faktur vendor masuk akan selalu melaporkan laba bulan
berjalan yang terlalu optimistis, lalu mengoreksinya turun belakangan.

**Talangan tidak masuk margin.** ``nature = disbursement`` adalah biaya pihak
ketiga yang ditalangi dan ditagihkan kembali apa adanya — bukan pendapatan dan
bukan beban. Pada job impor, talangan rutin berkali lipat nilai jasanya; kalau
ikut dihitung, ``margin_pct`` menjadi angka yang tidak berarti dan dasar
pemotongan PPh 23 ikut salah.

**Penutupan operasional dan penutupan finansial adalah dua hal berbeda.**
``completed`` berarti pekerjaan fisik selesai; ``closed_provisioned`` berarti
sisa estimasi sudah dibukukan sebagai provisi yang nyata; ``closed`` berarti
seluruh provisi sudah terpakai atau dilepas. Menyatukan ketiganya menghasilkan
aturan yang di lapangan diakali dengan menolkan estimasi — persis kebocoran yang
aturan itu ingin cegah.

## Key Models

`lgx.job` · tulang punggung komersial dan keuangan untuk KETIGA segmen
`lgx.job.charge` · baris pendapatan/biaya dengan nilai estimasi DAN aktual berdampingan
`lgx.milestone` · milestone per job (modul segmen menambah tautan shipment dan trip)

## Public Methods

`lgx.job.action_confirm/start/complete/close/cancel/draft` · alur status
`lgx.job._lgx_completion_blockers()` · **titik perluasan**: modul segmen MENAMBAH ke hasil `super()`, tidak menggantinya
`lgx.job._lgx_close_blockers()` · penghalang finansial, terpisah dari penghalang operasional
`lgx.job.lgx_log_milestone(code, ...)` · catat milestone berdasarkan KODE, bukan id
`lgx.job.lgx_is_jpt()` · True bila job tergolong jasa pengurusan transportasi
`lgx.job._generate_milestones()` · idempoten; mengkonfirmasi ulang tidak menggandakan
`lgx.job.charge.action_record_actual(amount)` · tandai nilai aktual sudah diketahui

## Integration Points

`custom_lgx_ff` menambah `shipment_ids` dan penghalang kontainer belum kembali; `custom_lgx_tms` menambah `trip_ids`, POD yang hilang, dan uang jalan terbuka; `custom_lgx_billing` menambah akrual, faktur dan provisi; `custom_lgx_doc` menambah checklist yang menahan milestone.

## Gotchas

**`is_actual_known` adalah flag eksplisit, bukan `amount_actual != 0`.** Tagihan vendor yang ternyata nol adalah fakta yang berbeda dari tagihan yang belum datang, dan keduanya harus bisa dibedakan — kalau tidak, biaya yang benar-benar nol akan selamanya dihitung sebagai akrual terbuka.

**Talangan TIDAK masuk margin.** `revenue_total` dan `cost_total` hanya menjumlah baris `nature = service`. Pada job impor, talangan rutin berkali lipat nilai jasanya; menggabungkannya membuat `margin_pct` tidak berarti dan dasar PPh 23 ikut salah.

**Bukti pihak ketiga hanya dituntut pada sisi PENDAPATAN.** Pada sisi biaya, tagihan vendor itu sendiri adalah dokumen pihak ketiganya; menuntut lampiran tambahan di sana adalah aturan yang dicarikan jalan memutar.

**Tiga status penutupan, bukan satu.** `completed` operasional, `closed_provisioned` finansial dengan provisi, `closed` penuh. Menyatukannya menghasilkan aturan yang di lapangan diakali dengan menolkan estimasi.
