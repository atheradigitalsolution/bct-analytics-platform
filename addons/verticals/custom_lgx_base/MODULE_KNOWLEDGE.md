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

## Jebakan Odoo 19 yang sudah kami bayar

Dikumpulkan di sini, bukan di memori sesi, karena tiap satu di antaranya sudah
dibayar lebih dari sekali. Semuanya punya bentuk yang sama: **Odoo menerima kode
yang salah tanpa mengeluh, lalu tidak mengerjakan apa yang tertulis.**

**`_sql_constraints` diterima tanpa keluhan dan TIDAK membuat apa pun.** Odoo 19
hanya menulis WARNING lalu jalan terus. Modul terpasang "sukses" sementara
keunikan yang Anda kira dijaga tidak dijaga sama sekali. Pakai
`models.Constraint`. Dan jangan percaya bahwa ia terpasang — rekonsiliasikan:

```
# jumlah yang dideklarasikan di kode
grep -rc "models.Constraint(" addons/verticals/custom_lgx_*/models/*.py | awk -F: '{s+=$2} END {print s}'
# dan yang benar-benar ada, DIPERIKSA PER NAMA
docker exec odoo19-bct-postgres psql -U odoo -d athera_lgx -t -A \
  -c "SELECT conname FROM pg_constraint WHERE contype IN ('c','u');"
```

Nama di Postgres adalah `<tabel>_<atribut tanpa garis bawah awal>`: `_rates_sane`
pada `lgx.hs.code` menjadi `lgx_hs_code_rates_sane`.

**Bandingkan NAMA, bukan JUMLAH.** Dua `count()` yang sama bukan bukti bahwa
himpunannya sama: satu constraint hilang ditambah satu yatim dari model yang
sudah dihapus menghasilkan selisih nol yang sepenuhnya salah — tepat pada hal
yang diperiksa karena ia pernah gagal senyap.

**Periksa DUA ARAH.** `comm -23` menemukan yang dideklarasikan tapi tidak ada;
`comm -13` menemukan yang ada tapi tidak dideklarasikan. Yang kedua menangkap
sisa dari model yang di-rename atau dihapus. Batasi daftar aktual ke tabel
`lgx\_%` supaya arah kedua bermakna — tanpa itu seluruh constraint Odoo inti
ikut terhitung sebagai yatim.

**Beri rekonsiliasinya DUA kontrol positif**, karena ia punya dua sisi yang bisa
rusak sendiri-sendiri:

* A — sisipkan nama palsu ke daftar HARAPAN; ia harus dilaporkan hilang.
  Menguji bahwa pembandingnya hidup.
* B — buang satu nama NYATA dari daftar AKTUAL; ia harus dilaporkan hilang.
  Menguji bahwa ia membaca daftar Postgres yang benar. **A saja akan lolos
  meski daftar aktualnya diambil dari tempat yang salah.**

Terakhir direkonsiliasi 2026-09-20 dengan kedua arah dan kedua kontrol:
**67 dideklarasikan, 67 ada, nol hilang, nol yatim.** Enam puluh enam di antaranya
pada tabel `lgx_*`; satu — `fleet_vehicle_jbi_not_above_jbb` — pada tabel warisan,
dan constraint pada model yang di-`_inherit` memang tidak akan muncul di
penyaringan `lgx_%`. Hitung terpisah, jangan dianggap hilang.

Periksa per nama, bukan dengan mencoba menyimpan data jelek — uji perilaku
menjawab "sesuatu menolak ini", yang bisa saja ACL atau kebetulan.

**`browse(id)` atas id yang tidak ada bernilai TRUTHY.** Jadi `if not record`
melewatkannya, dan yang meledak adalah pembacaan field jauh sesudahnya sebagai
`MissingError`, atau basis data saat menulis sebagai pelanggaran foreign key.
Selalu `.exists()` untuk id yang datang dari luar.

**`stock.move.name` dihapus.** Penggantinya `description_picking`. Gejalanya
`KeyError: 'name'` saat `create`, yang terbaca seperti kesalahan fixture.

**`stock.valuation.layer` dihapus**; pakai `account.move.line`. **`product.packaging`
dan `uom.category` dihapus**; UoM kini berjenjang lewat `relative_factor`.
**`property_valuation`** memakai nilai `periodic`, bukan `manual_periodic`.

**`<tree>` menjadi `<list>`**, dan `<group>` TIDAK sah di dalam `<search>` —
pakai `<separator/>` dengan filter datar. `create="false"` tidak sah pada
`<pivot>`.

**`res.users.groups_id` menjadi `group_ids`.**

**`<record model="res.groups">` pada grup yang lahir di blok `noupdate="1"`
dilewati diam-diam.** Untuk menambah implikasi grup, pakai `<function>` yang
memanggil method ber-`@api.model` — tanpa dekorator itu ia gagal dengan
`not enough values to unpack`.

**`HttpCase` menuntut server threaded.** Dengan `PreforkServer` ia gagal di
`setUpClass` dengan `AttributeError: 'PreforkServer' object has no attribute
'httpd'`, dan SELURUH kelas tidak berjalan — sementara pencacah kegagalan yang
hanya mencari `FAIL: Kelas.metode` melaporkan nol. Jalankan dengan
`--workers=0`, dan longgarkan `--db-filter='.*'` di harness saja: dbfilter
produksi `^%d` membuat `HttpCase` yang memanggil `127.0.0.1` mendapat label
`"127"`, tidak menemukan database, dan menjawab **404 di setiap rute**.

**Perubahan templat/view tidak ikut `restart`.** Arch hidup di `ir_ui_view` dan
hanya ditulis ulang saat `-u`. Gejalanya identik dengan kode basi. Periksa ke
basis datanya:

```
SELECT count(*) FROM ir_ui_view WHERE key='<modul>.<template>' AND arch_db::text LIKE '%<penanda>%';
```

**Tiga bentuk "tes yang tidak berjalan dan tidak ada yang mengeluh".** Ketiganya
ditemukan dalam satu hari, dan tiap bentuk lolos dari pemeriksaan yang menangkap
bentuk sebelumnya:

1. Direktori `tests/` tanpa `__init__.py` — tampak berisi, menjalankan nol.
2. Berkas tes yang ada dan direktorinya TIDAK kosong, tetapi tidak diimpor di
   `__init__.py`. Lolos dari pemeriksaan (1).
3. Berkas yang ada DAN diimpor, tetapi metodenya tersarang: satu `def` tingkat
   modul yang disisipkan di tengah badan kelas mengakhiri kelas itu, dan metode
   sesudahnya menjadi isi fungsi tersebut. Python tidak mengeluh — hasilnya sah
   secara sintaksis, sekadar bukan yang dimaksud. Lolos dari (1) dan (2).

Ketiganya kini ditegakkan `tests/test_odoo19_traps.py`, kecuali bentuk (1) yang
tidak dapat ditegakkan karena git tidak melacak direktori kosong.

**Hook data demo hanya berjalan saat INSTALL.** Menyunting `hooks.py` tidak
menyentuh database yang sudah terpasang; baris lama perlu dikoreksi lewat ORM.
