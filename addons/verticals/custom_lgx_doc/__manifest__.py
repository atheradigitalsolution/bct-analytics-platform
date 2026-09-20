# -*- coding: utf-8 -*-
{
    "name": "LGX — Dokumen & Masa Berlaku",
    "summary": "Satu mesin peringatan masa berlaku untuk KIR, STNK, Kartu Pengawasan, SIM, "
               "sertifikat ahli kepabeanan dan izin usaha; plus checklist dokumen per jenis job.",
    "description": """
LGX — Dokumen (custom_lgx_doc)
==============================

**Satu mesin, bukan lima implementasi terpisah.** KIR, STNK, Kartu Pengawasan,
SIM, sertifikat Ahli Kepabeanan dan izin usaha adalah masalah yang sama: sebuah
tanggal yang kalau lewat membuat sesuatu tidak boleh beroperasi. Menulis lima
pemeriksaan terpisah berarti lima tempat yang dapat berbeda diam-diam, dan
perbedaan itu baru ketahuan saat salah satunya tidak pernah memperingatkan.

**Peringatan menjadi AKTIVITAS pada penanggung jawab, bukan hanya baris di
dashboard.** Daftar yang tidak menempel pada siapa pun adalah daftar yang tidak
dibaca siapa pun.

**Checklist dokumen MENGHALANGI milestone, bukan sekadar mengingatkan.** Dokumen
yang baru ketahuan kurang saat barang sudah di pelabuhan adalah demurrage yang
sudah berjalan.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Logistics/LGX",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["custom_lgx_job"],
    "capability_tags": ["logistics", "documents", "expiry", "compliance", "checklist"],
    "data": [
        "security/ir.model.access.csv",
        "security/lgx_doc_rules.xml",
        "data/lgx_doc_data.xml",
        "views/lgx_document_views.xml",
        "views/lgx_doc_menus.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
