# -*- coding: utf-8 -*-
"""PDP semantic dictionary, rolled up onto the five frozen registry classes.

``pdp.classification`` is the human-facing vocabulary (``pii``, ``financial``,
``child`` ...) with behavioural flags for consent, masking and retention.
``pdp.field.classification`` is the frozen per-column registry of contract 01.
The dictionary NEVER competes with the registry: every code rolls up to exactly
one frozen class via ``pdp_class``, and the ``x_pdp_classification_id`` tag on
``ir.model.fields`` is a derived projection of the registry, kept in sync by
``_pdp_post_sync()`` (idempotent, runs on every ``-u``).
"""

import logging

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .pdp_field_classification import PDP_CLASSES

_logger = logging.getLogger(__name__)

#: dictionary code -> frozen registry class. Every seeded code must appear here.
CODE_TO_CLASS = {
    "public": "public",
    "internal": "internal",
    "pii": "personal",
    "financial": "sensitive",
    "child": "sensitive",
    "sensitive": "sensitive",
    "anonymized": "internal",
    "secret": "secret",
}

#: frozen registry class -> the dictionary code the projection uses when a
#: column has no tag yet. Deliberately the least specific code of the class.
DEFAULT_CODE_FOR_CLASS = {
    "public": "public",
    "internal": "internal",
    "personal": "pii",
    "sensitive": "sensitive",
    "secret": "secret",
}


class PdpClassification(models.Model):
    _name = "pdp.classification"
    _description = "PDP Data Classification"
    _order = "sequence, code"
    _rec_name = "code"

    sequence = fields.Integer(default=10)
    code = fields.Char(required=True, index=True)
    name = fields.Char(required=True, translate=True)
    description = fields.Text(translate=True)
    pdp_class = fields.Selection(
        PDP_CLASSES,
        string="Registry Class",
        help="The frozen contract-01 class this code rolls up to. The warehouse and the "
        "CDC loader only ever see the five frozen classes; this code is the finer-grained "
        "vocabulary used inside Odoo (consent, retention, DSAR).",
    )
    requires_consent = fields.Boolean(
        default=False,
        help="Processing this classification requires recorded subject consent.",
    )
    requires_masking = fields.Boolean(
        default=False,
        help="Field values of this classification must be masked in UI/export by default.",
    )
    default_retention_days = fields.Integer(
        default=0,
        help="Default retention period (days). 0 = unlimited / governed elsewhere.",
    )
    color = fields.Integer(default=0)
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint(
        "unique(code)",
        "Classification code must be unique.",
    )

    @api.constrains("code")
    def _check_code(self):
        for rec in self:
            if not rec.code or " " in rec.code:
                raise ValidationError("Classification code must be non-empty and contain no spaces.")

    @api.model
    def _seed_partner_pii_fields(self):
        """Tag default PII-classified fields on res.partner.

        Called from data XML <function/>; idempotent.
        """
        mapping = {
            "name": "pii",
            "phone": "pii",
            "mobile": "pii",
            "email": "pii",
            "vat": "financial",
        }
        # Odoo 19 blocks ORM writes to base ir.model.fields rows.
        # Use raw SQL to set the cross-cutting PDP tag column we added via _inherit.
        for fname, code in mapping.items():
            classif = self.search([("code", "=", code)], limit=1)
            if not classif:
                continue
            self.env.cr.execute(
                """
                UPDATE ir_model_fields
                   SET x_pdp_classification_id = %s
                 WHERE model = %s
                   AND name = %s
                   AND (x_pdp_classification_id IS NULL OR x_pdp_classification_id = 0)
                """,
                (classif.id, "res.partner", fname),
            )
        return True

    # ------------------------------------------------------------------
    # Registry -> tag projection
    # ------------------------------------------------------------------

    @api.model
    def _fill_pdp_class(self):
        """Backfill ``pdp_class`` on dictionary rows.

        The seed records are ``noupdate="1"``, so databases that installed the
        dictionary before ``pdp_class`` existed never receive the value from
        XML. Idempotent; never overrides a deliberate manual change.
        """
        for code, pdp_class in CODE_TO_CLASS.items():
            self.env.cr.execute(
                """
                UPDATE pdp_classification
                   SET pdp_class = %s
                 WHERE code = %s
                   AND pdp_class IS NULL
                """,
                (pdp_class, code),
            )
        unmapped = self.with_context(active_test=False).search(
            [("pdp_class", "=", False)]
        )
        for rec in unmapped:
            _logger.warning(
                "pdp.classification code %r has no registry roll-up; "
                "add it to CODE_TO_CLASS or set pdp_class manually.",
                rec.code,
            )
        return True

    @api.model
    def _sync_field_tags(self):
        """Project the registry onto ``ir_model_fields.x_pdp_classification_id``.

        Only fills tags that are NULL - a finer-grained tag chosen by a DPO
        (e.g. ``financial`` where the registry says ``sensitive``) is kept as
        long as its roll-up agrees with the registry. Genuine conflicts (the
        tag's roll-up contradicts the registry class) are logged loudly and
        left for a human: the registry is canonical, but silently rewriting a
        deliberate tag would hide the disagreement instead of resolving it.

        Raw SQL on purpose: Odoo 19 blocks ORM writes to base
        ``ir.model.fields`` rows. Idempotent; called from data ``<function/>``
        so it runs on every ``-u``.
        """
        self.env.cr.execute(
            """
            UPDATE ir_model_fields f
               SET x_pdp_classification_id = c.id
              FROM pdp_field_classification p
              JOIN pdp_classification c
                ON c.pdp_class = p.pdp_class
               AND c.code = CASE p.pdp_class WHEN 'personal' THEN 'pii' ELSE p.pdp_class END
             WHERE f.model = p.model_name
               AND f.name = p.field_name
               AND p.active
               AND f.x_pdp_classification_id IS NULL
            """
        )
        filled = self.env.cr.rowcount
        self.env.cr.execute(
            """
            SELECT f.model, f.name, c.code, c.pdp_class, p.pdp_class
              FROM ir_model_fields f
              JOIN pdp_classification c ON c.id = f.x_pdp_classification_id
              JOIN pdp_field_classification p
                ON p.model_name = f.model AND p.field_name = f.name AND p.active
             WHERE c.pdp_class IS DISTINCT FROM p.pdp_class
            """
        )
        conflicts = self.env.cr.fetchall()
        for model, name, code, tag_class, reg_class in conflicts:
            _logger.warning(
                "PDP tag conflict on %s.%s: tag %r rolls up to %r but the registry "
                "says %r. The registry is canonical - fix the tag or the registry row.",
                model, name, code, tag_class, reg_class,
            )
        if filled:
            _logger.info("PDP sync: filled %d field tags from the registry.", filled)
        return True

    @api.model
    def _pdp_post_sync(self):
        """Data-file entry point: backfill ``pdp_class``, then project tags."""
        self._fill_pdp_class()
        self._sync_field_tags()
        return True
