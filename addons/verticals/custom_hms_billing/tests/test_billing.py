# -*- coding: utf-8 -*-
"""Charging, payer split, deposits, payments and the accounting handoff."""
from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "hms")
class BillingCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.clinic = cls.env["hms.unit"].create({
            "code": "ZT-POLI-BIL", "name": "Poli Uji Billing", "type": "outpatient_clinic",
        })
        cls.lab_unit = cls.env["hms.unit"].create({
            "code": "ZT-LAB-BIL", "name": "Laboratorium", "type": "lab",
        })
        cls.doctor = cls.env["hms.practitioner"].create({
            "name": "Ratna Dewi", "title_prefix": "dr.", "type": "doctor",
            "nik": "3201014501840001", "user_id": cls.env.user.id,
        })
        cls.class_2 = cls.env.ref("custom_hms_base.care_class_2")
        cls.payer_self = cls.env.ref("custom_hms_base.payer_self")

        cls.bpjs_partner = cls.env["res.partner"].create({"name": "BPJS Kesehatan"})
        cls.payer_bpjs = cls.env["hms.payer"].create({
            "code": "ZT-BPJS-B", "name": "BPJS Kesehatan", "type": "bpjs",
            "partner_id": cls.bpjs_partner.id, "requires_sep": True,
        })
        cls.plan_bpjs = cls.env["hms.payer.plan"].create({
            "payer_id": cls.payer_bpjs.id, "code": "ZT-PBI", "name": "PBI Kelas 3",
            "coverage_percent": 100.0, "class_id": cls.class_2.id,
        })

        cls.cat_procedure = cls.env.ref("custom_hms_base.tariff_cat_procedure")
        cls.cat_lab = cls.env.ref("custom_hms_base.tariff_cat_lab")
        cls.tariff_proc = cls.env["hms.tariff"].create({
            "code": "ZT-TND-BIL", "name": "Hecting Sederhana",
            "category_id": cls.cat_procedure.id, "unit_id": cls.clinic.id,
            "price_ids": [(0, 0, {
                "price_total": 200000, "amount_facility": 120000, "amount_medical": 60000,
                "amount_consumable": 20000,
            })],
        })
        cls.tariff_lab = cls.env["hms.tariff"].create({
            "code": "ZT-LAB-BIL1", "name": "Darah Lengkap",
            "category_id": cls.cat_lab.id, "unit_id": cls.lab_unit.id,
            "price_ids": [(0, 0, {"price_total": 100000})],
        })

    def _patient(self, name="Pasien Billing"):
        existing = self.env["hms.patient"].search_count([])
        return self.env["hms.patient"].create({
            "name": name, "gender": "male", "birth_date": "1980-01-01",
            "nik": f"32019901010{existing + 100:05d}",
        })

    def _encounter(self, payer=None, plan=None, sep=None, patient=None):
        encounter = self.env["hms.encounter"].create({
            "patient_id": (patient or self._patient()).id,
            "unit_id": self.clinic.id,
            "payer_id": (payer or self.payer_self).id,
            "payer_plan_id": plan.id if plan else False,
            "practitioner_id": self.doctor.id,
        })
        if sep:
            encounter.sudo().write({"sep_no": sep, "sep_state": "issued"})
        return encounter

    def _order_done(self, encounter, tariff=None, qty=1.0):
        order = self.env["hms.order"].create({
            "encounter_id": encounter.id, "order_type": "procedure",
            "practitioner_id": self.doctor.id,
            "line_ids": [(0, 0, {"tariff_id": (tariff or self.tariff_proc).id, "qty": qty})],
        })
        order.action_submit()
        order.line_ids.action_done()
        return order


@tagged("post_install", "-at_install", "hms")
class TestCharging(BillingCase):
    def test_completing_an_order_creates_a_bill_and_a_line(self):
        encounter = self._encounter()
        self._order_done(encounter)
        bill = self.env["hms.bill"].search([("encounter_id", "=", encounter.id)])
        self.assertEqual(len(bill), 1)
        self.assertEqual(len(bill.line_ids), 1)
        self.assertAlmostEqual(bill.amount_total, 200000)

    def test_one_bill_per_encounter_even_with_many_orders(self):
        encounter = self._encounter()
        self._order_done(encounter)
        self._order_done(encounter, tariff=self.tariff_lab)
        bills = self.env["hms.bill"].search([("encounter_id", "=", encounter.id)])
        self.assertEqual(len(bills), 1)
        self.assertEqual(len(bills.line_ids), 2)

    def test_bill_line_freezes_the_service_component_split(self):
        encounter = self._encounter()
        self._order_done(encounter)
        line = self.env["hms.bill"].search([("encounter_id", "=", encounter.id)]).line_ids
        self.assertAlmostEqual(line.amount_medical, 60000)
        self.assertAlmostEqual(line.amount_facility, 120000)
        # Later tariff revisions must not reach back into a raised charge.
        self.tariff_proc.price_ids.write({"price_total": 500000, "amount_facility": 500000,
                                          "amount_medical": 0, "amount_consumable": 0})
        line.invalidate_recordset()
        self.assertAlmostEqual(line.amount_medical, 60000)
        self.assertAlmostEqual(line.unit_price, 200000)

    def test_cancelling_an_order_line_voids_its_charge(self):
        encounter = self._encounter()
        order = self.env["hms.order"].create({
            "encounter_id": encounter.id, "order_type": "procedure",
            "practitioner_id": self.doctor.id,
            "line_ids": [(0, 0, {"tariff_id": self.tariff_proc.id})],
        })
        order.action_submit()
        order.line_ids._create_charge()
        order.line_ids.action_cancel()
        bill = self.env["hms.bill"].search([("encounter_id", "=", encounter.id)])
        self.assertEqual(bill.line_ids.state, "cancelled")
        self.assertAlmostEqual(bill.amount_total, 0.0)

    def test_charge_is_refused_once_the_bill_is_closed(self):
        encounter = self._encounter()
        self._order_done(encounter)
        bill = self.env["hms.bill"].search([("encounter_id", "=", encounter.id)])
        bill.action_open()
        bill.action_close()
        with self.assertRaises(UserError):
            self._order_done(encounter, tariff=self.tariff_lab)

    def test_lab_charge_is_credited_to_the_lab_not_the_ordering_clinic(self):
        encounter = self._encounter()
        self._order_done(encounter, tariff=self.tariff_lab)
        line = self.env["hms.bill"].search([("encounter_id", "=", encounter.id)]).line_ids
        self.assertEqual(line.unit_id, self.lab_unit)


@tagged("post_install", "-at_install", "hms")
class TestPayerSplit(BillingCase):
    def test_self_pay_patient_owes_everything(self):
        encounter = self._encounter()
        self._order_done(encounter)
        bill = self.env["hms.bill"].search([("encounter_id", "=", encounter.id)])
        self.assertAlmostEqual(bill.amount_payer, 0.0)
        self.assertAlmostEqual(bill.amount_patient, 200000)

    def test_full_cover_plan_moves_everything_to_the_payer(self):
        encounter = self._encounter(self.payer_bpjs, self.plan_bpjs, sep="SEP001")
        self._order_done(encounter)
        bill = self.env["hms.bill"].search([("encounter_id", "=", encounter.id)])
        self.assertAlmostEqual(bill.amount_payer, 200000)
        self.assertAlmostEqual(bill.amount_patient, 0.0)

    def test_partial_cover_splits_the_line(self):
        self.plan_bpjs.coverage_percent = 80.0
        encounter = self._encounter(self.payer_bpjs, self.plan_bpjs, sep="SEP002")
        self._order_done(encounter)
        bill = self.env["hms.bill"].search([("encounter_id", "=", encounter.id)])
        self.assertAlmostEqual(bill.amount_payer, 160000)
        self.assertAlmostEqual(bill.amount_patient, 40000)

    def test_excluded_category_falls_entirely_to_the_patient(self):
        self.plan_bpjs.excluded_category_ids = [(4, self.cat_lab.id)]
        encounter = self._encounter(self.payer_bpjs, self.plan_bpjs, sep="SEP003")
        self._order_done(encounter, tariff=self.tariff_lab)
        line = self.env["hms.bill"].search([("encounter_id", "=", encounter.id)]).line_ids
        self.assertAlmostEqual(line.amount_patient, 100000)
        self.assertIn("dikecualikan", line.coverage_note)

    def test_missing_sep_stops_the_payer_being_billed(self):
        """No SEP means no claim — charging the payer anyway guarantees rejection."""
        encounter = self._encounter(self.payer_bpjs, self.plan_bpjs)
        self._order_done(encounter)
        bill = self.env["hms.bill"].search([("encounter_id", "=", encounter.id)])
        self.assertAlmostEqual(bill.amount_payer, 0.0)
        self.assertIn("SEP", bill.line_ids.coverage_note)

    def test_payer_without_a_plan_covers_nothing(self):
        encounter = self._encounter(self.payer_bpjs, sep="SEP004")
        self._order_done(encounter)
        bill = self.env["hms.bill"].search([("encounter_id", "=", encounter.id)])
        self.assertAlmostEqual(bill.amount_payer, 0.0)


@tagged("post_install", "-at_install", "hms")
class TestPaymentAndAccounting(BillingCase):
    def _open_bill(self, **kw):
        encounter = self._encounter(**kw)
        self._order_done(encounter)
        bill = self.env["hms.bill"].search([("encounter_id", "=", encounter.id)])
        bill.action_open()
        return bill

    def test_closing_creates_a_posted_balanced_invoice(self):
        bill = self._open_bill()
        bill.action_close()
        self.assertEqual(bill.state, "closed")
        self.assertEqual(len(bill.move_ids), 1)
        move = bill.move_ids
        self.assertEqual(move.state, "posted")
        self.assertEqual(move.partner_id, bill.patient_id.partner_id)
        self.assertAlmostEqual(move.amount_total, 200000)
        self.assertAlmostEqual(sum(move.line_ids.mapped("balance")), 0.0,
                               msg="Jurnal harus seimbang.")

    def test_split_bill_produces_two_invoices_to_two_partners(self):
        self.plan_bpjs.coverage_percent = 70.0
        bill = self._open_bill(payer=self.payer_bpjs, plan=self.plan_bpjs, sep="SEP010")
        bill.action_close()
        self.assertEqual(len(bill.move_ids), 2)
        partners = bill.move_ids.mapped("partner_id")
        self.assertIn(self.bpjs_partner, partners)
        self.assertIn(bill.patient_id.partner_id, partners)
        payer_move = bill.move_ids.filtered(lambda m: m.partner_id == self.bpjs_partner)
        self.assertAlmostEqual(payer_move.amount_total, 140000)

    def test_cash_payment_settles_the_bill(self):
        bill = self._open_bill()
        journal = self.env["account.journal"].search([("type", "=", "cash")], limit=1)
        wizard = self.env["hms.payment.wizard"].with_context(
            hms_back_office=True
        ).create({
            "bill_id": bill.id, "use_deposit": False,
            "line_ids": [(0, 0, {
                "method": "cash", "amount": 200000, "tendered": 200000,
                "journal_id": journal.id,
            })],
        })
        wizard.action_confirm()
        self.assertAlmostEqual(bill.amount_paid, 200000)
        self.assertAlmostEqual(bill.amount_due, 0.0)
        self.assertEqual(bill.state, "paid")

    def test_split_tender_across_three_methods(self):
        bill = self._open_bill()
        cash = self.env["account.journal"].search([("type", "=", "cash")], limit=1)
        bank = self.env["account.journal"].search([("type", "=", "bank")], limit=1)
        wizard = self.env["hms.payment.wizard"].with_context(
            hms_back_office=True
        ).create({
            "bill_id": bill.id, "use_deposit": False,
            "line_ids": [
                (0, 0, {"method": "cash", "amount": 50000, "journal_id": cash.id}),
                (0, 0, {"method": "edc_debit", "amount": 100000, "journal_id": bank.id,
                        "approval_code": "123456"}),
                (0, 0, {"method": "transfer", "amount": 50000, "journal_id": bank.id,
                        "reference": "TRF-99"}),
            ],
        })
        wizard.action_confirm()
        self.assertEqual(len(bill.payment_ids), 3)
        self.assertAlmostEqual(bill.amount_due, 0.0)

    def test_deposit_is_consumed_before_cash(self):
        bill = self._open_bill()
        self.env["hms.deposit"].create({
            "patient_id": bill.patient_id.id, "amount": 150000, "method": "cash",
        })
        wizard = self.env["hms.payment.wizard"].with_context(
            hms_back_office=True
        ).create({
            "bill_id": bill.id, "use_deposit": True,
        })
        wizard.action_confirm()
        self.assertAlmostEqual(bill.amount_deposit, 150000)
        self.assertAlmostEqual(bill.amount_due, 50000)

    def test_deposit_refund_returns_the_balance(self):
        deposit = self.env["hms.deposit"].create({
            "patient_id": self._patient().id, "amount": 300000, "method": "cash",
        })
        deposit.action_refund()
        self.assertEqual(deposit.state, "refunded")
        self.assertAlmostEqual(deposit.balance, 0.0)
        self.assertAlmostEqual(deposit.refunded_amount, 300000)

    def test_voiding_a_payment_requires_a_reason(self):
        bill = self._open_bill()
        journal = self.env["account.journal"].search([("type", "=", "cash")], limit=1)
        payment = self.env["hms.payment"].with_context(hms_back_office=True).create({
            "bill_id": bill.id, "method": "cash", "amount": 100000, "journal_id": journal.id,
        })
        with self.assertRaises(UserError):
            payment.action_void()

    def test_closed_bill_lines_are_immutable(self):
        bill = self._open_bill()
        bill.action_close()
        with self.assertRaises(UserError):
            bill.line_ids.write({"qty": 5})

    def test_closed_bill_cannot_be_reopened(self):
        bill = self._open_bill()
        bill.action_close()
        with self.assertRaises(UserError):
            bill.action_reopen()


@tagged("post_install", "-at_install", "hms")
class TestDiscountAuthorisation(BillingCase):
    def test_small_discount_applies_directly(self):
        encounter = self._encounter()
        self._order_done(encounter)
        bill = self.env["hms.bill"].search([("encounter_id", "=", encounter.id)])
        bill.apply_discount(5.0, "Pembulatan")
        self.assertAlmostEqual(bill.amount_discount, 10000)

    def test_large_discount_is_refused_without_approval(self):
        encounter = self._encounter()
        self._order_done(encounter)
        bill = self.env["hms.bill"].search([("encounter_id", "=", encounter.id)])
        self.assertTrue(bill.discount_needs_authorization(50.0))
        with self.assertRaises(UserError):
            bill.apply_discount(50.0, "Permintaan keluarga")
        self.assertAlmostEqual(bill.amount_discount, 0.0)

    def test_authorization_request_survives_because_nothing_raises(self):
        """The request is its own call; a refusal would roll it back."""
        encounter = self._encounter()
        self._order_done(encounter)
        bill = self.env["hms.bill"].search([("encounter_id", "=", encounter.id)])
        request = bill.request_discount_authorization(50.0, "Permintaan keluarga")
        self.assertEqual(request.state, "pending")
        self.assertEqual(
            self.env["hms.billing.authorization"].search_count([("bill_id", "=", bill.id)]), 1
        )

    def test_approved_authorization_lets_the_discount_through(self):
        encounter = self._encounter()
        self._order_done(encounter)
        bill = self.env["hms.bill"].search([("encounter_id", "=", encounter.id)])
        request = bill.request_discount_authorization(50.0, "Permintaan keluarga")
        supervisor = self.env["res.users"].create({
            "name": "Supervisor Kasir", "login": "sup.kasir.test",
            "group_ids": [(4, self.env.ref("custom_hms_base.group_hms_billing_supervisor").id)],
        })
        request.with_user(supervisor).action_approve()
        bill.apply_discount(50.0, "Permintaan keluarga")
        self.assertAlmostEqual(bill.amount_discount, 100000)

    def test_self_approval_is_refused(self):
        encounter = self._encounter()
        self._order_done(encounter)
        bill = self.env["hms.bill"].search([("encounter_id", "=", encounter.id)])
        auth = self.env["hms.billing.authorization"].create({
            "bill_id": bill.id, "action": "discount", "percent": 50.0,
            "reason": "uji", "requested_by_id": self.env.uid,
        })
        # Odoo 19 renamed res.users.groups_id to group_ids.
        self.env.user.group_ids = [(4, self.env.ref(
            "custom_hms_base.group_hms_billing_supervisor").id)]
        with self.assertRaises(UserError):
            auth.action_approve()


@tagged("post_install", "-at_install", "hms")
class TestUnpricedService(BillingCase):
    """A service with no tariff price must not stop the clinical flow, and must
    stop the money flow."""

    def _unpriced_tariff(self):
        return self.env["hms.tariff"].create({
            "code": "ZT-TND-NOPRICE", "name": "Tindakan Belum Bertarif",
            "category_id": self.cat_procedure.id, "unit_id": self.clinic.id,
        })

    def test_completing_an_unpriced_service_still_succeeds(self):
        encounter = self._encounter()
        order = self._order_done(encounter, tariff=self._unpriced_tariff())
        self.assertEqual(order.line_ids.state, "done")

    def test_unpriced_service_lands_on_the_bill_flagged_and_at_zero(self):
        encounter = self._encounter()
        self._order_done(encounter, tariff=self._unpriced_tariff())
        bill = self.env["hms.bill"].search([("encounter_id", "=", encounter.id)])
        line = bill.line_ids
        self.assertTrue(line.price_missing)
        self.assertAlmostEqual(line.price_subtotal, 0.0)
        self.assertIn("TARIF BELUM DITETAPKAN", line.coverage_note)
        self.assertEqual(bill.unpriced_line_count, 1)

    def test_bill_with_an_unpriced_line_cannot_be_opened_for_payment(self):
        encounter = self._encounter()
        self._order_done(encounter, tariff=self._unpriced_tariff())
        bill = self.env["hms.bill"].search([("encounter_id", "=", encounter.id)])
        with self.assertRaises(UserError):
            bill.action_open()

    def test_cancelling_the_unpriced_line_unblocks_the_bill(self):
        encounter = self._encounter()
        self._order_done(encounter, tariff=self._unpriced_tariff())
        self._order_done(encounter)
        bill = self.env["hms.bill"].search([("encounter_id", "=", encounter.id)])
        bill.line_ids.filtered("price_missing").action_cancel_line(reason="Tidak ditagihkan")
        self.assertEqual(bill.unpriced_line_count, 0)
        bill.action_open()
        self.assertEqual(bill.state, "open")
