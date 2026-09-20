# -*- coding: utf-8 -*-
"""Penyambung order diet dokter ke permintaan dapur gizi.

Permintaan ke unit gizi SUDAH ADA sebagai ``hms.unit.request`` dengan
``to_unit='nutrition'``. Bentuknya tidak diubah: ``to_unit`` dan ``type``
tetap persis seperti sebelumnya, dan permintaan gizi lama yang tidak
menyebut jenis diet tetap sah — dapur memang kadang diminta "tambah satu
porsi" tanpa perubahan diet.

Yang ditambahkan hanya dua hal: kolom ``diet_type_id`` supaya permintaan
bisa menyebut diet dari master (bukan dari teks bebas), dan satu jalan dari
perintah dokter ke tiket dapur.

SIAPA YANG MENEKAN TOMBOLNYA — DAN KENAPA BUKAN OTOMATIS
--------------------------------------------------------
``action_request_nutrition()`` dijalankan PERAWAT, bukan dipicu otomatis
saat dokter memesan. Dua alasan:

1. Yang tahu pasien sudah di bed mana, sedang puasa untuk operasi besok,
   atau baru saja muntah, adalah perawat ruangan — bukan order yang ditulis
   dari poli.
2. Membuat permintaan otomatis akan memaksa setiap dokter punya hak tulis
   ke antrian unit gizi. Perawat sudah punya hak itu karena memang
   pekerjaannya. Tidak ada ``sudo()`` di sini, dan tidak ada grup baru.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class HmsUnitRequest(models.Model):
    _inherit = "hms.unit.request"

    diet_type_id = fields.Many2one(
        "hms.diet.type", "Jenis Diet", index=True,
        help="Diet dari master gizi. Opsional: permintaan ke dapur yang tidak "
             "mengubah diet (mis. tambah porsi, ganti jam makan) tetap sah "
             "tanpa mengisi kolom ini.",
    )
    order_line_id = fields.Many2one(
        "hms.order.line", "Baris Order Diet", ondelete="set null", index=True,
        help="Order diet dokter yang melahirkan permintaan ini, bila ada.",
    )

    @api.constrains("to_unit", "diet_type_id")
    def _check_diet_type_unit(self):
        for req in self:
            if req.diet_type_id and req.to_unit != "nutrition":
                raise ValidationError(
                    _("Jenis diet hanya berlaku untuk permintaan ke unit gizi.")
                )


class HmsOrderLine(models.Model):
    _inherit = "hms.order.line"

    nutrition_request_ids = fields.One2many(
        "hms.unit.request", "order_line_id", "Permintaan Gizi",
    )

    def action_request_nutrition(self, detail=None, priority=None):
        """Teruskan order diet ke dapur gizi sebagai permintaan unit.

        Idempoten terhadap permintaan yang masih terbuka: menekan dua kali
        tidak menghasilkan dua porsi. Permintaan yang sudah selesai TIDAK
        memblokir permintaan baru, karena satu perintah diet memang
        dilaksanakan berkali-kali.
        """
        requests = self.env["hms.unit.request"]
        for line in self:
            if line.order_type != "diet":
                raise UserError(
                    _("Permintaan gizi hanya dapat dibuat dari baris order bertipe Diet / Gizi.")
                )
            if line.state == "cancelled":
                raise UserError(
                    _("Order diet '%s' sudah dibatalkan.") % line.name
                )
            admission = self.env["hms.admission"].search([
                ("encounter_id", "=", line.encounter_id.id),
            ], limit=1)
            if not admission:
                raise UserError(
                    _("Order diet '%s' tidak terhubung ke admisi rawat inap; "
                      "dapur gizi melayani permintaan per bed, bukan per kunjungan.")
                    % line.name
                )
            station = self.env["hms.nursing.station"].search([
                ("ward_id", "=", admission.ward_id.id),
            ], limit=1)
            if not station:
                raise UserError(
                    _("Ruang rawat %s belum punya nurse station; permintaan gizi "
                      "tidak punya pengirim.") % admission.ward_id.display_name
                )
            open_request = line.nutrition_request_ids.filtered(
                lambda r: r.state in ("open", "in_progress")
            )
            if open_request:
                requests |= open_request
                continue
            requests |= self.env["hms.unit.request"].create({
                "station_id": station.id,
                "admission_id": admission.id,
                "to_unit": "nutrition",
                "type": _("Diet"),
                "diet_type_id": line.diet_type_id.id,
                "order_line_id": line.id,
                "detail": detail or line.note or (
                    line.diet_type_id.display_name or line.name
                ),
                "priority": priority or "normal",
            })
        return requests
