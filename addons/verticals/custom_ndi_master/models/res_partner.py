# -*- coding: utf-8 -*-
"""Dua dimensi pelanggan yang harus bisa direplikasi ke warehouse.

Keduanya lahir dari addendum koreksi Lead (`20-odoo/06-ADDENDUM-KOREKSI-LEAD.md`),
bukan dari selera penamaan:

**K-2 — tipe pelanggan tidak boleh many2many.** Bentuk yang "wajar" untuk
"distributor / poultry shop / peternak / retail" adalah ``res.partner.category``.
Bentuk itu mati di seam replikasi: tabel relasinya
``res_partner_res_partner_category_rel`` tidak punya kolom ``id``, sehingga
``publication_column_list()`` menolaknya secara struktural — tabel itu tidak akan
pernah bisa masuk publication logical decoding. Analisis "penjualan per tipe
pelanggan" (pasal 24) karena itu mustahil lewat tag. Selection skalar hidup di
kolom ``res_partner`` sendiri dan ikut terreplikasi apa adanya.

**K-3 — wilayah tidak boleh menumpang ``city``.** ``res_partner.city``
diklasifikasi ``personal`` di ``custom_pdp_core`` dan karena itu di-hash HMAC saat
load ke warehouse. Digest-nya konsisten (join tetap hidup) tetapi tidak terbaca
manusia, jadi dashboard wilayah hanya akan menampilkan hash. Dimensi wilayah butuh
kolom sendiri yang berkelas ``internal``.

Selection, bukan many2one ke model wilayah tersendiri: daftar wilayah pemasaran NDI
adalah daftar tertutup yang berubah setahun sekali, dan Selection menaruh nilainya
langsung di kolom fakta sehingga warehouse tidak perlu satu tabel dimensi tambahan
beserta klasifikasi PDP-nya sendiri.
"""

from odoo import fields, models

#: Tipe pelanggan sepanjang rantai distribusi pakan: pabrik -> distributor ->
#: poultry shop -> peternak, ditambah pembeli eceran di outlet.
NDI_CUSTOMER_TYPE = [
    ("distributor", "Distributor"),
    ("poultry_shop", "Poultry Shop"),
    ("peternak", "Peternak"),
    ("retail", "Retail / Eceran"),
]

#: Wilayah pemasaran. Bukan pembagian administratif: ini klaster jarak kirim dari
#: pabrik Sidoarjo, yang memang dipakai untuk menghitung ongkir dan menilai sales.
NDI_SALES_REGION = [
    ("sidoarjo_raya", "Sidoarjo Raya"),
    ("surabaya_raya", "Surabaya Raya"),
    ("malang_raya", "Malang Raya"),
    ("kediri_raya", "Kediri Raya"),
    ("madiun_raya", "Madiun Raya"),
    ("tapal_kuda", "Tapal Kuda"),
    ("pantura_jatim", "Pantura Jawa Timur"),
    ("luar_jatim", "Luar Jawa Timur"),
]


class ResPartner(models.Model):
    _inherit = "res.partner"

    ndi_customer_type = fields.Selection(
        NDI_CUSTOMER_TYPE,
        string="Tipe Pelanggan NDI",
        index="btree_not_null",
        help="Posisi pelanggan pada rantai distribusi pakan. Dipakai sebagai sumbu "
             "laporan penjualan per tipe pelanggan (pasal 24).",
    )
    ndi_sales_region = fields.Selection(
        NDI_SALES_REGION,
        string="Wilayah Pemasaran NDI",
        index="btree_not_null",
        help="Dimensi wilayah untuk laporan dan dashboard. Terpisah dari Kota karena "
             "kolom Kota diklasifikasi 'personal' dan di-hash saat replikasi.",
    )
