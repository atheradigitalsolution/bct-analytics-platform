# -*- coding: utf-8 -*-
{
    "name": "LGX — Kepabeanan",
    "summary": "Deklarasi PIB/PEB dan dokumen TPB, HS code BTKI, perhitungan BM/PPN impor/PPh 22, "
               "Ahli Kepabeanan bersertifikat, jaminan transaksional, dan eksposur PPJK.",
    "description": """
LGX — Kepabeanan (custom_lgx_customs)
=====================================

**Identitas prinsipal memakai NIB + NPWP + jenis akses, bukan NIK.** PMK
219/2019 mengganti konsep NIK/NP PPJK dengan "Akses Kepabeanan" yang melekat
pada NIB dari OSS dan NPWP. Modul ini sengaja TIDAK menyediakan field "NIK
Kepabeanan", dan tidak boleh ditambahkan kemudian.

**Jaminan adalah entitas transaksional, bukan atribut master PPJK.** Customs
bond bukan syarat izin; ia melekat per transaksi atau per fasilitas (impor
sementara, BC 2.6.1, keberatan). Memodelkannya sebagai field pada master PPJK
akan membuat jaminan yang sudah dapat ditarik tidak pernah ditarik, karena tidak
ada record yang jatuh tempo.

**Eksposur PPJK adalah risiko finansial nyata.** PMK 219/2019 Pasal 24 ayat 2:
PPJK bertanggung jawab atas bea masuk terutang bila importir tidak ditemukan.
Karena itu total nilai deklarasi berjalan per prinsipal adalah laporan, bukan
sekadar angka yang bisa dihitung kalau diminta.

**Bea masuk dan pajak impor masuk job sebagai TALANGAN**, bukan sebagai biaya.
Ia dibayarkan atas nama importir dan ditagihkan kembali apa adanya; melewatkannya
ke laba rugi akan menggelembungkan HPP berkali lipat pada job impor.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Logistics/LGX",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["custom_lgx_ff"],
    "capability_tags": ["logistics", "customs", "ppjk", "indonesia", "import-duty", "btki"],
    "data": [
        "security/ir.model.access.csv",
        "security/lgx_customs_rules.xml",
        "data/lgx_customs_sequence.xml",
        "data/lgx_hs_code_data.xml",
        "views/lgx_customs_declaration_views.xml",
        "views/lgx_customs_master_views.xml",
        "views/lgx_customs_menus.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
