# -*- coding: utf-8 -*-
"""SLA kontraktual 3PL, dan pengukurannya.

Kontrak 3PL hampir selalu memuat SLA dengan penalti. Angkanya harus terukur DARI
SISTEM, karena itulah yang dibawa ke rapat bulanan dengan pemilik barang — dan
angka yang dihitung ulang di spreadsheet setiap bulan adalah angka yang
diperdebatkan setiap bulan.
"""
from odoo import _, api, fields, models


class LgxWmsSla(models.Model):
    _name = "lgx.wms.sla"
    _description = "SLA Gudang"
    _order = "name"

    name = fields.Char("Nama", required=True)
    company_id = fields.Many2one("res.company", "Perusahaan", required=True,
                                 default=lambda s: s.env.company, index=True)
    receiving_hours = fields.Float("Batas Waktu Penerimaan (jam)",
                                   help="Dari kedatangan sampai barang tercatat di sistem.")
    putaway_hours = fields.Float("Batas Waktu Putaway (jam)")
    order_cutoff_time = fields.Float("Batas Waktu Order (jam ke-)",
                                     help="Order yang masuk sebelum jam ini dikirim hari yang sama.")
    dispatch_same_day = fields.Boolean("Kirim Hari yang Sama", default=True)
    inventory_accuracy_target = fields.Float("Target Akurasi Stok (%)", default=99.5)
    order_accuracy_target = fields.Float("Target Akurasi Order (%)", default=99.0)
    on_time_delivery_target = fields.Float("Target Ketepatan Kirim (%)", default=95.0)
    penalty_note = fields.Text("Aturan Penalti")
    active = fields.Boolean(default=True)


class LgxWmsSlaMeasurement(models.Model):
    _name = "lgx.wms.sla.measurement"
    _description = "Pengukuran SLA Gudang"
    _order = "date desc, client_id"

    client_id = fields.Many2one("lgx.wms.client", "Klien", required=True, index=True,
                                ondelete="cascade")
    sla_id = fields.Many2one("lgx.wms.sla", "SLA", related="client_id.sla_id", store=True)
    company_id = fields.Many2one(related="client_id.company_id", store=True, index=True)
    date = fields.Date("Periode", required=True, index=True)
    receiving_ontime_pct = fields.Float("Penerimaan Tepat Waktu (%)")
    dispatch_ontime_pct = fields.Float("Pengiriman Tepat Waktu (%)")
    inventory_accuracy_pct = fields.Float("Akurasi Stok (%)")
    order_accuracy_pct = fields.Float("Akurasi Order (%)")
    breach_count = fields.Integer("Jumlah Pelanggaran", compute="_compute_breach", store=True)
    breach_summary = fields.Char("Ringkasan Pelanggaran", compute="_compute_breach", store=True)
    note = fields.Text("Catatan")

    # Keempatnya rasio dari hitungan: berapa yang tepat waktu dibagi berapa
    # seluruhnya. Angka di luar 0-100 bukan kinerja yang luar biasa, melainkan
    # salah ketik — dan pengukuran SLA yang salah menggeser tagihan penalti.
    _pct_in_range = models.Constraint(
        "check(receiving_ontime_pct between 0 and 100 "
        "and dispatch_ontime_pct between 0 and 100 "
        "and inventory_accuracy_pct between 0 and 100 "
        "and order_accuracy_pct between 0 and 100)",
        "Persentase pengukuran SLA harus antara 0 dan 100.",
    )
    _client_period_uniq = models.Constraint(
        "unique(client_id, date)", "Pengukuran SLA untuk klien dan periode ini sudah ada.",
    )

    @api.depends("receiving_ontime_pct", "dispatch_ontime_pct", "inventory_accuracy_pct",
                 "order_accuracy_pct", "sla_id")
    def _compute_breach(self):
        for measurement in self:
            sla = measurement.sla_id
            breaches = []
            if sla:
                checks = [
                    (measurement.dispatch_ontime_pct, sla.on_time_delivery_target, _("ketepatan kirim")),
                    (measurement.inventory_accuracy_pct, sla.inventory_accuracy_target, _("akurasi stok")),
                    (measurement.order_accuracy_pct, sla.order_accuracy_target, _("akurasi order")),
                ]
                for actual, target, label in checks:
                    if target and actual and actual < target:
                        breaches.append(_("%s %.2f%% < target %.2f%%", label, actual, target))
            measurement.breach_count = len(breaches)
            measurement.breach_summary = "; ".join(breaches) or False
