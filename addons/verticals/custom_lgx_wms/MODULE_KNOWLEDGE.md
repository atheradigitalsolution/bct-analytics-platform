# LGX — Gudang 3PL (`custom_lgx_wms`)

> Versi 19.0.1.0.0 · lisensi LGPL-3 · `capability_tags`: logistics, wms, 3pl, multi-owner, consignment, sla
> Depends: custom_lgx_job, stock, stock_account

## Purpose

Operasi multi-pemilik di atas stock bawaan: segregasi owner_id, SLA per klien, stock opname siklus, dan barang klien yang TIDAK masuk neraca perusahaan.

## Business Flow

Dibangun DI ATAS ``stock`` bawaan, tidak menggantikannya. Yang ditambahkan hanya
apa yang membedakan gudang 3PL dari gudang biasa.

**Isi gudang bukan aset perusahaan.** Stok milik banyak pemilik berbeda, tidak
boleh bercampur di laporan, dan tidak boleh masuk neraca. Odoo menyediakan
``owner_id`` pada quant dan move line — terkonfirmasi ada di instalasi ini —
tetapi:

**`owner_id` saja TIDAK mengecualikan barang dari valuasi.** Ini keputusan 2 di
Fase 0, dan jawabannya harus dibuktikan, bukan diasumsikan: dengan
``stock_account`` dan valuasi otomatis, penerimaan tetap membentuk jurnal tanpa
memedulikan pemilik. Mekanisme yang dipakai modul ini adalah **kategori produk
non-valuasi khusus barang klien** (``property_valuation = periodic``),
dan itu dibuktikan tes LGX-E07: menerima barang milik klien tidak menghasilkan
satu pun ``account.move``.

## Key Models

`lgx.wms.client` · pemilik barang, zona, dan kategori produk non-valuasi
`lgx.wms.sla` / `.measurement` · SLA kontraktual dan pengukurannya
`lgx.wms.count.program` / `.task` / `.line` · stock opname siklus per kelas ABC
`stock.picking` / `stock.move` / `stock.quant` · diperluas dengan klien gudang
`product.category` · penanda `lgx_is_client_goods`

## Public Methods

`lgx.wms.client.lgx_find_by_owner(owner)`
`lgx.wms.client.action_activate()` · menuntut job gudang sudah ada
`lgx.wms.count.program.action_generate_tasks()` / `._cron_generate_count_tasks()`
`lgx.wms.count.task.action_create_recount()` / `.action_approve_adjustment()`

## Integration Points

`custom_lgx_wms_billing` membaca quant lewat cron potret. Isolasi antar klien ditegakkan record rule pada `stock.quant` dan `stock.picking` untuk grup portal.

## Gotchas

**`owner_id` saja TIDAK mengecualikan quant dari valuasi.** Ini keputusan 2 di Fase 0 dan butir A14b. Dengan `stock_account` dan valuasi otomatis, penerimaan tetap membentuk jurnal tanpa memedulikan pemilik. Mekanisme yang benar-benar bekerja adalah **kategori produk non-valuasi**, dan itu dibuktikan tes LGX-E07 — bukan diasumsikan.

**Odoo 19 memakai nilai `periodic`, bukan `manual_periodic`,** pada `product.category.property_valuation`. Contoh kode versi 17/18 akan gagal dengan `ValueError: Wrong value`.

**`stock.valuation.layer` TIDAK ADA di Odoo 19.** Pemeriksaan valuasi dilakukan langsung pada buku besar — dan itu justru pemeriksaan yang lebih tepat, karena yang dipersoalkan neraca adalah jurnalnya.

**`stock.move.name` DIHAPUS di Odoo 19** → `description_picking`. Setiap contoh kode lama yang membuat `stock.move` akan gagal.

**Penerimaan tanpa pemilik ditolak saat validasi picking.** Stok tanpa pemilik di gudang multi-klien akan tercampur, dan stok yang sudah tercampur tidak dapat dipisahkan tanpa stock opname penuh.
