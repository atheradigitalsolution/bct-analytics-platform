# custom_ndi_data_seed — apa yang sudah dibayar mahal

Modul fixture untuk PT Nutrisi Daya Indonesia. Catatan ini bukan ringkasan kode; ia
daftar hal yang **sudah pernah salah** di modul ini dan kenapa perbaikannya berbentuk
seperti sekarang. Kalau kamu akan mengubah salah satu di bawah, baca alasannya dulu.

## Cacat yang benar-benar terjadi

### 1. `purchase.order.line.product_uom_qty` bukan kolom kuantitas

Ditulis pertama kali sebagai `product_uom_qty`. Pada Odoo 19 field itu adalah compute
**stored** ("Total Quantity", hasil konversi ke satuan referensi produk); menulisnya
tidak berpengaruh apa pun, dan `product_qty` yang wajib itu jatuh ke default **1,0**.

Yang membuatnya mahal bukan salahnya, melainkan bentuk gejalanya: 22 PO tetap
terkonfirmasi, 25 penerimaan tetap `done`, 22 tagihan pemasok tetap diposting. Tidak
ada satu pun galat. Kegagalan baru muncul sebelas langkah kemudian sebagai *"MO tidak
bisa direservasi penuh"*, dan pesan galat versi pertama menyarankan **"naikkan
penyangga pembelian"** — tuas yang sepenuhnya salah, karena 1 × 1,45 tetap 1.

Dua pelajaran yang sudah dikodekan:

* `sale.order.line` dan `stock.move` memakai `product_uom_qty` sebagai kuantitas,
  `purchase.order.line` memakai `product_qty`. Namanya terbalik antar model. Ada
  komentar panjang di tempatnya justru karena "sudah jelas" tidak menyelamatkan siapa pun.
* Pesan galat reservasi sekarang menyebut **stok tersedia vs dibutuhkan per bahan**.
  Selisih "butuh 2.750,000, tersedia 6,000" langsung terbaca sebagai salah hitung;
  "butuh 2.750" saja terbaca sebagai kurang stok.

### 2. Loop tak berujung di `partial_receipt_slots`

`partial_receipts=26` di atas `months=1` dan 22 PO per bulan: pencarian slot kosong
berputar selamanya di dalam bulan yang sudah penuh. Gejalanya satu proses Python 100%
CPU **tanpa satu pun query** — dari luar tidak bisa dibedakan dari "sedang bekerja".
Sekarang kapasitas `months x len(PO_PLAN)` dihitung eksplisit dan pencariannya dibatasi.

### 3. Lokasi sumber MO ditimpa compute

`mrp.production.location_src_id` adalah compute **stored** yang bergantung pada
`picking_type_id`. Nilai yang dikirim lewat `create()` ditimpa. MO lalu mencari bahan di
gudang produk jadi yang memang tidak pernah menerima bahan. Perbaikannya bukan menulis
ulang setelah create, melainkan menyetel `manu_type_id.default_location_src_id` ke lokasi
gudang bahan baku — satu tempat, dan benar untuk semua yang menurunkan lokasinya dari
tipe operasi.

### 4. Yield rata 100%

Versi pertama menyelesaikan setiap MO dengan hasil **persis** sebesar targetnya. Semua
angka benar, tidak ada galat, dan grafik yield adalah garis datar di 100% — metrik benar,
kueri benar, datanya tidak punya apa pun untuk ditunjukkan. Untuk pabrik pakan, yield
justru salah satu angka yang paling dibaca pemilik.

Sekarang susut normal diserap ke hasil (pasal 11): `move_raw_ids.quantity` dikembalikan
ke jumlah rencana **setelah** `_set_qty_producing()` menskalakannya turun, sehingga bahan
tetap habis sesuai formula dan hasilnya yang kurang. Kalau langkah pengembalian itu
dihapus, bahan ikut berkurang dan susutnya hilang dari data sama sekali.

### 5. Wizard yang tidak bisa dijawab generator

Tiga kali, dan ketiganya berhenti di tempat berbeda:

* `stock.backorder.confirmation` — `create_backorder` harus `always` pada **setiap** tipe
  penerimaan, bukan hanya gudang bahan baku: barang dagangan diterima di gudang produk jadi;
* `confirm.stock.sms` — `stock_sms` menyisipkan konfirmasi kirim SMS di depan setiap
  validasi pengiriman. Butuh `with_context(skip_sms=True)`. Tanpa itu, sample data
  benar-benar mengirim SMS ke nomor contoh;
* wizard backorder MO — `with_context(skip_backorder=True)` plus
  `create_backorder='never'` pada tipe operasi manufaktur.

`_validate_picking()` menolak kalau `button_validate()` mengembalikan action apa pun,
dan menyebut model wizardnya. Menelan hasilnya diam-diam adalah cara paling langsung
menghasilkan picking yang tidak pernah selesai.

### 6. `stock.move` Odoo 19 tidak punya field `name`

Deskripsi baris pindah ke `description_picking`. Mengirim `name` membuat `create()`
menolak seluruh transfer.

## Keputusan yang sengaja, jangan dibalik tanpa alasan

**Empat `stock.warehouse`, bukan empat `stock.location`.** Sebagai lokasi anak di bawah
satu gudang, setiap dokumen harus menimpa `location_id`/`location_dest_id` hasil rute
Odoo satu per satu, dan setiap tempat yang terlewat diam-diam memakai WH/Stock. Sebagai
gudang, `purchase.order.picking_type_id`, `sale.order.warehouse_id` dan
`pos.config.picking_type_id` sudah menunjuk tempat yang benar tanpa penimpaan manual.
Gudang bawaan `WH` sengaja tidak dipakai.

**Kemasan masuk sebagai baris BOM ber-`ndi_persen` 0.** Spesifikasi §3.1 memisahkannya
karena kolom persen wajib berjumlah 100. Tapi `mrp.bom` hanya punya satu tabel baris, dan
tanpa baris kemasan produksi tidak mengonsumsi karung sama sekali — padahal biaya kemasan
adalah komponen HPP yang direkonsiliasi UJI 5 spesifikasi. 146 baris formula + 48 baris
kemasan = 194.

**`stock.scrap` abnormal waste TIDAK mengisi `production_id`.** Scrap yang tertaut MO ikut
terbawa setiap kueri yang menjumlahkan `stock_move.production_id`, termasuk kueri yield —
dan hasilnya yield tampak **melebihi** 100% pada MO yang justru paling rugi. Tautannya
lewat `origin`, yang terbaca manusia dan tidak mencemari agregat.

**Tanggal dijepit ke hari berjalan.** Jendela 12 bulan spesifikasi berakhir setelah
tanggal berjalan. Memposting jurnal bertanggal masa depan membuat laporan periode
berjalan memuat baris yang belum terjadi.

**Tidak ada `reset`.** Dokumen dataset ini memuat jurnal yang sudah diposting dan stock
move yang sudah `done`, dan Odoo melarang menghapus keduanya **secara desain**. Fixture
yang mengapalkan bypass audit trail lebih buruk daripada ketidaknyamanan yang
dihematnya. Jalan yang didukung untuk bentuk lain adalah `dataset` baru.

## Pass produksi tambahan

`generate_extra_production()` berdiri terpisah dari `generate()` dengan namespace external
ID sendiri (`p2`) dan parameter bentuknya sendiri. Ia ada justru karena konsekuensi di
atas: data yang sudah mendarat tidak bisa **diubah**, hanya bisa **ditambahi**. Ia
membeli bahan yang kurang lebih dulu dari pemasok yang benar (digerakkan kebutuhan, bukan
jadwal), jadi tidak ada MO yang diselesaikan di atas stok yang tidak ada.

## Yang TIDAK dikerjakan

* SKU maklun `FG-MKL-01` (spesifikasi §6.1) — ia `produk_jadi` tanpa BOM, dan UJI 4 skrip
  verifikasi menegakkan "setiap produk jadi wajib punya BOM aktif". Menambahkannya butuh
  penanda `jenis_produksi` di master dulu (rekomendasi G-17).
* Retur pembelian (8) dan retur penjualan (6).
* Sesi kasir dengan selisih kas ≠ 0 — menutup sesi dengan selisih menuntut akun selisih
  kas yang tidak disetel l10n_id.
* Record insentif bulanan/kwartal — modul insentifnya belum ada.
