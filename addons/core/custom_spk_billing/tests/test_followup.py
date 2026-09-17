# -*- coding: utf-8 -*-
"""Dunning that escalates once per threshold, and the credit warning."""

from __future__ import annotations

from odoo import fields
from odoo.tests import tagged

from .common import BillingCommon


@tagged("post_install", "-at_install")
class TestFollowup(BillingCommon):

    def _invoice(self, days_overdue, post=True, amount=1_000_000.0):
        due = fields.Date.subtract(fields.Date.context_today(self.Move), days=days_overdue)
        invoice = self.Move.create({
            "move_type": "out_invoice",
            "partner_id": self.partner.id,
            "invoice_date": due,
            "invoice_date_due": due,
            "invoice_line_ids": [(0, 0, {
                "name": "Booth", "quantity": 1, "price_unit": amount})],
        })
        if post:
            invoice.action_post()
        return invoice

    # ---------- levels are data ----------

    def test_seeded_levels_start_before_the_due_date(self):
        """A reminder three days early costs nothing and removes 'we never got it'."""
        pre = self.env.ref("custom_spk_billing.followup_level_pre")
        self.assertEqual(pre.days_overdue, -3)
        self.assertEqual(pre.action, "email")

    def test_the_sequence_ends_at_the_owner(self):
        last = self.Level.search([], order="days_overdue desc", limit=1)
        self.assertEqual(last.action, "escalate",
                         "dunning that emails politely forever is not dunning")

    def test_two_levels_cannot_share_an_age(self):
        from psycopg2 import IntegrityError
        with self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.Level.create({"name": "dup", "days_overdue": 7, "action": "call"})

    # ---------- the cron ----------

    def test_an_overdue_invoice_reaches_the_level_its_age_warrants(self):
        invoice = self._invoice(days_overdue=8)
        self.Move._cron_spk_followup()
        invoice.invalidate_recordset()
        self.assertEqual(invoice.x_spk_followup_level_id.days_overdue, 7,
                         "the highest threshold passed, not the first")

    def test_a_level_fires_once_per_invoice(self):
        """A client emailed twice for the same threshold stops reading the emails."""
        invoice = self._invoice(days_overdue=8)
        self.Move._cron_spk_followup()
        first = invoice.x_spk_followup_level_id
        acted_again = self.Move._cron_spk_followup()
        self.assertEqual(invoice.x_spk_followup_level_id, first)
        self.assertEqual(acted_again, 0)

    def test_crossing_the_next_threshold_advances_the_level(self):
        invoice = self._invoice(days_overdue=8)
        self.Move._cron_spk_followup()
        invoice.invoice_date_due = fields.Date.subtract(
            fields.Date.context_today(self.Move), days=31)
        self.Move._cron_spk_followup()
        invoice.invalidate_recordset()
        self.assertEqual(invoice.x_spk_followup_level_id.action, "escalate")

    def test_an_invoice_not_yet_due_enough_is_left_alone(self):
        invoice = self._invoice(days_overdue=-10)
        self.Move._cron_spk_followup()
        self.assertFalse(invoice.x_spk_followup_level_id)

    def test_a_draft_invoice_is_not_chased(self):
        invoice = self._invoice(days_overdue=20, post=False)
        self.Move._cron_spk_followup()
        self.assertFalse(invoice.x_spk_followup_level_id)

    # ---------- credit control ----------

    def test_overdue_age_and_amount_are_computed_from_posted_invoices(self):
        self._invoice(days_overdue=70, amount=5_000_000.0)
        self._invoice(days_overdue=10, amount=2_000_000.0)
        self.partner.invalidate_recordset()
        self.assertGreaterEqual(self.partner.x_spk_overdue_days, 70)
        self.assertGreater(self.partner.x_spk_overdue_amount, 0.0)

    def test_credit_warning_fires_past_the_configured_age(self):
        self.env.company.x_spk_credit_hold_days = 60
        self._invoice(days_overdue=70, amount=5_000_000.0)
        self.partner.invalidate_recordset()
        warning = self.partner.spk_credit_warning()
        self.assertTrue(warning)
        self.assertIn(self.partner.display_name, warning)

    def test_credit_warning_is_a_warning_not_a_block(self):
        """Whether to take the job anyway is the owner's call, and may be justified."""
        self.env.company.x_spk_credit_hold_days = 60
        self._invoice(days_overdue=70)
        self.partner.invalidate_recordset()
        # Returns text rather than raising: the caller decides what to do with it.
        self.assertIsInstance(self.partner.spk_credit_warning(), str)

    def test_credit_check_can_be_disabled(self):
        self.env.company.x_spk_credit_hold_days = 0
        self._invoice(days_overdue=200)
        self.partner.invalidate_recordset()
        self.assertFalse(self.partner.spk_credit_warning())

    def test_a_client_within_terms_raises_no_warning(self):
        self.env.company.x_spk_credit_hold_days = 60
        self._invoice(days_overdue=5)
        self.partner.invalidate_recordset()
        self.assertFalse(self.partner.spk_credit_warning())
