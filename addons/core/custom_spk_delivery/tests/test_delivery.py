# -*- coding: utf-8 -*-
"""Multi-venue shipments, the loading window, and handover as the billing gate."""

from __future__ import annotations

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestDelivery(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Delivery = cls.env["custom.spk.delivery"]
        cls.partner = cls.env["res.partner"].create({"name": "Klien Pameran"})

    def _spk(self, event="GIIAS", end=None):
        vals = {"partner_id": self.partner.id, "event_name": event}
        if end:
            vals["event_date_end"] = end
        spk = self.env["custom.spk"].create(vals)
        spk.action_confirm()
        return spk

    def _delivery(self, spk, seq=1, venue="JCC Senayan", loading="2026-08-01 22:00:00", cost=0.0):
        return self.Delivery.create({
            "spk_id": spk.id, "sequence_no": seq, "venue_name": venue,
            "loading_in": loading, "delivery_cost": cost,
        })

    # ---------- one job, several venues ----------

    def test_sub_number_is_derived_from_the_spk(self):
        """The client asks about D2 of SPK 0001, not the hundredth delivery this year."""
        spk = self._spk()
        first = self._delivery(spk, seq=1)
        second = self._delivery(spk, seq=2, venue="Mall Kelapa Gading")
        self.assertEqual(first.name, "%s/D1" % spk.name)
        self.assertEqual(second.name, "%s/D2" % spk.name)

    def test_two_shipments_cannot_share_a_sub_number(self):
        from psycopg2 import IntegrityError
        spk = self._spk()
        self._delivery(spk, seq=1)
        with self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self._delivery(spk, seq=1, venue="Lain")

    def test_one_job_can_ship_to_several_venues(self):
        spk = self._spk()
        self._delivery(spk, seq=1, venue="JCC Senayan")
        self._delivery(spk, seq=2, venue="Mall Kelapa Gading")
        self._delivery(spk, seq=3, venue="JCC Senayan")
        self.assertEqual(self.Delivery.search_count([("spk_id", "=", spk.id)]), 3)

    # ---------- the loading window ----------

    def test_a_venue_without_a_loading_window_is_refused(self):
        """Venues dictate when goods may enter, often overnight."""
        spk = self._spk()
        with self.assertRaises(ValidationError):
            self.Delivery.create({
                "spk_id": spk.id, "venue_name": "JCC Senayan", "loading_in": False,
            })

    def test_installation_cannot_end_before_it_starts(self):
        spk = self._spk()
        with self.assertRaises(ValidationError):
            self._delivery(spk).write({
                "installation_start": "2026-08-02 01:00:00",
                "installation_end": "2026-08-01 23:00:00",
            })

    # ---------- cost lands once ----------

    def test_marking_installed_books_the_trip_cost(self):
        spk = self._spk()
        d = self._delivery(spk, cost=1_800_000.0)
        d.action_mark_installed()
        self.assertEqual(d.state, "installed")
        self.assertTrue(d.cost_posted)
        lines = self.env["account.analytic.line"].search(
            [("account_id", "=", spk.analytic_account_id.id)])
        self.assertAlmostEqual(sum(lines.mapped("amount")), -1_800_000.0, places=2)

    def test_trip_cost_is_categorised_as_delivery(self):
        spk = self._spk()
        d = self._delivery(spk, cost=500_000.0)
        d.action_mark_installed()
        line = self.env["account.analytic.line"].search(
            [("account_id", "=", spk.analytic_account_id.id)], limit=1)
        self.assertEqual(line.x_spk_cost_category, "delivery")

    def test_a_scheduled_trip_that_never_happened_costs_nothing(self):
        spk = self._spk()
        self._delivery(spk, cost=1_800_000.0)
        lines = self.env["account.analytic.line"].search(
            [("account_id", "=", spk.analytic_account_id.id)])
        self.assertFalse(lines, "cost lands on installation, not on scheduling")

    def test_installing_twice_is_refused_so_cost_cannot_double(self):
        spk = self._spk()
        d = self._delivery(spk, cost=900_000.0)
        d.action_mark_installed()
        with self.assertRaises(UserError):
            d.action_mark_installed()

    # ---------- handover is the billing gate ----------

    def test_bast_is_linked_not_duplicated(self):
        """custom_bast already does dual signature, GPS and timestamp."""
        spk = self._spk()
        d = self._delivery(spk)
        d.action_create_bast()
        self.assertTrue(d.bast_id)
        self.assertEqual(d.bast_id.party_to_id, self.partner)
        self.assertEqual(d.bast_id.kind, "installation")
        self.assertFalse(d.bast_signed, "raising the document is not signing it")

    def test_creating_bast_twice_reuses_the_first(self):
        spk = self._spk()
        d = self._delivery(spk)
        d.action_create_bast()
        first = d.bast_id
        d.action_create_bast()
        self.assertEqual(d.bast_id, first, "two handover records would disagree")

    def test_handover_cannot_be_confirmed_without_the_client_signature(self):
        """Billing against an unsigned BAST is what a client's finance dept declines."""
        spk = self._spk()
        d = self._delivery(spk)
        d.action_create_bast()
        d.action_mark_installed()
        with self.assertRaises(UserError):
            d.action_confirm_handover()

    def test_client_signature_closes_the_handover(self):
        spk = self._spk()
        d = self._delivery(spk)
        d.action_create_bast()
        d.action_mark_installed()
        d.bast_id.action_sign_to(b"c2lnbmF0dXJl", signed_by="PIC Klien")
        self.assertTrue(d.bast_signed)
        d.action_confirm_handover()
        self.assertEqual(d.state, "bast_signed")

    # ---------- dismantle ----------

    def test_dismantle_reminder_fires_after_the_event_ends(self):
        """The work always happens; the schedule is what goes missing."""
        spk = self._spk(end="2026-08-05")
        d = self._delivery(spk)
        d.action_mark_installed()
        flagged = self.Delivery._cron_schedule_dismantle()
        self.assertGreaterEqual(flagged, 1)

    def test_a_scheduled_dismantle_is_not_flagged(self):
        spk = self._spk(end="2026-08-05")
        d = self._delivery(spk)
        d.action_mark_installed()
        d.dismantle_at = "2026-08-06 22:00:00"
        flagged = self.Delivery._cron_schedule_dismantle()
        self.assertEqual(flagged, 0)
