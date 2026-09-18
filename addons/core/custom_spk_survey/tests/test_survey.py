# -*- coding: utf-8 -*-
"""The two numbers a survey exists to capture, and the venue cost it feeds forward."""

from __future__ import annotations

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestSurvey(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Survey = cls.env["custom.spk.survey"]
        cls.partner = cls.env["res.partner"].create({"name": "Klien Pameran"})

    def _spk(self):
        spk = self.env["custom.spk"].create(
            {"partner_id": self.partner.id, "event_name": "GIIAS"})
        spk.action_confirm()
        return spk

    def _survey(self, **kw):
        vals = {
            "spk_id": self._spk().id, "venue_name": "JCC Senayan",
            "ceiling_height_m": 4.0, "access_width_m": 2.2,
        }
        vals.update(kw)
        return self.Survey.create(vals)

    def test_name_identifies_job_and_venue(self):
        spk = self._spk()
        s = self.Survey.create({
            "spk_id": spk.id, "venue_name": "Mall Kelapa Gading",
            "ceiling_height_m": 2.4, "access_width_m": 1.8,
        })
        self.assertIn(spk.name, s.name)
        self.assertIn("Mall Kelapa Gading", s.name)

    def test_venue_costs_roll_up_for_the_estimate(self):
        """These go into the estimate as venue cost instead of arriving as an invoice."""
        s = self._survey(
            venue_cost_power=2_500_000.0, venue_cost_permit=1_000_000.0,
            venue_cost_security=750_000.0, venue_cost_other=250_000.0)
        self.assertAlmostEqual(s.venue_cost_total, 4_500_000.0, places=2)

    def test_a_survey_without_ceiling_height_is_not_a_survey(self):
        """The number that most often contradicts the drawing."""
        s = self._survey(ceiling_height_m=0.0)
        with self.assertRaises(ValidationError):
            s.action_done()

    def test_a_survey_without_access_width_is_not_a_survey(self):
        """Panels are cut to this; getting it wrong means recutting on site."""
        s = self._survey(access_width_m=0.0)
        with self.assertRaises(ValidationError):
            s.action_done()

    def test_a_complete_survey_closes(self):
        s = self._survey()
        s.action_done()
        self.assertEqual(s.state, "done")

    def test_work_hours_must_fall_within_a_day(self):
        with self.assertRaises(ValidationError):
            self._survey(work_hours_from=22.0, work_hours_to=30.0)

    def test_night_only_venues_are_visible_on_the_list(self):
        """A one-day install becomes two nights, with crew premiums to match."""
        s = self._survey(night_work_only=True, work_hours_from=22.0, work_hours_to=6.0)
        self.assertTrue(s.night_work_only)

    def test_negative_dimensions_are_refused(self):
        with self.assertRaises(ValidationError):
            self._survey(ceiling_height_m=-1.0)

    # ---------- photographs live in the filestore ----------

    def test_photographs_attach_to_the_record(self):
        """R2 needs a card on file, so the filestore carries the cost and the evidence.

        One consequence favours the client: a file here is inside the record's own access
        rules and inside athera-backup, neither of which an external bucket would have
        been without extra work.
        """
        s = self._survey()
        att = self.env["ir.attachment"].create({
            "name": "front.jpg", "datas": b"aGVsbG8=", "mimetype": "image/jpeg",
            "res_model": s._name, "res_id": s.id,
        })
        s.photo_ids = [(4, att.id)]
        self.assertEqual(s.photo_count, 1)
        self.assertIn(att, s.photo_ids)

    def test_a_survey_with_no_photographs_still_closes(self):
        """The two mandatory numbers are dimensions, not pictures."""
        s = self._survey()
        self.assertEqual(s.photo_count, 0)
        s.action_done()
        self.assertEqual(s.state, "done")
