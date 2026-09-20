# LGX — Integrasi CEISA 4.0 (`custom_lgx_ceisa`)

> Versi 19.0.1.0.0 · lisensi LGPL-3 · `capability_tags`: logistics, customs, ceisa, integration, indonesia, queue-job
> Depends: custom_lgx_customs, queue_job

## Purpose

Pengiriman deklarasi pabean host-to-host ke CEISA 4.0 lewat antrian, dengan OAuth2 client credentials, token yang diperiksa saat dijalankan, dan mode manual untuk kantor pabean yang belum wajib.

## Business Flow

**Tidak ada panggilan HTTP sinkron dari dalam transaksi ORM.** Tombol "Kirim ke
CEISA" hanya membuat satu baris `lgx.integration.message` dan mengantrikan job;
HTTP-nya terjadi di runner `queue_job`. Memanggil Bea Cukai dari dalam transaksi
pengguna berarti kursor database ditahan selama jaringan lambat, dan satu
gangguan di sisi mereka menjadi tabel terkunci di sisi kita.

**Token diperiksa saat job DIJALANKAN, bukan saat dijadwalkan.** Masa berlaku
access token sangat pendek. Job yang mengambil token saat dijadwalkan lalu
berjalan lima menit kemudian akan mengirim dengan token yang sudah mati — dan
gagalnya terlihat sebagai 401 yang membingungkan, bukan sebagai token basi.
Karena itu `_lgx_ceisa_token()` dipanggil tepat sebelum request, selalu.

**Kantor pabean yang belum wajib CEISA 4.0 tidak dikirimi apa pun.** Penetapan
mandatory berjalan bertahap per kantor dan per layanan. Mencoba mengirim ke
kantor yang belum wajib menghasilkan penolakan yang tidak ada artinya, dan
antrian yang penuh galat permanen adalah antrian yang berhenti dibaca orang.

⚠ Endpoint, alur OAuth, dan masa berlaku token adalah PERKIRAAN TERBAIK dari
dokumentasi publik dan belum diverifikasi ke lingkungan development sungguhan
(butir A20 di Lampiran A). Semuanya konfigurasi, bukan konstanta — mengganti
base URL dan nama field tidak menuntut menyentuh kode.

## Key Models

`lgx.ceisa.client` · AbstractModel; satu-satunya tempat `requests` dipanggil
`lgx.customs.declaration` · diperluas dengan pengiriman, penarikan status, dan log pesan
`lgx.integration.message` · diperluas dengan `ceisa_declaration_id`
`res.company` · konfigurasi dan CACHE TOKEN

## Public Methods

`lgx.ceisa.client._lgx_ceisa_token(company, force_refresh)` · token yang DIJAMIN segar
`lgx.ceisa.client._call(company, method, path, payload, message)` · request berjejak
`lgx.ceisa.client.action_test_connection(company)` · uji kredensial tanpa mengirim dokumen
`lgx.customs.declaration.action_send_ceisa()` · mengantrikan, TIDAK memanggil HTTP
`lgx.customs.declaration._ceisa_payload()` · dipisah supaya dapat diuji tanpa jaringan
`lgx.customs.declaration._job_submit_to_ceisa(message_id)` · dijalankan runner
`lgx.customs.declaration._apply_ceisa_status(body)` · idempoten, tidak pernah mundur
`lgx.customs.declaration._cron_pull_ceisa_status()`

## Integration Points

Berbicara dengan `lgx-mock` (`/opt/lgx/mock`) selama pengembangan. Menulis `lgx.milestone` dengan `source = 'ceisa'` lewat `lgx.job.lgx_log_milestone`.

## Gotchas

**401 di endpoint TOKEN adalah galat PERMANEN; 401 di endpoint sumber daya adalah token basi.** Keduanya sempat saya samakan, dan tes terhadap mock menangkapnya: `client_secret` yang salah dicoba ulang delapan kali dengan backoff sampai dua jam, lalu berakhir sebagai job gagal yang penyebabnya terkubur di percobaan pertama. Sekarang yang pertama `UserError`, yang kedua memicu satu kali refresh lalu satu kali ulang.

**Token diperiksa saat job DIJALANKAN, bukan saat dijadwalkan.** Masa berlaku access token sangat pendek; job yang mengambil token saat dijadwalkan lalu berjalan lima menit kemudian mengirim dengan token mati.

**Token di-cache di DATABASE, bukan di memori proses.** Odoo multi-worker: cache memori berarti tiap worker meminta tokennya sendiri, dan dengan TTL sependek itu menjadi badai permintaan token lalu pembatasan laju di sisi mereka.

**`capacity` BUKAN field pada `queue.job.channel`** di versi queue_job ini — kapasitas diatur di runner lewat `ODOO_QUEUE_JOB_CHANNELS`. Mencantumkannya sebagai data membuat modul gagal dipasang. `retry_pattern` juga ditulis lewat `edit_retry_pattern` (Text).

**Kanal antrian terpisah (`root.lgx_ceisa`).** CEISA lambat dan kadang mati; job yang menunggu socket menahan slot runner. Tanpa kanal sendiri, satu gangguan di Bea Cukai menghentikan seluruh antrian — termasuk potret okupansi gudang yang tidak ada hubungannya.

**`identity_key` pada job pengiriman.** Dua penekanan tombol menghasilkan SATU job; tanpa itu, staf yang menekan dua kali karena layar terasa lambat mengirim dokumen yang sama dua kali ke Bea Cukai.

**Cron penarik status MATI secara default.** Cron yang menarik ke endpoint yang belum dikonfigurasi hanya mengisi antrian dengan galat pada database yang belum memakai CEISA sama sekali.

⚠ Endpoint, alur OAuth dan masa berlaku token adalah perkiraan terbaik dari dokumentasi publik, belum diverifikasi ke lingkungan development sungguhan (butir A20).
