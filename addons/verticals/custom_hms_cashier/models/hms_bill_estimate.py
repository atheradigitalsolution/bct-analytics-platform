# -*- coding: utf-8 -*-
"""Cost estimates for inpatient stays."""
import json

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HmsBillEstimate(models.Model):
    _name = "hms.bill.estimate"
    _description = "Estimasi Biaya Rawat Inap"
    _order = "id desc"

    admission_id = fields.Many2one("hms.admission", ondelete="cascade", index=True)
    encounter_id = fields.Many2one("hms.encounter", ondelete="cascade", index=True)
    patient_id = fields.Many2one("hms.patient", required=True, index=True)
    class_id = fields.Many2one("hms.care.class", "Kelas", required=True)
    expected_los = fields.Integer("Perkiraan Lama Rawat (hari)", default=3, required=True)
    currency_id = fields.Many2one(
        "res.currency", default=lambda s: s.env.company.currency_id, readonly=True,
    )
    estimate_amount = fields.Monetary("Estimasi Total", readonly=True)
    basis = fields.Text("Dasar Perhitungan", readonly=True)
    created_at = fields.Datetime(default=fields.Datetime.now, readonly=True)
    created_by_id = fields.Many2one("res.users", default=lambda s: s.env.user, readonly=True)

    @api.model
    def estimate(self, patient, care_class, expected_los=3, payer=None, encounter=None):
        """Price a hypothetical stay from the tariff table.

        Only the predictable components are included — room, daily nursing,
        visits and admission fee. Procedures and drugs are deliberately left
        out and said so in the basis, because quoting a number that pretends
        to cover them is how families end up feeling misled at discharge.
        """
        Tariff = self.env["hms.tariff"]
        lines = []
        total = 0.0
        today = fields.Date.context_today(self)

        def price_of(category_ref, label, qty):
            nonlocal total
            category = self.env.ref(category_ref, raise_if_not_found=False)
            if not category:
                return
            tariff = Tariff.search([("category_id", "=", category.id)], limit=1)
            if not tariff:
                return
            try:
                price = tariff.resolve_price(
                    class_id=care_class.id, payer_id=payer.id if payer else None, date=today,
                )
            except Exception:  # noqa: BLE001 — an unpriced item is simply skipped
                lines.append({"label": label, "qty": qty, "amount": 0.0,
                              "note": _("tarif belum ditetapkan")})
                return
            amount = price.price_total * qty
            total += amount
            lines.append({"label": label, "qty": qty, "amount": amount})

        price_of("custom_hms_base.tariff_cat_room", _("Akomodasi kamar"), expected_los)
        price_of("custom_hms_base.tariff_cat_nursing", _("Asuhan keperawatan"), expected_los)
        price_of("custom_hms_base.tariff_cat_consult", _("Visite dokter"), expected_los)
        price_of("custom_hms_base.tariff_cat_admin", _("Administrasi"), 1)

        basis = {
            "lines": lines,
            "excluded": [
                _("Tindakan medis"), _("Obat dan BHP"), _("Laboratorium"), _("Radiologi"),
            ],
            "note": _(
                "Estimasi mencakup komponen yang dapat diperkirakan di muka. Tindakan, "
                "obat dan pemeriksaan penunjang bergantung pada perkembangan kondisi "
                "pasien dan tidak termasuk dalam angka ini."
            ),
        }
        return self.create({
            "admission_id": encounter and self.env["hms.admission"].search(
                [("encounter_id", "=", encounter.id)], limit=1
            ).id or False,
            "encounter_id": encounter.id if encounter else False,
            "patient_id": patient.id,
            "class_id": care_class.id,
            "expected_los": expected_los,
            "estimate_amount": total,
            "basis": json.dumps(basis, default=str, ensure_ascii=False),
        })
