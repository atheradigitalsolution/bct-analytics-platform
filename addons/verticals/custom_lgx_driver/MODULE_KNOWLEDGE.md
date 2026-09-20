# LGX — Pengemudi & Kepatuhan Jam Kerja (`custom_lgx_driver`)

> Versi 19.0.1.0.0 · lisensi LGPL-3 · `capability_tags`: logistics, driver, compliance, working-hours, indonesia
> Depends: custom_lgx_tms, hr

## Purpose

Tautan pengemudi ke hr.employee, log jam kerja yang dihitung dari waktu aktual trip, dan penandaan pelanggaran jam mengemudi dengan jejak audit.

## Business Flow

**Jejak audit kepatuhan adalah kepentingan PERUSAHAAN, bukan pengemudi.**
UU 22/2009 Pasal 92 memberi sanksi administratif kepada perusahaan — mulai
peringatan tertulis sampai pencabutan izin — bukan hanya kepada pengemudi.
Karena itu jam mengemudi dihitung dari waktu aktual trip dan pelanggarannya
ditandai, bukan dibiarkan menjadi pengetahuan lisan.

⚠ Keempat ambang (4 jam mengemudi berturut-turut, istirahat 30 menit, 8 jam
kerja sehari, 12 jam batas mutlak) baru bersumber SEKUNDER. Pasal 90 dan 92
UU 22/2009 harus dibaca langsung dari JDIH sebelum angkanya dikunci — butir A12c
di Lampiran A. Karena itu keempatnya adalah parameter sistem, bukan konstanta.

Perpanjangan sampai 12 jam menuntut alasan DAN penyetuju tercatat. Perpanjangan
yang bisa dilakukan tanpa jejak adalah perpanjangan yang akan menjadi kebiasaan.

## Key Models

`lgx.driver` · diperluas dengan `employee_id`, pelatihan, dan ringkasan pelanggaran
`lgx.driver.training` · pelatihan bersertifikat
`lgx.driver.duty.log` · jam kerja harian, dihitung dari waktu AKTUAL trip

## Public Methods

`lgx.driver.duty.log._cron_build_duty_logs(for_date)` · idempoten per (pengemudi, tanggal)
`lgx.driver.duty.log._thresholds()` · keempat ambang dari `ir.config_parameter`
`lgx.driver.duty.log.action_approve_extension()`

## Integration Points

Membaca `lgx.trip.actual_start` dan `.actual_end`. Aplikasi pengemudi memakai `custom_lgx_api.lgx.api.service.driver_trip_list` dan `.submit_pod`.

## Gotchas

**Pelanggaran DITANDAI, bukan DITOLAK penyimpanannya.** Godaan awalnya adalah membuat ini constraint yang menolak `create`. Itu salah arah: log ini merekam apa yang SUDAH terjadi, dan menolak menyimpannya berarti pelanggaran yang sebenarnya terjadi tidak tercatat di mana pun — persis kebalikan dari jejak audit yang Pasal 92 membuat perusahaan membutuhkannya.

**Sanksi Pasal 92 UU 22/2009 jatuh pada PERUSAHAAN**, bukan hanya pengemudi. Itulah alasan strukturalnya, bukan kepatuhan formal.

⚠ Keempat ambang (4 jam, 30 menit, 8 jam, 12 jam) baru bersumber SEKUNDER. Pasal 90 dan 92 harus dibaca langsung dari JDIH sebelum dikunci (butir A12c).
