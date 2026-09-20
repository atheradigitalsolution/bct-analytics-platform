# LGX — Integrasi NLE / INSW (`custom_lgx_nle`)

> Versi 19.0.1.0.0 · lisensi LGPL-3 · `capability_tags`: logistics, nle, insw, do-online, integration, indonesia
> Depends: custom_lgx_ff, queue_job

## Purpose

DO Online, SP2, dan penarikan status dokumen serta kontainer dari Customs API, seluruhnya lewat antrian dengan jejak pesan.

## Business Flow

**Customs API adalah nilai tambah yang paling sering terlewat.** DO Online dan
SP2 menghemat pengetikan, tetapi yang benar-benar mengubah pekerjaan harian
adalah penarikan status: rekonsiliasi otomatis status dokumen pabean dan posisi
kontainer, tanpa staf operasi membuka portal berkali-kali sehari lalu menyalin
angkanya dengan tangan.

Status yang ditarik menjadi `lgx.milestone` dengan `source = 'nle'`. Sumbernya
disimpan justru karena penting: saat pelanggan menanyakan kenapa ETA berubah,
"siapa yang bilang" adalah setengah dari jawabannya.

**Job yang sudah `closed` tidak ikut ditarik.** Menarik status dokumen pada job
yang bukunya sudah tutup hanya menghasilkan perubahan yang tidak boleh lagi
memengaruhi apa pun — dan cron yang menyentuh periode tertutup adalah cron yang
suatu saat mengubah angka yang sudah dilaporkan.

⚠ `id_platform` dan API key produksi diperoleh lewat REGISTRASI ke NLE. Itu
pekerjaan administratif klien, bukan pekerjaan kode, dan masuk daftar prasyarat
proyek. Sampai itu terbit, modul ini bekerja penuh terhadap `lgx-mock`.

## Key Models

`lgx.nle.client` · AbstractModel; satu-satunya tempat `requests` dipanggil
`lgx.shipment` · diperluas dengan DO Online, SP2, dan rekonsiliasi status
`lgx.integration.message` · diperluas dengan `nle_shipment_id`
`res.company` · base URL, API key, dan `id_platform`

## Public Methods

`lgx.nle.client._call(company, method, path, payload, params, message)`
`lgx.shipment.action_request_do_online()` / `._job_request_do_online(message_id)`
`lgx.shipment.action_request_sp2()` / `._job_request_sp2(message_id)`
`lgx.shipment._do_payload()` · dipisah supaya dapat diuji tanpa jaringan
`lgx.shipment._apply_nle_status(body)` · idempoten
`lgx.shipment._cron_pull_nle_status()`

## Integration Points

Menulis `lgx.milestone` dengan `source = 'nle'`, dan mengisi `lgx.container.gate_out_date` yang menjadi dasar perhitungan detensi di `custom_lgx_ff`.

## Gotchas

**NLE menjawab HTTP 200 dengan `status: "Failed"` untuk penolakan ATURAN BISNIS.** Bentuk permintaannya benar; isinya yang ditolak. Klien yang hanya memeriksa kode HTTP mencatat kegagalan ini sebagai sukses — dan DO yang tidak pernah terbit akan tampak terbit, sampai ada yang menanyakan kenapa kontainer tidak bisa diambil. `_call` karena itu memeriksa `status` di badan, bukan hanya kode HTTP.

**`id_platform` diperoleh lewat REGISTRASI, dan request tanpa itu ditolak dengan pesan yang tidak menyebutkan penyebabnya.** Karena itu penolakannya dilakukan di sisi kita, di mana penyebabnya masih dapat dikatakan.

**Status kontainer mengisi tanggal gerbang, tetapi TIDAK PERNAH menimpa yang sudah diketik.** Angka yang sudah diisi orang tidak boleh ditimpa tebakan dari luar — dan tanggal gerbang adalah dasar perhitungan detensi.

**Pemetaan status dokumen ke milestone adalah DATA (`NLE_DOCUMENT_MILESTONES`), bukan rangkaian if.** Istilah di sisi mereka berubah lebih sering daripada alur kita, dan perubahan istilah tidak boleh menjadi perubahan logika.

**Penarikan berulang tidak menggandakan milestone** — `lgx_log_milestone` memperbarui baris yang ada. Cron dua-jam-sekali kalau tidak akan menghasilkan dua puluh milestone yang sama dalam sehari.

**Job yang sudah `closed` tidak ikut ditarik.** Cron yang menyentuh periode tertutup adalah cron yang suatu saat mengubah angka yang sudah dilaporkan.

⚠ Endpoint dan skema adalah perkiraan terbaik dari dokumentasi publik (butir A21).
