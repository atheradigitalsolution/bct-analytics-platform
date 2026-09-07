# -*- coding: utf-8 -*-
"""Snapshot tingkat harga pada baris transaksi (keputusan D1).

Kenapa field ini harus ada sama sekali: ``sale.order.line.pricelist_item_id``
di Odoo 19 adalah compute **tanpa** ``store=True`` — tidak ada kolomnya di
database. ``price_unit`` memang tersimpan dan memang beku setelah baris dibuat,
jadi *berapa* harganya aman. Yang hilang adalah *tingkat mana* yang dipakai.
Tanpa itu, pasal 4 (dashboard omset per Harga 1-9) dan pasal 24 (laporan
penjualan per Harga 1-9) tidak punya sumbu untuk mengelompokkan apa pun.

Kebijakan pembekuan mengikuti Odoo, bukan mengarang sendiri: selama dokumen
masih bisa disunting, tingkat harga ikut pricelist yang dipilih — persis seperti
``price_unit`` yang dihitung ulang selama order masih draft. Begitu dokumen
dikonfirmasi, keduanya berhenti bergerak bersama-sama. Membekukan tingkat lebih
awal dari harga justru menghasilkan laporan yang bertentangan dengan struk.
"""

from odoo import api, fields, models

HJ_LEVEL_SELECTION = [(str(level), "Harga %d" % level) for level in range(1, 10)]


class NdiHjLevelMixin(models.AbstractModel):
    _name = "ndi.hj.level.mixin"
    _description = "NDI Snapshot Tingkat Harga pada Baris Transaksi"

    ndi_hj_level = fields.Selection(
        HJ_LEVEL_SELECTION,
        string="Tingkat Harga",
        store=True,
        readonly=False,
        index="btree_not_null",
        compute="_compute_ndi_hj_snapshot",
        precompute=True,
        help="Tingkat Harga 1-9 yang dipakai baris ini. Diambil dari pricelist dokumen "
             "dan berhenti berubah begitu dokumen tidak lagi bisa disunting.",
    )
    ndi_hpp_snapshot = fields.Float(
        string="HPP Saat Transaksi",
        digits="Product Price",
        store=True,
        readonly=False,
        compute="_compute_ndi_hj_snapshot",
        precompute=True,
        help="Biaya produk pada saat baris dibuat, DALAM SATUAN BARIS INI — sehingga "
             "qty * HPP bisa langsung dibandingkan dengan subtotal. Profit per baris "
             "dihitung dari sini, bukan dari standard_price sekarang yang sudah bergerak.",
    )
    ndi_hj_components = fields.Json(
        string="Komponen HJ Saat Transaksi",
        store=True,
        readonly=False,
        compute="_compute_ndi_hj_snapshot",
        precompute=True,
        help="Rincian pembentuk harga pada saat transaksi (pasal 4).",
    )

    # --- Kait yang diisi model konkret -------------------------------------

    def _ndi_pricelist(self):
        """Pricelist dokumen induk baris ini."""
        raise NotImplementedError

    def _ndi_is_frozen(self):
        """True bila baris tidak boleh lagi diperbarui snapshot-nya."""
        raise NotImplementedError

    def _ndi_product(self):
        return self.product_id

    def _ndi_line_uom(self):
        """Satuan yang dipakai ``qty`` dan ``price_unit`` pada baris ini.

        Bawaannya satuan referensi produk, yang benar untuk model baris yang
        memang tidak punya kolom UoM sendiri — ``pos.order.line`` salah satunya.
        ``sale.order.line`` menimpanya dengan ``product_uom_id``.
        """
        product = self._ndi_product()
        return product.uom_id if product else self.env["uom.uom"]

    # --- Perhitungan --------------------------------------------------------

    def _compute_ndi_hj_snapshot(self):
        for line in self:
            if line._ndi_is_frozen():
                # Tidak menugaskan apa pun — idiom yang sama dipakai
                # `sale.order.line._compute_price_unit` untuk baris yang tidak
                # boleh dihitung ulang. `Field.compute_value` sudah menandai
                # perhitungan selesai sebelum memanggil compute, jadi nilai lama
                # di basis data tetap berlaku. Inilah yang membuatnya snapshot.
                continue
            pricelist = line._ndi_pricelist()
            level = pricelist.ndi_hj_level if pricelist else 0
            line.ndi_hj_level = str(level) if level else False

            product = line._ndi_product()
            template = product.product_tmpl_id if product else None
            if template:
                # ------------------------------------------------------------------
                # KONVERSI SATUAN, DAN INI BUKAN KERAPIAN.
                #
                # `standard_price` selalu dinyatakan dalam SATUAN REFERENSI produk
                # (`product.uom_id`), sedangkan `qty` dan `price_unit` pada baris
                # dinyatakan dalam satuan BARIS. Untuk NDI keduanya berbeda pada
                # hampir setiap baris penjualan: produk pakan berbasis kg, tetapi
                # dijual per "SAK 50 KG" atau "SAK 30 KG".
                #
                # Tanpa konversi, `qty * ndi_hpp_snapshot` mengalikan jumlah sak
                # dengan biaya per kilogram. Biayanya keluar 50 kali terlalu kecil
                # dan marginnya terlihat luar biasa — bukan mustahil, hanya bagus,
                # yang justru membuatnya lolos pemeriksaan.
                #
                # Terukur di `ndi` sebelum perbaikan ini: rata-rata price_unit
                # 383.253 per SAK 50 KG melawan ndi_hpp_snapshot 6.922 per kg, dan
                # margin kotor gabungan terbaca 98,1% pada kanal sale sementara
                # kanal POS — yang produknya memang dijual dalam satuan referensi
                # dan karena itu tidak pernah terkena bug ini — terbaca 17,6%.
                # Dua kanal pada gudang data yang sama tidak boleh berbeda 5 kali
                # lipat karena alasan satuan.
                #
                # `_compute_price` mengalikan dengan rasio `factor` absolut kedua
                # satuan, jadi ia benar untuk arah mana pun dan tidak melakukan apa
                # pun ketika kedua satuan sama.
                # ------------------------------------------------------------------
                line.ndi_hpp_snapshot = product.uom_id._compute_price(
                    product.standard_price, line._ndi_line_uom()
                )
                line.ndi_hj_components = template._ndi_price_components()
            else:
                line.ndi_hpp_snapshot = 0.0
                line.ndi_hj_components = False

    @api.model
    def _ndi_level_int(self, value):
        return int(value) if value else 0
