# -*- coding: utf-8 -*-
"""Clinical events issue the next queue ticket automatically."""
from odoo import _, api, fields, models


class HmsEncounter(models.Model):
    _inherit = "hms.encounter"

    journey_id = fields.One2many("hms.qms.journey", "encounter_id", "Perjalanan Antrian")
    qms_ticket_ids = fields.One2many("hms.qms.ticket", "encounter_id", "Tiket Antrian")
    current_ticket_id = fields.Many2one(
        "hms.qms.ticket", "Tiket Aktif", compute="_compute_current_ticket",
    )

    @api.depends("qms_ticket_ids.state")
    def _compute_current_ticket(self):
        for enc in self:
            enc.current_ticket_id = enc.qms_ticket_ids.filtered(
                lambda t: t.state in ("waiting", "called", "serving")
            )[:1]

    def _get_journey(self):
        self.ensure_one()
        journey = self.env["hms.qms.journey"].search([("encounter_id", "=", self.id)], limit=1)
        if not journey:
            journey = self.env["hms.qms.journey"].create({"encounter_id": self.id})
        return journey

    def _hms_issue_ticket(self):
        """Called by custom_hms_registration right after the encounter is made.

        The service is chosen from the unit: a clinic with `queue_mode` set to
        per-practitioner uses the doctor's own service when one exists, which
        is how a hospital runs two doctors in one room without their numbers
        colliding.
        """
        self.ensure_one()
        Service = self.env["hms.qms.service"]
        service = False
        if self.unit_id.queue_mode == "per_practitioner" and self.practitioner_id:
            service = Service.search([
                ("unit_id", "=", self.unit_id.id),
                ("practitioner_id", "=", self.practitioner_id.id),
            ], limit=1)
        if not service:
            service = Service.search([("unit_id", "=", self.unit_id.id)], limit=1)
        if not service:
            return False
        priority = self._queue_priority()
        return self.env["hms.qms.ticket"].issue(
            service, priority=priority, encounter=self, source="registration",
            journey=self._get_journey(), stage_no=1,
        )

    def _queue_priority(self):
        """Derive the priority flag from what is already known about the patient."""
        self.ensure_one()
        patient = self.patient_id
        if self.type == "emergency":
            return "emergency"
        if patient.disability and patient.disability != "none":
            return "disability"
        if patient.age_years >= 60:
            return "elderly"
        if patient.age_years < 2:
            return "infant"
        return "none"

    def action_close(self):
        """Closing the visit hands the patient to pharmacy and/or the cashier."""
        res = super().action_close()
        for enc in self:
            enc._issue_followup_tickets()
        return res

    def _issue_followup_tickets(self):
        self.ensure_one()
        Service = self.env["hms.qms.service"]
        Ticket = self.env["hms.qms.ticket"]
        journey = self._get_journey()
        stage = max(self.qms_ticket_ids.mapped("stage_no") or [1])
        issued = Ticket

        pending_rx = self.prescription_ids.filtered(
            lambda r: r.state in ("draft", "submitted", "verified", "preparing", "ready")
        ) if "prescription_ids" in self._fields else Ticket.browse()
        if pending_rx:
            pharmacy = Service.search([("kind", "=", "pharmacy")], limit=1)
            if pharmacy:
                stage += 1
                issued |= Ticket.issue(
                    pharmacy, priority=self._queue_priority(), encounter=self,
                    source="clinical", journey=journey, stage_no=stage,
                )

        cashier = Service.search([("kind", "=", "cashier")], limit=1)
        if cashier:
            stage += 1
            issued |= Ticket.issue(
                cashier, priority=self._queue_priority(), encounter=self,
                source="clinical", journey=journey, stage_no=stage,
            )
        return issued


class HmsOrderLine(models.Model):
    _inherit = "hms.order.line"

    def action_order(self):
        """A lab or radiology order puts the patient in that department's queue."""
        res = super().action_order()
        Service = self.env["hms.qms.service"]
        Ticket = self.env["hms.qms.ticket"]
        for line in self:
            if line.order_type not in ("lab", "radiology"):
                continue
            existing = Ticket.search([
                ("encounter_id", "=", line.encounter_id.id),
                ("service_id.kind", "=", line.order_type),
                ("state", "in", ("waiting", "called", "serving")),
            ], limit=1)
            if existing:
                continue
            service = Service.search([
                ("kind", "=", line.order_type),
                ("unit_id", "in", (line.unit_id.id, False)),
            ], limit=1)
            if not service:
                continue
            Ticket.issue(
                service, priority=line.encounter_id._queue_priority(),
                encounter=line.encounter_id, source="clinical",
                journey=line.encounter_id._get_journey(),
                stage_no=max(line.encounter_id.qms_ticket_ids.mapped("stage_no") or [1]) + 1,
            )
        return res
