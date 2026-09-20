# -*- coding: utf-8 -*-
"""Trip haulage yang mengangkut kontainer forwarding.

Tanggal keluar dan masuk gerbang adalah dasar perhitungan DETENSI, dan yang
benar-benar mengetahuinya adalah trip — pengemudilah yang keluar terminal dan
mengembalikan kontainer ke depo. Menyalinnya dengan tangan ke kartu kontainer
berarti dua angka yang harus dijaga tetap sama, dan angka yang harus dijaga
tetap sama adalah angka yang suatu saat berbeda.
"""
from odoo import _, api, fields, models


class LgxTrip(models.Model):
    _inherit = "lgx.trip"

    container_id = fields.Many2one(
        "lgx.container", "Kontainer (Forwarding)", index=True,
        help="Menautkan trip haulage ke kontainer yang dilacak forwarding.",
    )

    @api.onchange("container_id")
    def _onchange_container_id(self):
        for trip in self:
            if trip.container_id:
                trip.container_no = trip.container_id.container_no
                trip.container_type_id = trip.container_id.container_type_id
                if not trip.job_id:
                    trip.job_id = trip.container_id.job_id

    def action_dispatch(self):
        """Berangkat dari terminal = kontainer keluar gerbang."""
        result = super().action_dispatch()
        for trip in self.filtered(lambda t: t.container_id and not t.container_id.gate_out_date):
            if trip.trip_type == "container_haulage":
                trip.container_id.gate_out_date = fields.Date.context_today(trip)
                trip.message_post(body=_(
                    "Tanggal keluar terminal kontainer %s diisi dari keberangkatan trip. "
                    "Detensi mulai dihitung dari sini.", trip.container_id.container_no,
                ))
        return result

    def action_settle(self):
        """Trip pengembalian kontainer = kontainer masuk depo."""
        result = super().action_settle()
        for trip in self.filtered(lambda t: t.container_id and not t.container_id.gate_in_date):
            if trip.trip_type == "container_haulage" and trip.actual_end:
                trip.container_id.gate_in_date = fields.Date.to_date(trip.actual_end)
                trip.message_post(body=_(
                    "Tanggal pengembalian kontainer %s diisi dari penyelesaian trip. "
                    "Detensi berhenti berjalan.", trip.container_id.container_no,
                ))
        return result
