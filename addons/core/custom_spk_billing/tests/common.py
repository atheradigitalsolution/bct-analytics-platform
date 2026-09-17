# -*- coding: utf-8 -*-
from __future__ import annotations

from odoo.tests.common import TransactionCase


class BillingCommon(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Plan = cls.env["custom.spk.billing.plan"]
        cls.Milestone = cls.env["custom.spk.billing.milestone"]
        cls.Level = cls.env["custom.spk.followup.level"]
        cls.Move = cls.env["account.move"]
        cls.partner = cls.env["res.partner"].create({"name": "Klien Pameran"})

    def _spk(self, event="GIIAS"):
        spk = self.env["custom.spk"].create(
            {"partner_id": self.partner.id, "event_name": event})
        spk.action_confirm()
        return spk

    def _plan(self, spk=None, mode="single", amount=44_000_000.0):
        return self.Plan.create({
            "spk_id": (spk or self._spk()).id, "mode": mode, "contract_amount": amount,
        })

    def _standard_terms(self, plan):
        """DP 50 / handover 40 / retention 10, the shape the document describes."""
        self.Milestone.create({
            "plan_id": plan.id, "name": "DP", "percentage": 50.0,
            "is_down_payment": True, "trigger": "on_confirm", "sequence": 10})
        self.Milestone.create({
            "plan_id": plan.id, "name": "Setelah BAST", "percentage": 40.0,
            "trigger": "on_handover", "sequence": 20})
        self.Milestone.create({
            "plan_id": plan.id, "name": "Retensi", "percentage": 10.0,
            "trigger": "after_event", "sequence": 30})
        return plan
