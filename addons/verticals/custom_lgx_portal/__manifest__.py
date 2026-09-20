# -*- coding: utf-8 -*-
{
    "name": "LGX — Portal Pelanggan",
    "summary": "Pelacakan kiriman, unduh dokumen yang tercatat, dan pengajuan booking — "
               "dengan tautan pelacakan publik yang bertanda tangan dan kedaluwarsa.",
    "description": """
LGX — Portal Pelanggan (custom_lgx_portal)
==========================================

**Hanya milestone `is_customer_visible` yang tampil, dan itu ditegakkan di DUA
lapis.** Controller menyaringnya, dan record rule menyaringnya lagi. Bukan
karena paranoid: template QWeb adalah tempat orang menambahkan `t-foreach` baru
tanpa memikirkan siapa yang membacanya, dan satu baris ceroboh di sana akan
membocorkan milestone internal — "biaya vendor diterima", "kontainer kena
detensi" — ke layar pelanggan. Lapis kedua membuat kecerobohan itu tidak cukup.

**Setiap pengunduhan dokumen dicatat.** Bukan untuk mengawasi pelanggan,
melainkan karena pertanyaan "apakah mereka sudah menerima B/L-nya" muncul setiap
minggu di operasi, dan menjawabnya dengan tebakan adalah cara dokumen dikirim
ulang berkali-kali lewat surel.

**Tautan pelacakan publik bertanda tangan DAN kedaluwarsa.** Odoo menyediakan
`access_token` pada `portal.mixin`, tetapi token itu berlaku selamanya. Nomor
B/L beredar di rantai pasok — di surel, di grup pesan, di berkas Excel yang
diteruskan — dan tautan abadi yang ikut beredar bersamanya adalah pintu yang
tidak pernah tertutup. Karena itu modul ini memakai tokennya sendiri dengan masa
berlaku yang dapat dikonfigurasi.

**Booking dari portal membuat job `draft`, bukan job yang langsung berjalan.**
Pelanggan menerima nomor referensi seketika, staf operasi menerima aktivitas
terjadwal, dan tidak ada pekerjaan yang masuk antrian operasi tanpa seseorang
mengonfirmasinya.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Logistics/LGX",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["custom_lgx_job", "custom_lgx_ff", "custom_lgx_doc", "portal"],
    "capability_tags": ["logistics", "portal", "tracking", "customer-self-service"],
    "data": [
        "security/ir.model.access.csv",
        "security/lgx_portal_rules.xml",
        "data/lgx_portal_data.xml",
        "views/portal_templates.xml",
        "views/lgx_job_portal_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
