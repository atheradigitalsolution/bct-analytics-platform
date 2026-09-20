# -*- coding: utf-8 -*-
"""Wires every clinical event that produces money into the bill.

Each hook was declared upstream so the clinical modules stay installable
without billing. This file is the single place where "what was done" becomes
"what is owed".

**Why sudo() appears here.** The clinical act is authorised by the user's own
rights: an analyst may verify a result, a pharmacist may dispense. The billing
entry that follows is the system's bookkeeping, not an action the clinician is
performing — and giving every clinical role write access to bills so the
side-effect can go through would be a far larger grant than the work requires.
The decision stays gated by the clinical permission; only the ledger write is
elevated.
"""
from odoo import _, fields, models
from odoo.exceptions import UserError


class HmsOrderLine(models.Model):
    _inherit = "hms.order.line"

    charge_id = fields.Many2one("hms.bill.line", "Baris Tagihan", readonly=True, copy=False)

    def _create_charge(self):
        """Turn a completed (or ordered) service into a bill line."""
        for line in self:
            if line.charge_id and line.charge_id.state != "cancelled":
                continue
            bill = self.env["hms.bill"].sudo().get_or_create_for(line.encounter_id)
            if bill.state == "closed":
                raise UserError(
                    _("Tagihan %(b)s sudah ditutup; layanan '%(l)s' tidak dapat dibebankan. "
                      "Buka kunjungan baru atau batalkan penutupan lewat Akuntansi.")
                    % {"b": bill.name, "l": line.name}
                )
            charge = self.env["hms.bill.line"].sudo().charge(
                bill,
                line.tariff_id,
                qty=line.qty,
                source=line,
                unit=line.unit_id,
                practitioner=line.performed_by_id or line.order_id.practitioner_id,
                service_date=fields.Date.context_today(line),
                name=line.name,
                cito=line.order_id.priority == "cito",
            )
            line.sudo().write({
                "charge_id": charge.id,
                "unit_price": charge.unit_price,
                "price_subtotal": charge.price_subtotal,
            })
        return True

    def _reverse_charge(self):
        for line in self.filtered("charge_id"):
            line.charge_id.sudo().action_cancel_line(reason=_("Order dibatalkan"))
        return True


class HmsDailyCharge(models.Model):
    _inherit = "hms.daily.charge"

    bill_line_id = fields.Many2one("hms.bill.line", "Baris Tagihan", readonly=True, copy=False)

    def _post_charge(self):
        for charge in self:
            if charge.bill_line_id:
                continue
            bill = self.env["hms.bill"].sudo().get_or_create_for(
                charge.admission_id.encounter_id
            )
            if bill.state == "closed":
                continue
            line = self.env["hms.bill.line"].sudo().charge(
                bill,
                charge.tariff_id,
                qty=charge.qty,
                source=charge,
                practitioner=charge.practitioner_id,
                service_date=charge.charge_date,
                # The billed class, not the bed class — see hms_inpatient.
                class_override=charge.class_id,
                name=_("%(t)s — %(d)s") % {
                    "t": charge.tariff_id.name,
                    "d": fields.Date.to_string(charge.charge_date),
                },
            )
            charge.sudo().write({"bill_line_id": line.id})
        return True


class HmsPrescription(models.Model):
    _inherit = "hms.prescription"

    bill_line_ids = fields.One2many("hms.bill.line", "prescription_id", "Baris Tagihan")

    def action_dispense(self):
        """Charge the medicine at the moment it physically leaves the depot.

        Charging at prescribing time would bill drugs the pharmacy later
        substituted or the patient never collected.
        """
        res = super().action_dispense()
        for rx in self:
            rx._charge_dispensed_lines()
        return res

    def _charge_dispensed_lines(self):
        self.ensure_one()
        bill = self.env["hms.bill"].sudo().get_or_create_for(self.encounter_id)
        if bill.state == "closed":
            raise UserError(
                _("Tagihan %s sudah ditutup; obat tidak dapat dibebankan.") % bill.name
            )
        BillLine = self.env["hms.bill.line"].sudo()
        placeholder = None
        for line in self.line_ids.filtered(lambda l: l.state == "dispensed" and l.qty_dispense > 0):
            tariff = line.medicine_id.tariff_id
            if tariff:
                charge = BillLine.charge(
                    bill, tariff, qty=line.qty_dispense, source=line,
                    unit=self.depot_id.unit_id, name=line.medicine_id.display_name,
                )
            else:
                # Medicines are usually priced from the product, not from a
                # tariff item. A single shared placeholder tariff carries the
                # category so the bill detail and the unit P&L still group
                # correctly, without duplicating every drug into the tariff
                # master.
                if placeholder is None:
                    placeholder = self._medicine_placeholder_tariff()
                unit_price = line.product_id.list_price
                coverage, reason = BillLine._resolve_coverage(self.encounter_id, placeholder)
                charge = BillLine.create({
                    "bill_id": bill.id,
                    "tariff_id": placeholder.id,
                    "name": line.medicine_id.display_name,
                    "qty": line.qty_dispense,
                    "unit_id": (self.depot_id.unit_id or self.encounter_id.unit_id).id,
                    "service_date": fields.Date.context_today(self),
                    "unit_price": unit_price,
                    "amount_consumable": unit_price * line.qty_dispense,
                    "source_model": line._name,
                    "source_id": line.id,
                    "coverage_percent": coverage,
                    "coverage_note": reason,
                })
            charge.write({"prescription_id": self.id})
        return True

    def _medicine_placeholder_tariff(self):
        """One shared tariff row that carries the medicine category."""
        tariff = self.env["hms.tariff"].search([("code", "=", "OBAT-GEN")], limit=1)
        if tariff:
            return tariff
        category = self.env.ref("custom_hms_base.tariff_cat_medicine")
        return self.env["hms.tariff"].sudo().create({
            "code": "OBAT-GEN",
            "name": _("Obat & BHP (harga produk)"),
            "category_id": category.id,
            "description": _(
                "Baris tarif teknis. Harga obat berasal dari master produk, bukan dari "
                "tabel tarif; baris ini hanya membawa kategori agar rincian tagihan dan "
                "P&L unit tetap terkelompok benar."
            ),
        })


class HmsMedicine(models.Model):
    _inherit = "hms.medicine"

    tariff_id = fields.Many2one(
        "hms.tariff", "Item Tarif",
        help="Kosongkan agar harga diambil dari master produk (kasus umum). "
             "Isi hanya bila obat ini punya tarif tersendiri per kelas/penjamin.",
    )


class HmsBillLine(models.Model):
    _inherit = "hms.bill.line"

    prescription_id = fields.Many2one("hms.prescription", "Resep", index=True)
