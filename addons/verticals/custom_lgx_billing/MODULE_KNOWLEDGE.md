# LGX — Penagihan, Akrual, dan Provisi (`custom_lgx_billing`)

> Versi 19.0.1.0.0 · lisensi LGPL-3 · `capability_tags`: logistics, billing, accrual, provision, disbursement, indonesia
> Depends: custom_lgx_job, account

## Purpose

Job menjadi faktur pelanggan dan tagihan vendor; talangan lewat akun kliring di neraca; estimasi membentuk akrual; penutupan finansial lewat provisi.

## Business Flow

Tiga hal yang rusak sekaligus tanpa peta akun yang eksplisit: margin per job,
dasar pemotongan PPh 23, dan laporan laba rugi. Modul ini adalah peta akun itu.

**Talangan mengalir lewat neraca, bukan lewat laba rugi.** Bea masuk, THC dan
retribusi yang ditalangi lalu ditagihkan kembali apa adanya bukan pendapatan dan
bukan beban. Pada job impor, talangan rutin berkali lipat nilai jasanya — kalau
keduanya dilewatkan akun laba rugi, pendapatan dan HPP sama-sama menggelembung
dan ``margin_pct`` menjadi angka yang tidak berarti.

    Membayar bea masuk atas nama klien  Dr Kliring talangan  Cr Kas/Bank
    Menagihkan kembali ke klien          Dr Piutang usaha     Cr Kliring talangan
    Dampak ke laba rugi                  NOL

**Akrual dibalik oleh tagihannya, bukan oleh pembalikan otomatis awal periode.**
Pembalikan otomatis akan membuat biaya menghilang selama beberapa minggu sampai
tagihan vendor datang — persis masalah yang akrual ini ada untuk menutupinya.

**Provisi, bukan penghapusan.** Saat job ditutup secara finansial, sisa estimasi
dipindahkan dari akun akrual ke akun provisi job tertutup dengan umur tercatat.
Tagihan yang datang kemudian membebani provisi, bukan membuka kembali laba rugi
periode yang sudah dilaporkan.

## Key Models

`res.company` · peta akun logistik (kliring talangan, akrual, provisi, varians, jurnal)
`account.move` / `account.move.line` · jejak dua arah ke job dan baris charge
`lgx.job.charge` · diperluas dengan `accrual_line_id`, `provision_line_id`, `variance_line_id`
`lgx.job.invoice.wizard` · pemilihan baris untuk faktur bertahap

## Public Methods

`res.company.lgx_setup_default_accounts()` · penyiapan peta akun, IDEMPOTEN; dipakai tenant baru, tombol pengaturan, dan setUpClass tes
`res.company.lgx_check_accounts()` · gagal lebih awal dan menyebut apa yang kurang
`lgx.job.action_post_accrual()` · Dr beban/kliring, Cr akrual; idempoten
`lgx.job._lgx_post_variance(move)` · dipanggil dari `account.move._post`
`lgx.job.lgx_create_customer_invoice(charges)` / `.lgx_create_vendor_bills()`
`lgx.job.action_close_with_provision()` · Dr akrual, Cr provisi
`lgx.job.charge.action_release_provision()` · butuh grup manajer keuangan

## Integration Points

Dipanggil `custom_lgx_wms_billing` (charge dari proses penagihan gudang) dan `custom_lgx_customs` (pungutan impor sebagai talangan). `custom_lgx_tax_id` membaca `nature` baris charge untuk menyusun dasar PPh 23.

## Gotchas

**`_lgx_sync_charges` HANYA berlaku untuk faktur.** Entri akrual, varians dan provisi juga membawa `lgx_job_id` dan `lgx_charge_id`. Tanpa penyaringan `move_type`, memposting akrual akan menandai barisnya "aktual sudah diketahui" dan seluruh mekanisme estimasi-versus-aktual runtuh pada langkah pertamanya. Ini bug yang pernah terjadi dan ditangkap tes.

**Akrual dibalik oleh TAGIHANNYA, bukan oleh pembalikan otomatis awal periode.** Pembalikan otomatis membuat biaya menghilang selama beberapa minggu sampai tagihan datang.

**Baris tagihan vendor memakai tiga akun berbeda menurut keadaan** (`_lgx_bill_account`): provisi bila job sudah ditutup finansial, akrual bila sudah diakrualkan, akun beban langsung bila belum pernah diakrualkan. Tagihan yang datang setelah penutupan HARUS membebani provisi, bukan membuka kembali laba rugi periode yang sudah dilaporkan.

**Akun kliring talangan harus NOL saat job `closed`.** Saldo yang tersisa berarti ada talangan yang tidak pernah ditagihkan — kas yang hilang diam-diam, dan itu laporan tersendiri.
