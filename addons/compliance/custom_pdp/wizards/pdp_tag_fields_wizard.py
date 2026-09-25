# -*- coding: utf-8 -*-
"""Wizard for batch tagging ir.model.fields with PDP classifications.

Write-through: the frozen per-column registry (``pdp.field.classification``)
is canonical, so tagging a field here also upserts the matching registry row
(class = the code's roll-up). Otherwise the next ``_sync_field_tags()`` run
would report the tag as a conflict against an older registry entry.
"""

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..models.pdp_classification import CODE_TO_CLASS


class PdpTagFieldsWizard(models.TransientModel):
    _name = "pdp.tag.fields.wizard"
    _description = "Batch Tag PII Fields"

    model_id = fields.Many2one("ir.model", string="Model", required=True)
    field_ids = fields.Many2many(
        "ir.model.fields",
        string="Fields",
        domain="[('model_id', '=', model_id)]",
    )
    classification_id = fields.Many2one(
        "pdp.classification",
        string="Classification",
        required=True,
    )

    @api.onchange("model_id")
    def _onchange_model(self):
        self.field_ids = [(5, 0, 0)]

    def action_apply(self):
        self.ensure_one()
        if not self.field_ids:
            raise UserError("Select at least one field.")
        # Raw SQL, same as _seed_partner_pii_fields: Odoo 19 refuses ORM writes
        # on base ir.model.fields rows ("Properties of base fields cannot be
        # altered"), and the tag is our own manual column, not a field property.
        self.env.cr.execute(
            "UPDATE ir_model_fields SET x_pdp_classification_id = %s WHERE id = ANY(%s)",
            (self.classification_id.id, self.field_ids.ids),
        )
        self.env["ir.model.fields"].invalidate_model(["x_pdp_classification_id"])
        self._write_through_registry()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "PDP Tagging",
                "message": "Tagged %d fields as %s"
                % (
                    len(self.field_ids),
                    self.classification_id.code,
                ),
                "type": "success",
                "sticky": False,
            },
        }

    def _write_through_registry(self):
        """Upsert the canonical registry rows for the tagged fields."""
        pdp_class = (
            self.classification_id.pdp_class
            or CODE_TO_CLASS.get(self.classification_id.code)
        )
        if not pdp_class:
            # A bespoke code with no roll-up: the tag stands alone and
            # _sync_field_tags() will flag any disagreement.
            return
        registry = self.env["pdp.field.classification"].sudo().with_context(
            active_test=False
        )
        note = "SYNC:tag-wizard (%s)" % self.env.user.login
        for field in self.field_ids:
            row = registry.search(
                [
                    ("model_name", "=", field.model),
                    ("field_name", "=", field.name),
                ],
                limit=1,
            )
            if row:
                values = {}
                if row.pdp_class != pdp_class:
                    values["pdp_class"] = pdp_class
                    # The CHECK constraint restricts drop_to_null to 'sensitive'.
                    if pdp_class != "sensitive" and row.drop_to_null:
                        values["drop_to_null"] = False
                if not row.active:
                    values["active"] = True
                if values:
                    values["notes"] = note
                    row.write(values)
            else:
                registry.create(
                    {
                        "model_name": field.model,
                        "field_name": field.name,
                        "pdp_class": pdp_class,
                        "legal_basis": "Tagged as %r via the PDP wizard"
                        % self.classification_id.code,
                        "notes": note,
                    }
                )
