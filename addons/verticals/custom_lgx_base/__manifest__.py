# -*- coding: utf-8 -*-
{
    "name": "LGX — Master Data Logistik",
    "summary": "Fondasi vertical logistik ATHERA: simpul jaringan, kode charge, "
               "tipe kontainer, kantor pabean, jenis dokumen, template milestone, "
               "cabang/NITKU, dan delapan privilege terpisah.",
    "description": """
LGX — Master Data (custom_lgx_base)
===================================

Lapisan master untuk vertical logistik (freight forwarding, trucking, gudang
3PL). Semua modul ``custom_lgx_*`` lain berdiri di atas modul ini.

**Cabang adalah ``operating.unit``, bukan model baru.** Keputusan A24 di
spesifikasi. ``custom_operating_unit`` sudah menstempel ``operating_unit_id``
pada ``account.move``, ``sale.order`` dan ``stock.picking`` berikut record
rule-nya, jadi dimensi cabang untuk faktur dan laporan pajak sudah ada. Modul
ini hanya menambahkan identitas pajak cabang: NITKU 22 digit, NPWP 16 digit,
kantor pabean, dan KBLI dua versi.

**Kode charge adalah tempat pengetahuan pajak disimpan sekali.**
``lgx.charge.code`` membawa ``default_nature`` (service / disbursement),
``is_freight_charge`` (syarat PPN besaran tertentu), ``vat_treatment`` dan
``default_wht_type``. Setiap baris biaya pada job mewarisi keempatnya, sehingga
perlakuan pajak tidak pernah diketik ulang per transaksi.

**Delapan privilege terpisah.** Odoo 19 merender semua grup yang berbagi satu
``res.groups.privilege`` sebagai dropdown pilih-satu; satu privilege untuk semua
peran akan membuat dispatcher kehilangan hak gudangnya begitu form user
disimpan.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Logistics/LGX",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": [
        "base",
        "mail",
        "contacts",
        "uom",
        "product",
        "account",
        "custom_doc_numbering",
        "custom_operating_unit",
    ],
    "capability_tags": [
        "logistics", "freight-forwarding", "trucking", "warehouse-3pl",
        "master-data", "indonesia",
    ],
    "data": [
        "security/lgx_groups.xml",
        "security/ir.model.access.csv",
        "security/lgx_rules.xml",
        "data/lgx_config_parameter.xml",
        "data/lgx_uom_data.xml",
        "data/lgx_container_type_data.xml",
        "data/lgx_customs_office_data.xml",
        "data/lgx_location_data.xml",
        "data/lgx_charge_code_data.xml",
        "data/lgx_document_type_data.xml",
        "data/lgx_milestone_type_data.xml",
        "data/lgx_kbli_data.xml",
        "views/lgx_location_views.xml",
        "views/lgx_charge_code_views.xml",
        "views/lgx_reference_views.xml",
        "views/lgx_kbli_views.xml",
        "views/lgx_integration_views.xml",
        "views/res_partner_views.xml",
        "views/operating_unit_views.xml",
        "views/lgx_kmk_rate_views.xml",
        "views/lgx_menus.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
