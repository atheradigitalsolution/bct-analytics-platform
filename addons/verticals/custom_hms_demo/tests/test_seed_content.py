# -*- coding: utf-8 -*-
"""Pagar database demo, idempotensi penyemaian, dan isi yang dijanjikan."""
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.custom_hms_demo.hooks import post_init_hook


class _FakeCursor:
    dbname = "produksi"


class _FakeEnv:
    cr = _FakeCursor()


@tagged("post_install", "-at_install", "hms")
class TestSeedGuard(TransactionCase):
    def test_seeding_refuses_a_database_that_is_not_demo(self):
        """Jalur seeding baru harus menolak sekeras post_init_hook."""
        builder = self.env["hms.demo.builder"]
        with patch.object(type(builder), "_database_name", lambda self: "produksi"):
            with self.assertRaises(UserError):
                builder.seed_all()

    def test_content_builder_refuses_a_database_that_is_not_demo(self):
        content = self.env["hms.demo.content"]
        builder = self.env["hms.demo.builder"]
        with patch.object(type(builder), "_database_name", lambda self: "rs_produksi"):
            with self.assertRaises(UserError):
                content.build_content()

    def test_post_init_hook_still_refuses_a_database_that_is_not_demo(self):
        with self.assertRaises(UserError):
            post_init_hook(_FakeEnv())

    def test_the_guard_accepts_the_demo_database(self):
        self.assertTrue(
            self.env["hms.demo.builder"]._assert_demo_database().endswith("_demo")
        )


@tagged("post_install", "-at_install", "hms")
class TestSeededMasters(TransactionCase):
    def test_support_catalogues_are_populated(self):
        for model in ("hms.lab.test", "hms.rad.exam", "hms.diet.type"):
            self.assertTrue(
                self.env[model].search_count([]),
                "Katalog %s masih kosong setelah penyemaian." % model,
            )

    def test_lab_catalogue_does_not_shrink_the_legacy_panel(self):
        """Katalog yang menang atas M2M lama tidak boleh memangkas parameternya.

        ``hms.tariff._hms_lab_parameters()`` mendahulukan ``hms.lab.test``.
        Sebuah entri katalog yang isinya lebih sedikit daripada M2M lama akan
        MENGURANGI baris hasil tanpa memberi tahu siapa pun.
        """
        tariff = self.env["hms.tariff"].search([("code", "=", "LAB-DL")], limit=1)
        self.assertTrue(tariff)
        legacy = set(tariff.lab_parameter_ids.ids)
        resolved = set(tariff._hms_lab_parameters().ids)
        self.assertTrue(legacy.issubset(resolved))

    def test_a_tariff_without_a_catalogue_entry_still_falls_back(self):
        widal = self.env["hms.tariff"].search([("code", "=", "LAB-WIDAL")], limit=1)
        self.assertTrue(widal)
        self.assertFalse(widal.lab_test_ids)
        self.assertEqual(widal._hms_lab_parameters(), widal.lab_parameter_ids)


@tagged("post_install", "-at_install", "hms")
class TestSeededScenarios(TransactionCase):
    def _count(self, model, domain=None):
        return self.env[model].search_count(domain or [])

    def test_casemix_screen_has_claims_across_states(self):
        states = set(self.env["hms.claim"].search([]).mapped("state"))
        self.assertGreaterEqual(self._count("hms.claim"), 8)
        for wanted in ("to_code", "coding", "finalized", "submitted",
                       "pending", "dispute"):
            self.assertIn(wanted, states, "Tidak ada klaim berstatus %s." % wanted)
        self.assertTrue(states & {"approved", "paid"})

    def test_pending_and_dispute_claims_carry_their_reason(self):
        for claim in self.env["hms.claim"].search([("state", "=", "pending")]):
            self.assertTrue(claim.pending_reason)
            self.assertTrue(claim.pending_category)
        for claim in self.env["hms.claim"].search([("state", "=", "dispute")]):
            self.assertTrue(claim.dispute_level)

    def test_batches_and_adjustments_exist(self):
        self.assertGreaterEqual(self._count("hms.claim.batch"), 2)
        self.assertTrue(self._count("hms.claim.adjustment",
                                    [("state", "=", "authorized")]))
        self.assertTrue(self._count("hms.claim.adjustment", [("state", "=", "draft")]))
        self.assertTrue(self._count("hms.coding.query"))

    def test_medrec_screen_has_open_and_closed_findings(self):
        self.assertTrue(self._count("hms.klpcm", [("state", "=", "open")]))
        self.assertTrue(self._count("hms.klpcm", [("state", "=", "completed")]))
        self.assertTrue(self._count("hms.klpcm", [("is_overdue", "=", True)]))
        self.assertTrue(self._count("hms.roi.request",
                                    [("state", "in", ("submitted", "approved"))]))
        self.assertTrue(self._count("hms.correction.request"))
        self.assertTrue(self._count("hms.death.certificate", [("state", "=", "signed")]))
        self.assertGreaterEqual(self._count("hms.medical.letter"), 3)

    def test_safety_screen_spans_severity_and_state(self):
        incidents = self.env["hms.incident.report"].search([])
        self.assertGreaterEqual(len(incidents), 8)
        self.assertTrue({"knc", "ktc", "ktd", "sentinel"}
                        <= set(incidents.mapped("incident_type")))
        self.assertTrue({"reported", "investigating", "graded", "closed"}
                        <= set(incidents.mapped("state")))
        self.assertTrue(incidents.filtered("is_anonymous"))
        self.assertFalse(incidents.filtered(
            lambda i: i.is_anonymous and i.reporter_id
        ))
        self.assertGreaterEqual(self._count("hms.complaint"), 6)

    def test_critical_results_show_both_sides_of_the_loop(self):
        rad = self.env["hms.rad.report"].search([("is_critical", "=", True)])
        self.assertTrue(rad.filtered(lambda r: r.ack_state == "acknowledged"))
        self.assertTrue(rad.filtered(lambda r: r.ack_state in ("pending", "overdue")))
        lab = self.env["hms.lab.result"].search([("is_critical", "=", True)])
        self.assertTrue(lab.filtered(lambda r: r.ack_state == "acknowledged"))
        self.assertTrue(lab.filtered(lambda r: r.ack_state in ("pending", "overdue")))

    def test_schedule_board_has_a_postponement_with_a_reason(self):
        schedules = self.env["hms.procedure.schedule"].search([])
        self.assertGreaterEqual(len(schedules), 3)
        postponed = schedules.filtered(lambda s: s.state == "postponed")
        self.assertTrue(postponed)
        self.assertTrue(all(s.postpone_reason for s in postponed))

    def test_followup_plans_never_invent_a_bpjs_control_number(self):
        plans = self.env["hms.followup.plan"].search([])
        self.assertGreaterEqual(len(plans), 3)
        self.assertFalse(plans.filtered("bpjs_control_no"))

    def test_a_claim_is_close_enough_to_its_deadline_to_show_the_marker(self):
        claims = self.env["hms.claim"].search([("state", "not in", ("paid", "rejected"))])
        self.assertTrue(
            claims.filtered(lambda c: 0 < c.days_to_deadline <= 30),
            "Tidak ada klaim yang mendekati tenggat; penanda kedaluwarsa "
            "tidak akan terlihat hidup.",
        )

    def test_seeding_twice_adds_nothing(self):
        """Idempotensi dibuktikan, bukan diasumsikan."""
        models = ("hms.encounter", "hms.claim", "hms.claim.code", "hms.claim.batch",
                  "hms.claim.adjustment", "hms.coding.query", "hms.klpcm",
                  "hms.roi.request", "hms.correction.request", "hms.medical.letter",
                  "hms.death.certificate", "hms.incident.report", "hms.complaint",
                  "hms.rad.report", "hms.procedure.schedule", "hms.followup.plan",
                  "hms.lab.test", "hms.rad.exam", "hms.diet.type")
        before = {m: self._count(m) for m in models}
        self.env["hms.demo.builder"].seed_all()
        after = {m: self._count(m) for m in models}
        self.assertEqual(before, after)
