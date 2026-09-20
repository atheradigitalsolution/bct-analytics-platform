# LGX — Dokumen & Masa Berlaku (`custom_lgx_doc`)

> Versi 19.0.1.0.0 · lisensi LGPL-3 · `capability_tags`: logistics, documents, expiry, compliance, checklist
> Depends: custom_lgx_job

## Purpose

Satu mesin peringatan masa berlaku untuk KIR, STNK, Kartu Pengawasan, SIM, sertifikat ahli kepabeanan dan izin usaha; plus checklist dokumen per jenis job.

## Business Flow

**Satu mesin, bukan lima implementasi terpisah.** KIR, STNK, Kartu Pengawasan,
SIM, sertifikat Ahli Kepabeanan dan izin usaha adalah masalah yang sama: sebuah
tanggal yang kalau lewat membuat sesuatu tidak boleh beroperasi. Menulis lima
pemeriksaan terpisah berarti lima tempat yang dapat berbeda diam-diam, dan
perbedaan itu baru ketahuan saat salah satunya tidak pernah memperingatkan.

**Peringatan menjadi AKTIVITAS pada penanggung jawab, bukan hanya baris di
dashboard.** Daftar yang tidak menempel pada siapa pun adalah daftar yang tidak
dibaca siapa pun.

**Checklist dokumen MENGHALANGI milestone, bukan sekadar mengingatkan.** Dokumen
yang baru ketahuan kurang saat barang sudah di pelabuhan adalah demurrage yang
sudah berjalan.

## Key Models

`lgx.document` · dokumen bermasa-berlaku, referensi polimorfik ke pemiliknya
`lgx.document.checklist` / `.template` · checklist per jenis job

## Public Methods

`lgx.document._cron_warn_expiring()` · idempoten per hari
`lgx.document.lgx_attach_to(record, document_type, number, expiry_date)`
`lgx.job.action_generate_checklist()` · idempoten
`lgx.job.lgx_log_milestone(...)` · **di-override**: menolak milestone yang dihalangi dokumen

## Integration Points

Mesin generik ini menggantikan pemeriksaan sementara di `custom_lgx_customs` (sertifikat ahli) dan `custom_lgx_fleet` (KIR/STNK/KP) tanpa mengubah perilaku yang sudah diuji.

## Gotchas

**Checklist MENAHAN milestone, tidak sekadar mengingatkan.** Dokumen yang baru ketahuan kurang saat barang sudah di pelabuhan adalah demurrage yang sudah berjalan.

**Penahanan dilewati untuk `source` = `system` dan `nle`.** Menolak fakta yang sudah terjadi di luar sistem hanya membuat data berhenti mencerminkan lapangan.

**Referensi polimorfik (`res_model` + `res_id`), bukan enam Many2one opsional** yang lima di antaranya selalu kosong.

**Bea meterai: e-meterai dibubuhkan SEBELUM tanda tangan digital** (catatan Peruri). Urutannya tidak dapat dibalik. Di sini hanya dicatat sebagai flag; penegakannya ada di lapisan e-signing.
