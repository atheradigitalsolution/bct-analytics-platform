# -*- coding: utf-8 -*-
"""Simpul jaringan logistik: pelabuhan, bandara, terminal, depo, gudang, kota.

Satu model untuk semuanya, bukan satu model per jenis. Alasannya praktis: rute
sebuah job kerap menyeberang jenis simpul (pabrik -> depo -> pelabuhan -> kota
tujuan), dan Many2one ke satu model adalah satu-satunya bentuk yang membuat
rute itu bisa dinyatakan tanpa lima field opsional.

Kode memakai UN/LOCODE lima huruf (IDJKT, SGSIN) untuk simpul yang punya, dan
kode internal untuk yang tidak. Keunikan ditegakkan di Postgres, bukan hanya di
Python: lihat catatan `models.Constraint` di MODULE_KNOWLEDGE.md.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class LgxCustomsOffice(models.Model):
    _name = "lgx.customs.office"
    _description = "Kantor Pabean"
    _order = "code"

    code = fields.Char("Kode", required=True, index=True, help="Kode kantor pabean Bea Cukai, mis. 040300.")
    name = fields.Char("Nama", required=True)
    office_type = fields.Selection(
        [("kpu", "Kantor Pelayanan Utama"), ("kppbc", "KPPBC"), ("kanwil", "Kantor Wilayah")],
        string="Jenis", default="kppbc",
    )
    city = fields.Char("Kota")
    state_id = fields.Many2one("res.country.state", "Provinsi")
    partner_id = fields.Many2one(
        "res.partner", "Partner Penerima Pembayaran",
        help="Pihak yang menerima pembayaran bea masuk dan pungutan lain untuk "
             "kantor ini. Dipakai sebagai vendor pada baris talangan deklarasi — "
             "talangan tanpa pihak adalah utang yang tidak bisa direkonsiliasi.",
    )
    ceisa_mandatory = fields.Boolean(
        "CEISA 4.0 Wajib", default=False,
        help="CEISA 4.0 diwajibkan bertahap per kantor. Kantor yang belum wajib "
             "tidak dikirimi dokumen otomatis; dokumen dikerjakan lewat mode manual.",
    )
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint("unique(code)", "Kode kantor pabean harus unik.")

    @api.depends("code", "name")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"[{rec.code}] {rec.name}" if rec.code else rec.name


class LgxLocation(models.Model):
    _name = "lgx.location"
    _description = "Simpul Jaringan Logistik"
    _order = "country_id, code"
    _inherit = ["mail.thread"]

    code = fields.Char("Kode", required=True, index=True, help="UN/LOCODE bila ada, mis. IDJKT.")
    name = fields.Char("Nama", required=True)
    location_type = fields.Selection(
        [
            ("seaport", "Pelabuhan Laut"),
            ("airport", "Bandara"),
            ("terminal", "Terminal Peti Kemas"),
            ("depot", "Depo Kontainer"),
            ("cfs", "CFS / Gudang Konsolidasi"),
            ("warehouse", "Gudang"),
            ("city", "Kota / Titik Darat"),
            ("border", "Pos Lintas Batas"),
        ],
        string="Jenis", required=True, default="seaport",
    )
    country_id = fields.Many2one("res.country", "Negara", required=True)
    state_id = fields.Many2one("res.country.state", "Provinsi", domain="[('country_id','=',country_id)]")
    city = fields.Char("Kota")
    partner_id = fields.Many2one("res.partner", "Operator/Pengelola")
    customs_office_id = fields.Many2one("lgx.customs.office", "Kantor Pabean")
    latitude = fields.Float("Lintang", digits=(10, 6))
    longitude = fields.Float("Bujur", digits=(10, 6))
    is_domestic = fields.Boolean("Dalam Negeri", compute="_compute_is_domestic", store=True)
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint("unique(code)", "Kode simpul (UN/LOCODE) harus unik.")

    @api.depends("country_id")
    def _compute_is_domestic(self):
        indonesia = self.env.ref("base.id", raise_if_not_found=False)
        for rec in self:
            rec.is_domestic = bool(indonesia) and rec.country_id == indonesia

    @api.constrains("code")
    def _check_code(self):
        """Huruf, angka, dan tanda hubung.

        UN/LOCODE sendiri selalu lima huruf tanpa tanda baca, tetapi simpul yang
        tidak punya LOCODE — depo, CFS, gudang, pool — diberi kode turunan
        seperti ``IDJKT-D1``. Melarang tanda hubung berarti memaksa kode internal
        menjadi rangkaian huruf yang tidak terbaca, dan itu yang akan salah
        diketik orang.
        """
        for rec in self:
            if not rec.code:
                continue
            if not all(ch.isalnum() or ch == "-" for ch in rec.code):
                raise ValidationError(_(
                    "Kode simpul hanya boleh huruf, angka, dan tanda hubung: %s", rec.code,
                ))

    @api.depends("code", "name")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"{rec.code} — {rec.name}" if rec.code else rec.name
