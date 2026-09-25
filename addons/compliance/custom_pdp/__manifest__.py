{
    "name": "PDP - Classification Registry & Taxonomy",
    "summary": "UU 27/2022 data classification: the frozen per-column registry plus the semantic taxonomy.",
    "description": """
PDP
===

The single PDP classification module, merging the former ``custom_pdp_core``
(per-column registry) and ``custom_pdp_taxonomy`` (semantic dictionary).

Implements frozen contract 01 (``docs/agents/contracts/01-classification.md``).

* ``pdp.field.classification`` - one row per physical database column, carrying exactly one of
  the five frozen PDP classes ``public | internal | personal | sensitive | secret``. The CDC
  loader reads this registry over JSON-RPC at startup and refuses to start when a column it is
  about to extract carries no classification. Unclassified is a hard failure, never a silent
  default to ``public``. This registry is CANONICAL.
* ``pdp.classification`` - the human-facing vocabulary (``pii``, ``financial``, ``child`` ...)
  with behavioural flags for consent, masking and retention, used by the compliance suite
  (audit, consent, DSAR, retention). Every code rolls up to one frozen class via ``pdp_class``.
* ``ir.model.fields.x_pdp_classification_id`` - a derived projection of the registry, kept in
  sync by ``_pdp_post_sync()`` on every upgrade; the tag wizard writes through to the registry.
""",
    "version": "19.0.2.0.0",
    "category": "Custom Platform/Compliance/PDP",
    "author": "ATHERA Analytics Platform",
    "website": "https://example.invalid/bct",
    "license": "LGPL-3",
    "depends": ["custom_core"],
    "capability_tags": ["pdp", "compliance", "data-classification"],
    "data": [
        "security/pdp_groups.xml",
        "security/pdp_security.xml",
        "security/ir.model.access.csv",
        "data/pdp.field.classification.csv",
        "data/pdp_classification_data.xml",
        "views/pdp_field_classification_views.xml",
        "views/pdp_classification_views.xml",
        "views/ir_model_fields_views.xml",
        "wizards/pdp_tag_fields_wizard_views.xml",
        "views/menu_views.xml",
        "data/pdp_sync.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
