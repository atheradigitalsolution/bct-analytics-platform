# -*- coding: utf-8 -*-
"""Matriks harga NDI: satu baris per produk, sembilan tingkat, satu tombol terap.

**Satu sumber kebenaran.** Komponen dan hasil HJ tidak diduplikasi di sini —
semuanya ``related`` ke ``product.template`` (``custom_ndi_master``). Kalau
matriks menyimpan salinannya sendiri, cepat atau lambat master dan matriks akan
berbeda dan tidak ada cara memutuskan mana yang benar.

**Idempoten, dan itu bukan sekadar kenyamanan.** ``action_apply()`` dijalankan
dari tombol, dari cron pembaruan massal, dan dari skrip migrasi data. Kalau
setiap jalannya membuat ``product.pricelist.item`` baru alih-alih memperbarui
yang ada, tumpukan aturan akan tumbuh sampai mesin harga Odoo memilih aturan
yang salah — dan gejalanya muncul di struk pelanggan, bukan di log. Karena itu
upsert dikunci pada tuple identitas (pricelist, produk, ``applied_on``,
``min_quantity``, tanpa tanggal), dan uji idempotensi ikut dalam gerbang rilis.
"""

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.custom_ndi_master.models.ndi_waterfall import COMPONENT_KEYS

#: Identitas satu aturan harga NDI. Dua item dengan tuple ini sama adalah
#: duplikat, dan aturan Odoo yang mana yang menang tidak terdefinisi.
ITEM_IDENTITY = ("pricelist_id", "product_tmpl_id", "applied_on", "min_quantity")


class NdiPriceMatrix(models.Model):
    _name = "ndi.price.matrix"
    _description = "NDI Matriks Harga HJ1-HJ9"
    _order = "product_tmpl_id"
    _rec_name = "product_tmpl_id"

    product_tmpl_id = fields.Many2one(
        "product.template", string="Produk", required=True, ondelete="cascade", index=True
    )
    active = fields.Boolean(default=True)
    state = fields.Selection(
        [("draft", "Belum Diterapkan"), ("applied", "Diterapkan")],
        default="draft",
        required=True,
        index=True,
    )
    applied_on_date = fields.Datetime(string="Terakhir Diterapkan", readonly=True)
    applied_by_id = fields.Many2one("res.users", string="Diterapkan Oleh", readonly=True)
    item_count = fields.Integer(string="Aturan Harga Aktif", compute="_compute_item_count")
    log_ids = fields.One2many("ndi.price.matrix.log", "matrix_id", string="Riwayat Penerapan")

    # --- Komponen (baca dari master, tidak disalin) ------------------------
    hpp_dasar = fields.Float(related="product_tmpl_id.ndi_hpp_dasar", readonly=True)
    profit_pct = fields.Float(related="product_tmpl_id.ndi_profit_pct", readonly=True)
    risiko_pct = fields.Float(related="product_tmpl_id.ndi_risiko_pct", readonly=True)
    pajak_pct = fields.Float(related="product_tmpl_id.ndi_pajak_pct", readonly=True)
    ongkir_rp = fields.Float(related="product_tmpl_id.ndi_ongkir_rp", readonly=True)
    pembulatan_rp = fields.Float(related="product_tmpl_id.ndi_pembulatan_rp", readonly=True)
    insentif_kwartal_rp = fields.Float(
        related="product_tmpl_id.ndi_insentif_kwartal_rp", readonly=True
    )
    insentif_bulanan_rp = fields.Float(
        related="product_tmpl_id.ndi_insentif_bulanan_rp", readonly=True
    )
    margin_het_rp = fields.Float(related="product_tmpl_id.ndi_margin_het_rp", readonly=True)

    # --- Hasil waterfall ---------------------------------------------------
    hj1 = fields.Float(related="product_tmpl_id.ndi_hj1", readonly=True, store=True)
    hj2 = fields.Float(related="product_tmpl_id.ndi_hj2", readonly=True, store=True)
    hj3 = fields.Float(related="product_tmpl_id.ndi_hj3", readonly=True, store=True)
    hj4 = fields.Float(related="product_tmpl_id.ndi_hj4", readonly=True, store=True)
    hj5 = fields.Float(related="product_tmpl_id.ndi_hj5", readonly=True, store=True)
    hj6 = fields.Float(related="product_tmpl_id.ndi_hj6", readonly=True, store=True)
    hj7 = fields.Float(related="product_tmpl_id.ndi_hj7", readonly=True, store=True)
    hj8 = fields.Float(related="product_tmpl_id.ndi_hj8", readonly=True, store=True)
    hj9 = fields.Float(related="product_tmpl_id.ndi_hj9", readonly=True, store=True)

    _product_uniq = models.Constraint(
        "UNIQUE (product_tmpl_id)",
        "Satu produk hanya boleh punya satu baris matriks harga.",
    )

    @api.depends("product_tmpl_id")
    def _compute_item_count(self):
        levels = self.env["product.pricelist"]._ndi_pricelist_by_level()
        pricelist_ids = [pricelist.id for pricelist in levels.values()]
        if not pricelist_ids or not self.ids:
            for record in self:
                record.item_count = 0
            return
        data = self.env["product.pricelist.item"].sudo()._read_group(
            [
                ("pricelist_id", "in", pricelist_ids),
                ("product_tmpl_id", "in", self.product_tmpl_id.ids),
                ("applied_on", "=", "1_product"),
            ],
            ["product_tmpl_id"],
            ["__count"],
        )
        mapped = {template.id: count for template, count in data}
        for record in self:
            record.item_count = mapped.get(record.product_tmpl_id.id, 0)

    # === Sinkronisasi dari master =========================================

    @api.model
    def _ndi_sync_from_products(self, templates=None):
        """Pastikan setiap produk berkomponen harga punya baris matriks.

        Dipanggil dari tombol dan dari cron. Tidak pernah menghapus baris yang
        sudah ada: menghapus matriks berarti menghapus jejak penerapan harga.
        """
        if templates is None:
            templates = self.env["product.template"].search(
                ["|", ("ndi_hpp_dasar", "!=", 0.0), ("ndi_jenis_produk", "!=", False)]
            )
        existing = self.with_context(active_test=False).search(
            [("product_tmpl_id", "in", templates.ids)]
        )
        missing = templates - existing.product_tmpl_id
        created = self.create([{"product_tmpl_id": template.id} for template in missing])
        return existing | created

    # === Penerapan ke pricelist ===========================================

    def _ndi_item_values(self, pricelist, level):
        self.ensure_one()
        return {
            "pricelist_id": pricelist.id,
            "product_tmpl_id": self.product_tmpl_id.id,
            "applied_on": "1_product",
            "min_quantity": 0.0,
            "base": "list_price",
            "compute_price": "fixed",
            "fixed_price": self["hj%d" % level],
            "date_start": False,
            "date_end": False,
        }

    def action_apply(self):
        """Tulis/segarkan sembilan ``product.pricelist.item`` per produk.

        Idempoten: aturan yang sudah ada di-*update*, tidak digandakan.
        """
        if not self:
            return True
        levels = self.env["product.pricelist"]._ndi_pricelist_by_level()
        missing_levels = [level for level in range(1, 10) if level not in levels]
        if missing_levels:
            raise UserError(
                self.env._(
                    "Pricelist untuk tingkat %(levels)s belum ada. Jalankan ulang instalasi "
                    "data modul atau buat pricelist dengan Tingkat Harga NDI yang sesuai.",
                    levels=", ".join(str(level) for level in missing_levels),
                )
            )

        item_model = self.env["product.pricelist.item"].sudo()
        pricelist_ids = [pricelist.id for pricelist in levels.values()]
        existing = item_model.search(
            [
                ("pricelist_id", "in", pricelist_ids),
                ("product_tmpl_id", "in", self.product_tmpl_id.ids),
                ("applied_on", "=", "1_product"),
                ("min_quantity", "=", 0.0),
            ]
        )
        index = {
            (item.pricelist_id.id, item.product_tmpl_id.id): item for item in existing
        }

        to_create = []
        for matrix in self:
            if not matrix.product_tmpl_id:
                continue
            for level in range(1, 10):
                pricelist = levels[level]
                values = matrix._ndi_item_values(pricelist, level)
                item = index.get((pricelist.id, matrix.product_tmpl_id.id))
                if item:
                    item.write(values)
                else:
                    to_create.append(values)
        if to_create:
            created = item_model.create(to_create)
            for item in created:
                index[(item.pricelist_id.id, item.product_tmpl_id.id)] = item

        now = fields.Datetime.now()
        self.write(
            {"state": "applied", "applied_on_date": now, "applied_by_id": self.env.user.id}
        )
        self.env["ndi.price.matrix.log"].sudo().create(
            [
                {
                    "matrix_id": matrix.id,
                    "applied_on_date": now,
                    "user_id": self.env.user.id,
                    "values": matrix._ndi_snapshot_values(),
                }
                for matrix in self
            ]
        )
        return True

    def _ndi_snapshot_values(self):
        """Komponen + sembilan HJ pada detik penerapan (pasal 21, telusur harga)."""
        self.ensure_one()
        snapshot = {
            component: self.product_tmpl_id["ndi_%s" % component]
            for component in COMPONENT_KEYS
        }
        snapshot.update({"hj%d" % level: self["hj%d" % level] for level in range(1, 10)})
        snapshot["sku"] = self.product_tmpl_id.default_code or ""
        return snapshot

    def action_apply_all(self):
        """Sinkronkan matriks dari master lalu terapkan semuanya."""
        matrices = self._ndi_sync_from_products()
        matrices.action_apply()
        return True

    def action_open_items(self):
        self.ensure_one()
        levels = self.env["product.pricelist"]._ndi_pricelist_by_level()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Aturan Harga %s", self.product_tmpl_id.display_name),
            "res_model": "product.pricelist.item",
            "view_mode": "list,form",
            "domain": [
                ("pricelist_id", "in", [pricelist.id for pricelist in levels.values()]),
                ("product_tmpl_id", "=", self.product_tmpl_id.id),
            ],
        }


class NdiPriceMatrixLog(models.Model):
    _name = "ndi.price.matrix.log"
    _description = "NDI Riwayat Penerapan Matriks Harga"
    _order = "applied_on_date desc, id desc"

    matrix_id = fields.Many2one(
        "ndi.price.matrix", required=True, ondelete="cascade", index=True, string="Matriks"
    )
    product_tmpl_id = fields.Many2one(
        related="matrix_id.product_tmpl_id", store=True, index=True, string="Produk"
    )
    applied_on_date = fields.Datetime(string="Diterapkan", required=True, index=True)
    user_id = fields.Many2one("res.users", string="Oleh", required=True)
    values = fields.Json(
        string="Nilai Saat Diterapkan",
        help="Snapshot komponen dan sembilan HJ pada saat penerapan (pasal 21).",
    )
