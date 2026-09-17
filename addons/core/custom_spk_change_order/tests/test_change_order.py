# -*- coding: utf-8 -*-
"""The gate: no verbal changes, and no change that the calendar cannot absorb."""

from __future__ import annotations

from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestChangeOrder(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.CO = cls.env["custom.spk.change.order"]
        cls.Rev = cls.env["custom.spk.design.revision"]
        cls.partner = cls.env["res.partner"].create({"name": "Klien Pameran"})

    def _spk(self, days_out=30):
        spk = self.env["custom.spk"].create({
            "partner_id": self.partner.id,
            "event_name": "GIIAS",
            "event_date_start": fields.Date.context_today(self.CO) + timedelta(days=days_out),
        })
        spk.action_confirm()
        return spk

    def _co(self, spk, origin="client_scope", price=5_000_000.0, days=0):
        return self.CO.create({
            "spk_id": spk.id, "description": "Tambah partisi",
            "origin": origin, "price_impact": price, "cost_impact": price * 0.7,
            "schedule_impact_days": days,
        })

    # ---------- numbering ----------

    def test_number_is_derived_from_the_spk(self):
        spk = self._spk()
        first, second = self._co(spk), self._co(spk)
        self.assertEqual(first.name, "CO/%s/01" % spk.name)
        self.assertEqual(second.name, "CO/%s/02" % spk.name)

    def test_two_change_orders_cannot_share_a_number(self):
        from psycopg2 import IntegrityError
        spk = self._spk()
        self._co(spk)
        with self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.CO.create({
                    "spk_id": spk.id, "description": "x", "sequence_no": 1})

    # ---------- who pays ----------

    def test_a_client_change_is_billable(self):
        self.assertTrue(self._co(self._spk(), origin="client_scope").is_billable)

    def test_our_own_mistake_is_not_billable(self):
        """Recorded anyway: a pattern of internal errors only gets fixed once counted."""
        co = self._co(self._spk(), origin="internal_error")
        self.assertFalse(co.is_billable)

    def test_billability_stays_editable(self):
        """Sometimes a technical adjustment is billable, sometimes goodwill is right."""
        co = self._co(self._spk(), origin="internal_error")
        co.is_billable = True
        self.assertTrue(co.is_billable)

    # ---------- pricing before agreeing ----------

    def test_a_billable_change_without_a_price_cannot_be_quoted(self):
        """Agreeing scope without a number is how the argument starts."""
        co = self._co(self._spk(), price=0.0)
        with self.assertRaises(UserError):
            co.action_quote()

    def test_client_cannot_approve_before_it_is_priced(self):
        co = self._co(self._spk())
        with self.assertRaises(UserError):
            co.action_client_approve()

    # ---------- the calendar is not negotiable ----------

    def test_a_change_needing_more_days_than_remain_is_refused(self):
        """The event date does not move, so this stops being a price question."""
        spk = self._spk(days_out=5)
        co = self._co(spk, days=10)
        co.action_quote()
        with self.assertRaises(UserError):
            co.action_client_approve()

    def test_a_change_the_calendar_can_absorb_is_approved(self):
        spk = self._spk(days_out=30)
        co = self._co(spk, days=3)
        co.action_quote()
        co.action_client_approve(approved_by="PIC Klien")
        self.assertEqual(co.state, "client_approved")
        self.assertEqual(co.client_approved_by, "PIC Klien")
        self.assertTrue(co.client_approved_on)

    def test_a_negative_schedule_impact_is_refused(self):
        with self.assertRaises(ValidationError):
            self._co(self._spk(), days=-3)

    # ---------- the gate ----------

    def test_the_workshop_cannot_act_without_recorded_client_approval(self):
        """Work done on a verbal request is work that gets argued about."""
        co = self._co(self._spk())
        co.action_quote()
        with self.assertRaises(UserError):
            co.action_apply()

    def test_approved_change_applies(self):
        co = self._co(self._spk())
        co.action_quote()
        co.action_client_approve(approved_by="PIC")
        co.action_apply()
        self.assertEqual(co.state, "applied")
        self.assertTrue(co.applied_on)

    # ---------- design revisions ----------

    def test_the_first_two_client_revisions_are_free(self):
        spk = self._spk()
        for n in (1, 2):
            rev = self.Rev.create({"spk_id": spk.id, "revision_no": n})
            self.assertFalse(rev.is_chargeable)

    def test_the_third_client_revision_is_chargeable(self):
        """Unbounded revisions consume margin and the schedule at the same time."""
        spk = self._spk()
        rev = self.Rev.create({"spk_id": spk.id, "revision_no": 3})
        self.assertTrue(rev.is_chargeable)

    def test_our_own_mistakes_never_become_chargeable(self):
        spk = self._spk()
        rev = self.Rev.create({
            "spk_id": spk.id, "revision_no": 5, "reason": "internal_error"})
        self.assertFalse(rev.is_chargeable, "however many there are")

    def test_technical_adjustments_are_not_chargeable_either(self):
        spk = self._spk()
        rev = self.Rev.create({
            "spk_id": spk.id, "revision_no": 4, "reason": "technical"})
        self.assertFalse(rev.is_chargeable)

    def test_revision_numbers_are_unique_per_job(self):
        from psycopg2 import IntegrityError
        spk = self._spk()
        self.Rev.create({"spk_id": spk.id, "revision_no": 1})
        with self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.Rev.create({"spk_id": spk.id, "revision_no": 1})
