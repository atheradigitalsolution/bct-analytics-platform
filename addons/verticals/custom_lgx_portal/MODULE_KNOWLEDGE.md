# LGX — Portal Pelanggan (`custom_lgx_portal`)

> Versi 19.0.1.0.0 · lisensi LGPL-3 · `capability_tags`: logistics, portal, tracking, customer-self-service
> Depends: custom_lgx_job, custom_lgx_ff, custom_lgx_doc, portal

## Purpose

Pelacakan kiriman, unduh dokumen yang tercatat, dan pengajuan booking — dengan tautan pelacakan publik yang bertanda tangan dan kedaluwarsa.

## Business Flow

**Hanya milestone `is_customer_visible` yang tampil, dan itu ditegakkan di DUA
lapis.** Controller menyaringnya, dan record rule menyaringnya lagi. Bukan
karena paranoid: template QWeb adalah tempat orang menambahkan `t-foreach` baru
tanpa memikirkan siapa yang membacanya, dan satu baris ceroboh di sana akan
membocorkan milestone internal — "biaya vendor diterima", "kontainer kena
detensi" — ke layar pelanggan. Lapis kedua membuat kecerobohan itu tidak cukup.

**Setiap pengunduhan dokumen dicatat.** Bukan untuk mengawasi pelanggan,
melainkan karena pertanyaan "apakah mereka sudah menerima B/L-nya" muncul setiap
minggu di operasi, dan menjawabnya dengan tebakan adalah cara dokumen dikirim
ulang berkali-kali lewat surel.

**Tautan pelacakan publik bertanda tangan DAN kedaluwarsa.** Odoo menyediakan
`access_token` pada `portal.mixin`, tetapi token itu berlaku selamanya. Nomor
B/L beredar di rantai pasok — di surel, di grup pesan, di berkas Excel yang
diteruskan — dan tautan abadi yang ikut beredar bersamanya adalah pintu yang
tidak pernah tertutup. Karena itu modul ini memakai tokennya sendiri dengan masa
berlaku yang dapat dikonfigurasi.

**Booking dari portal membuat job `draft`, bukan job yang langsung berjalan.**
Pelanggan menerima nomor referensi seketika, staf operasi menerima aktivitas
terjadwal, dan tidak ada pekerjaan yang masuk antrian operasi tanpa seseorang
mengonfirmasinya.

## Key Models

`lgx.job` · mewarisi `portal.mixin`; menambah token pelacakan publik yang KEDALUWARSA
`lgx.document` · menambah riwayat unduh dan ringkasannya
`lgx.document.download.log` · satu baris per pengunduhan

## Public Methods

`lgx.job.lgx_issue_track_token(force)` · token baru atau token lama yang masih berlaku
`lgx.job.lgx_resolve_track_token(job_id, token)` · recordset kosong bila tidak sah
`lgx.job.action_share_tracking_link()` / `.action_revoke_track_token()`
`lgx.job.lgx_create_portal_booking(partner, values)` · job `draft` + aktivitas
`lgx.document.lgx_log_download(partner, source, remote_addr)`

## Integration Points

Route: `/my/logistik`, `/my/logistik/job/<id>`, `/my/logistik/dokumen/<id>`,
`/my/logistik/booking`, `/lgx/lacak`, `/lgx/lacak/<job_id>/<token>`.
Template memakai `portal.portal_layout` dan `portal.frontend_layout`.

## Gotchas

**`website=True` WAJIB pada setiap route yang merender template portal — meskipun modul `website` tidak terpasang.** Flag itu ditangani `http_routing`, bukan `website`: ia yang membuat `request.render()` memanggil `_prepare_frontend_environment`, yang mengisi `frontend_languages`. Tanpanya `portal.frontend_layout` meledak dengan `TypeError: object of type 'NoneType' has no len()` di `portal.language_selector` — pesan yang sama sekali tidak menunjuk ke flag yang hilang. Saya sempat menghapusnya dengan alasan "website tidak terpasang"; itu salah.

**Penyaringan berlapis DUA: controller DAN record rule.** Template QWeb adalah tempat orang menambahkan `t-foreach` baru tanpa memikirkan siapa yang membacanya. Lapis kedua membuat satu baris ceroboh di sana tidak cukup untuk membocorkan milestone internal ke layar pelanggan.

**Token pelacakan bukan `portal.mixin.access_token`.** Yang bawaan berlaku SELAMANYA. Nomor B/L beredar di rantai pasok — surel, grup pesan, Excel yang diteruskan — dan tautan abadi yang ikut beredar adalah pintu yang tidak pernah tertutup. Token modul ini memakai `secrets.token_urlsafe` (ketidakterdugaan kriptografis, bukan sekadar keunikan seperti uuid4), dibandingkan dengan `secrets.compare_digest`, dan mati menurut `lgx.track_link_ttl_hours` (default 72 jam).

**Pencarian publik menampilkan RINGKASAN saja, tanpa dokumen.** Nomor B/L terlalu mudah diperoleh untuk menjadi kunci ke dokumen. Dokumen hanya terbuka lewat tautan bertanda tangan atau portal yang sudah login.

**Dokumen internal dijawab sama dengan dokumen yang tidak ada** (`not_found`). Membedakannya berarti memberi tahu bahwa dokumen itu memang ada.

**`commercial_partner_id`, bukan `partner_id`.** Kontak cabang dan kontak pribadi di bawah satu perusahaan harus melihat job perusahaannya.

**External id model lintas modul di `ir.model.access.csv` harus berprefiks modulnya** (`custom_lgx_ff.model_lgx_shipment`). Tanpa prefiks hanya resolve untuk model yang modul ini sendiri definisikan atau warisi.

**Booking membuat job `draft`, bukan job berjalan.** Tidak ada pekerjaan yang masuk antrian operasi hanya karena seseorang mengisi formulir.
