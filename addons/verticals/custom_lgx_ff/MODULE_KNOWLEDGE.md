# LGX — Freight Forwarding (`custom_lgx_ff`)

> Versi 19.0.1.0.0 · lisensi LGPL-3 · `capability_tags`: logistics, freight-forwarding, consolidation, container, demurrage
> Depends: custom_lgx_job, custom_lgx_pricing

## Purpose

Shipment, konsolidasi master/house, B/L & AWB, kontainer dengan validasi ISO 6346, berat yang ditagih, dan perhitungan demurrage/detensi yang menahan penutupan job.

## Business Flow

**Konsolidasi adalah mekanisme yang membuat forwarding menguntungkan, dan yang
paling sering salah dimodelkan.** Forwarder membeli satu kontainer penuh dari
pelayaran lalu menjual ruangnya ke banyak pengirim kecil. Akibatnya dokumen
berlapis dua: Master B/L dari carrier ke forwarder, House B/L dari forwarder ke
tiap pengirim. Model datanya karena itu rekursif: satu shipment bisa menjadi
induk shipment lain, P&L konsol dihitung di tingkat master sementara tagihan
terbit di tingkat house.

**Demurrage dan detensi adalah sumber kebocoran nomor satu.** Keduanya berbeda:
demurrage untuk kontainer yang terlalu lama DI DALAM terminal, detensi untuk
kontainer yang sudah KELUAR dan terlambat dikembalikan. Carrier menagihkannya
beberapa minggu kemudian, dan kalau job sudah ditutup, biaya itu tidak pernah
diteruskan ke pelanggan. Karena itu kontainer yang belum kembali MENAHAN job
agar tidak bisa diselesaikan.

**Berat yang ditagih memakai faktor dari rate card, bukan konstanta.** Angka 6000
untuk udara adalah standar IATA, tetapi carrier boleh berbeda dan pembulatan
berbeda lagi.

## Key Models

`lgx.shipment` · pengangkutan; `is_master` + `parent_shipment_id` memodelkan konsolidasi
`lgx.container` · validasi ISO 6346, demurrage dan detensi berjalan
`lgx.package` · **pengganti `product.packaging` yang DIHAPUS di Odoo 19**

## Public Methods

`iso6346_check_digit(prefix_and_serial)` · fungsi modul, dapat diuji sendiri
`lgx.shipment._fallback_chargeable_weight()` · dipakai bila tidak ada rate card
`lgx.shipment.action_book/depart/arrive/complete`
`lgx.container._cron_warn_containers_at_risk()`
`lgx.job.action_generate_agent_share()` · bagian agen job nominasi sebagai baris biaya

## Integration Points

Menambah penghalang `_lgx_completion_blockers` pada job: kontainer yang belum kembali menahan penyelesaian. `custom_lgx_tms_ff` menyambungkan tanggal gerbang kontainer ke pergerakan trip.

## Gotchas

**Tabel huruf ISO 6346 MELEWATI setiap kelipatan 11** — tidak ada 11, 22, atau 33. Itu bukan salah ketik; itu standarnya. Algoritmenya diuji terhadap `CSQU3054383`, contoh kanonik yang diterbitkan standar.

**Demurrage dan detensi dihitung PER KONTAINER**, bukan per shipment: masa bebas berjalan per kontainer dan satu shipment bisa punya sepuluh kontainer yang keluar di hari berbeda.

**Hitungan BERJALAN, bukan hanya saat kontainer sudah kembali.** Demurrage yang baru dihitung setelah kontainer kembali adalah demurrage yang baru ketahuan setelah tidak bisa ditagihkan lagi.

**P&L konsol = pendapatan SELURUH house dikurangi biaya pada MASTER.** Menjumlahkan margin per house akan menghitung biaya master sebanyak jumlah house-nya, dan konsol yang sebenarnya rugi akan tampak untung berlipat.

**Faktor volumetrik berasal dari rate card, tidak pernah dari kode.** 6000 adalah default IATA; carrier boleh berbeda, dan setiap carrier baru tidak boleh menjadi rilis modul.
