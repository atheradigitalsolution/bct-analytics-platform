# LGX — Master Data Logistik (`custom_lgx_base`)

> Versi 19.0.1.0.0 · lisensi LGPL-3 · `capability_tags`: logistics, freight-forwarding, trucking, warehouse-3pl, master-data, indonesia
> Depends: base, mail, contacts, uom, product, account, custom_doc_numbering, custom_operating_unit

## Purpose

Fondasi vertical logistik ATHERA: simpul jaringan, kode charge, tipe kontainer, kantor pabean, jenis dokumen, template milestone, cabang/NITKU, dan delapan privilege terpisah.

## Business Flow

Lapisan master untuk vertical logistik (freight forwarding, trucking, gudang
3PL). Semua modul ``custom_lgx_*`` lain berdiri di atas modul ini.

**Cabang adalah ``operating.unit``, bukan model baru.** Keputusan A24 di
spesifikasi. ``custom_operating_unit`` sudah menstempel ``operating_unit_id``
pada ``account.move``, ``sale.order`` dan ``stock.picking`` berikut record
rule-nya, jadi dimensi cabang untuk faktur dan laporan pajak sudah ada. Modul
ini hanya menambahkan identitas pajak cabang: NITKU 22 digit, NPWP 16 digit,
kantor pabean, dan KBLI dua versi.

**Kode charge adalah tempat pengetahuan pajak disimpan sekali.**
``lgx.charge.code`` membawa ``default_nature`` (service / disbursement),
``is_freight_charge`` (syarat PPN besaran tertentu), ``vat_treatment`` dan
``default_wht_type``. Setiap baris biaya pada job mewarisi keempatnya, sehingga
perlakuan pajak tidak pernah diketik ulang per transaksi.

**Delapan privilege terpisah.** Odoo 19 merender semua grup yang berbagi satu
``res.groups.privilege`` sebagai dropdown pilih-satu; satu privilege untuk semua
peran akan membuat dispatcher kehilangan hak gudangnya begitu form user
disimpan.

## Key Models

`lgx.location` · simpul jaringan (pelabuhan, bandara, depo, CFS, gudang, kota)
`lgx.customs.office` · kantor pabean, membawa `partner_id` penerima pembayaran pungutan
`lgx.charge.code` · master item tagih; tempat pengetahuan pajak disimpan sekali
`lgx.container.type` · tipe kontainer ISO berikut TEU dan volume dalam
`lgx.commodity` · komoditas, termasuk penanda barang berbahaya
`lgx.document.type` · jenis dokumen + flag bea meterai + milestone yang dihalanginya
`lgx.milestone.type` / `lgx.milestone.template` · mesin pelacakan lintas segmen
`lgx.integration.message` · log pesan CEISA / NLE / Coretax
`lgx.kbli` · KBLI 2020 dan 2025 berikut pemetaan antar versi
`lgx.numbering.mixin` · AbstractModel penomoran dokumen
res.partner · peran logistik, NIB, jenis akses kepabeanan, NITKU
operating.unit · NITKU 22 digit, NPWP 16 digit, kantor pabean, KBLI dua versi

## Public Methods

`lgx.numbering.mixin._lgx_next_number(code, date)` · nomor berikutnya, sadar perusahaan dan reset bulanan
`res.partner.lgx_has_valid_npwp()` · True bila NPWP 16 digit; dipakai penentuan tarif 2% vs 4%
`lgx.location.lgx_find_applicable` — tidak ada; pencarian simpul memakai search biasa

## Integration Points

Seluruh modul `custom_lgx_*` lain berdiri di atas modul ini. `lgx.charge.code.product_id` adalah jembatan wajib ke `account.move.line`; kode charge tanpa produk adalah baris yang tidak punya jalan ke akuntansi.

## Gotchas

**KBLI disimpan DUA VERSI, bukan salah satu.** Masa transisi 2020 ⇄ 2025 berjalan paralel, dan dokumen perizinan yang sama bisa menyebut kode berbeda tergantung kapan ia terbit. Pemetaannya Many2many karena konversi tidak selalu satu-ke-satu. Baris yang belum dikonfirmasi ke OSS/BPS ditandai `is_verified = False` dan TERLIHAT begitu di layar — bukan disembunyikan di komentar kode. Daftar bawaan sengaja kecil; KBLI lengkap dimuat lewat `lgx.kbli.lgx_import_csv`.

**Cabang adalah `operating.unit`, bukan model baru.** Keputusan A24. `custom_operating_unit` sudah menstempel `operating_unit_id` pada `account.move`, `sale.order` dan `stock.picking` berikut record rule dan klaim JWT `allowed_ou`, jadi dimensi cabang pada jurnal SUDAH ADA. Membuat `lgx.branch` berarti membangun ulang semuanya.

**Delapan privilege terpisah, dan jangan pernah menumpang privilege modul lain.** Odoo 19 merender semua grup yang berbagi satu privilege sebagai dropdown pilih-satu; menyimpan form user akan diam-diam mencabut sisanya. Setelah mengubah grup yang bersifat keamanan, **restart container odoo** — worker HTTP menyimpan cache grup sendiri-sendiri.

**`custom_doc_numbering` menarik `sale_management`, `purchase`, `stock`, `account`, `custom_bast` dan `custom_core`.** Konsekuensinya seluruh pohon itu ikut terpasang bersama `custom_lgx_base`. Itu diterima dengan sadar: nilainya adalah `ir.sequence.x_monthly_reset`, dan reset bulanan adalah bentuk yang dipakai seluruh dokumen di repo ini.

**CBM, Ton dan Km TIDAK dibuat ulang** — Odoo sudah punya `uom.product_uom_cubic_meter`, `_ton`, `_km`. Satuan tagih yang memang tidak ada (pallet-hari, CBM-hari, SKU-bulan, ritase) dibuat sebagai AKAR pohon UoM sendiri, tanpa induk, karena pallet-hari tidak dapat dikonversi ke CBM dan tidak boleh bisa.

**Kode simpul boleh memuat tanda hubung.** UN/LOCODE murni lima huruf, tetapi depo dan CFS diberi kode turunan seperti `IDJKT-D1`. Melarang tanda hubung memaksa kode internal menjadi rangkaian huruf yang tidak terbaca.
