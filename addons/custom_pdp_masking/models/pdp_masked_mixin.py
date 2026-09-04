# Part of custom_pdp_masking. Licence: LGPL-3.
"""In-Odoo enforcement of the masking policy.

Contract 01 binds the *warehouse* load. This mixin closes the obvious hole next to it: a user who
cannot see personal data in a dashboard but can open the same record in Odoo has not been
restricted at all.

How it works — the READ funnel
------------------------------
The override sits on ``_read_format()``, **not** on ``read()``, and that distinction is the whole
point of this file's 2026-09-04 revision.

``read()`` is what the form and list views call, but it is *not* the only public RPC method that
formats stored values for a caller. In Odoo 19 the picture is::

    read()                  -> self.fetch(...)  -> self._read_format(...)
    search_read()           -> self.search_fetch(...) -> records._read_format(...)
    web_read()              -> self.read(...)   -> ... -> self._read_format(...)
    web_search_read()       -> web_read()       -> ... -> self._read_format(...)

``search_read`` therefore never touches ``read()``. Masking ``read()`` alone left
``/web/dataset/call_kw`` with ``method="search_read"`` returning cleartext ``name``, ``email``,
``phone`` and ``vat`` to any authenticated user without ``custom_pdp_core.group_pdp_data_viewer``
— measured against the running stack, not inferred. ``_read_format()`` is the one place both
paths meet, and Odoo's own ``read()`` docstring names it as the supported override point
("This is a high-level method that is not supposed to be overridden. In order to modify how fields
are read from database, see methods :meth:`_fetch_query` and :meth:`_read_format`").

Masking there still touches no internal ORM path: ``record.email``, ``mapped()``, ``search()``
domains and ``_compute`` methods read through the cache and are unaffected. Business logic keeps
working on cleartext; only what is formatted for a caller is masked.

How it works — the GROUP funnel
-------------------------------
Aggregation is a second way to read a column, and it does not go through ``_read_format()`` at all.
``formatted_read_group(domain, groupby=["vat"], ...)`` returns one row per distinct NPWP, listing
every value verbatim, plus an ``__extra_domain`` that repeats the value a second time. Even
``aggregates=["vat:array_agg"]`` on an unmasked groupby hands back the whole column.

Grouping is REFUSED rather than masked, and that is a deliberate choice:

* Masking the group label alone would still leak through ``__extra_domain`` (which must select the
  group and therefore must carry the real value) and through ``having``/``order``. Three channels
  to remember instead of one, and a future Odoo release can add a fourth.
* "Group these people by their tax number" is not an operation someone who may not read the tax
  number has a legitimate use for, so refusing costs nothing real.
* It fails closed. A spec this file does not recognise still lands in the refusal, because the
  match is on field names appearing anywhere in the spec string.

The three public group entry points are covered, and between them they cover every group path the
web client has: ``web_read_group`` and ``read_progress_bar`` both call ``formatted_read_group``,
and ``search_panel_select_range`` only accepts many2one/selection fields, which this mixin never
masks. Searching and filtering on a masked column stays allowed — see MODULE_KNOWLEDGE.md for why
that boundary is where it is.

The masked token
----------------
Masked ``char``/``text`` columns become ``***`` plus a short token, so two different partners still
look different in a list and the UI stays navigable. The token is derived from the database UUID,
**not** from the warehouse salt:

* the warehouse salt must never be present in an HTTP response, and
* a UI token must never be mistaken for a warehouse digest and used as a join key.

Columns classified ``sensitive`` with ``drop_to_null`` (free text) are blanked entirely, matching
what the warehouse will hold for them.
"""

import hashlib
import hmac
import logging
import re

from odoo import _, api, models
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)

#: Prefix that makes a masked value obvious in a screenshot and greppable in a bug report.
UI_MASK_PREFIX = "***"

#: Number of hex characters of the UI token. Short on purpose: it is a visual discriminator, not
#: a cryptographic identifier.
UI_MASK_TOKEN_LENGTH = 8

#: Replacement for masked free-text columns.
UI_MASK_BLANK = "*** redacted (PDP) ***"

#: Every identifier-shaped token in a groupby/aggregate/order specification. Odoo spells those
#: specs as ``field``, ``field:granularity``, ``field:agg`` or ``alias:agg(field)``; pulling every
#: identifier out of the string covers all four without a parser that has to be kept in step with
#: the ORM. It over-matches (an alias that happens to be called ``name`` is treated as the field),
#: and over-matching here means refusing a query rather than answering one, which is the safe way
#: round.
_PDP_SPEC_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class PdpMaskedMixin(models.AbstractModel):
    """Mask ``personal`` and ``sensitive`` columns in the UI for non-viewers.

    Inherit it into any model that stores personal data::

        class ResPartner(models.Model):
            _name = "res.partner"
            _inherit = ["res.partner", "pdp.masked.mixin"]
    """

    _name = "pdp.masked.mixin"
    _description = "PDP UI Masking Mixin"

    #: Columns this model never masks in the UI, even when classified. Override per model.
    _pdp_ui_mask_exclude = ()

    #: Non-stored companions of a masked column that must be masked with it, otherwise the
    #: cleartext leaks back through a computed label.
    _pdp_ui_mask_companions = {
        "name": ("display_name", "complete_name"),
    }

    @api.model
    def _pdp_ui_may_see_raw(self):
        """Return True when the current user may read personal data unmasked."""
        if self.env.su:
            # Superuser: module installation, data loading, cron and the demo seeder. Masking
            # these would corrupt data rather than protect it.
            return True
        return self.env.user.has_group("custom_pdp_core.group_pdp_data_viewer")

    @api.model
    def _pdp_ui_token(self, value):
        """Return a stable, non-reversible discriminator for ``value``.

        Keyed on the database UUID so it is stable within a database, differs across databases,
        and shares no key material with the warehouse digest.
        """
        key = (
            self.env["ir.config_parameter"].sudo().get_param("database.uuid")
            or self.env.cr.dbname
            or "pdp"
        )
        digest = hmac.new(
            key.encode("utf-8"), str(value).encode("utf-8"), hashlib.sha256
        ).hexdigest()
        return UI_MASK_PREFIX + digest[:UI_MASK_TOKEN_LENGTH]

    @api.model
    def _pdp_ui_blank(self):
        """Replacement for a masked free-text column. Shared with the export path."""
        return UI_MASK_BLANK

    def _pdp_ui_mask_value(self, field_name, value, mode):
        if mode == "null":
            return self._pdp_ui_blank()
        return self._pdp_ui_token(value)

    # ------------------------------------------------------------------
    # The plan, resolved once per call
    # ------------------------------------------------------------------

    @api.model
    def _pdp_ui_effective_plan(self):
        """Return ``{column: 'hash' | 'null'}`` for this model, minus its exclusions.

        Empty when the caller may see raw values, so every caller can treat "empty plan" as
        "nothing to do" without repeating the group check.
        """
        if self._pdp_ui_may_see_raw():
            return {}
        plan = self.env["pdp.masking.rule"].sudo()._ui_mask_plan(self._name)
        if not plan:
            return {}
        return {
            name: mode
            for name, mode in plan.items()
            if name not in self._pdp_ui_mask_exclude
        }

    # ------------------------------------------------------------------
    # The read funnel: read(), search_read(), web_read(), web_search_read()
    # ------------------------------------------------------------------

    def _pdp_ui_mask_rows(self, rows):
        """Mask a list of ``{field: value}`` dicts in place and return it."""
        if not rows:
            return rows
        plan = self._pdp_ui_effective_plan()
        if not plan:
            return rows
        # Companions (display_name, complete_name, ...) inherit the mode of their source column.
        for source, companions in self._pdp_ui_mask_companions.items():
            if source in plan:
                for companion in companions:
                    plan.setdefault(companion, plan[source])
        for row in rows:
            for field_name, mode in plan.items():
                if row.get(field_name):
                    row[field_name] = self._pdp_ui_mask_value(
                        field_name, row[field_name], mode
                    )
        return rows

    def _read_format(self, fnames, load="_classic_read"):
        """The single funnel every formatted read passes through. See the module docstring.

        ``read()`` is deliberately NOT overridden any more: it calls this method, and so does
        ``search_read()``, which did not call ``read()`` and was the leak.
        """
        return self._pdp_ui_mask_rows(super()._read_format(fnames, load=load))

    # ------------------------------------------------------------------
    # The group funnel: formatted_read_group() and friends
    # ------------------------------------------------------------------

    @api.model
    def _pdp_ui_masked_in_specs(self, *spec_groups):
        """Return the masked column names named anywhere in the given specifications.

        Accepts strings, nested sequences and domains indifferently; anything that is not a string
        is stringified, because a value that merely *looks* like a masked field name causes a
        refusal, never a disclosure.
        """
        plan = self._pdp_ui_effective_plan()
        if not plan:
            return []

        def tokens(item):
            if item is None or item is False:
                return
            if isinstance(item, str):
                yield from _PDP_SPEC_TOKEN.findall(item)
            elif isinstance(item, (list, tuple, set, frozenset)):
                for element in item:
                    yield from tokens(element)
            elif isinstance(item, dict):
                for key, value in item.items():
                    yield from tokens(key)
                    yield from tokens(value)
            else:
                yield from _PDP_SPEC_TOKEN.findall(str(item))

        found = []
        for group in spec_groups:
            for token in tokens(group):
                if token in plan and token not in found:
                    found.append(token)
        return found

    @api.model
    def _pdp_ui_refuse_masked_grouping(self, *spec_groups):
        """Raise rather than aggregate a column the caller may not read. See module docstring."""
        masked = self._pdp_ui_masked_in_specs(*spec_groups)
        if not masked:
            return
        _logger.info(
            "custom_pdp_masking: refused a grouped read of %s on %s for uid %s",
            ", ".join(masked), self._name, self.env.uid,
        )
        raise AccessError(
            _(
                "You are not allowed to group or aggregate on %(columns)s. Those columns hold "
                "personal data and are masked for your account; grouping by them would return "
                "the values the mask exists to withhold. Ask for the 'PDP / Data Viewer' right "
                "if you need them.",
                columns=", ".join(masked),
            )
        )

    @api.model
    @api.readonly
    def formatted_read_group(
        self, domain, groupby=(), aggregates=(), having=(), offset=0, limit=None, order=None,
    ):
        self._pdp_ui_refuse_masked_grouping(groupby, aggregates, having, order)
        return super().formatted_read_group(
            domain, groupby=groupby, aggregates=aggregates, having=having,
            offset=offset, limit=limit, order=order,
        )

    @api.model
    @api.readonly
    def formatted_read_grouping_sets(
        self, domain, grouping_sets, aggregates=(), *, order=None,
    ):
        self._pdp_ui_refuse_masked_grouping(grouping_sets, aggregates, order)
        return super().formatted_read_grouping_sets(
            domain, grouping_sets, aggregates=aggregates, order=order,
        )

    @api.model
    @api.readonly
    def read_group(self, domain, fields, groupby, offset=0, limit=None, orderby=False, lazy=True):
        """Deprecated in Odoo 19, still reachable over RPC, and it builds its result straight from
        ``_read_group`` rather than through ``formatted_read_group``. Guarded separately for that
        reason."""
        self._pdp_ui_refuse_masked_grouping(fields, groupby, orderby)
        return super().read_group(
            domain, fields, groupby, offset=offset, limit=limit, orderby=orderby, lazy=lazy,
        )
