# -*- coding: utf-8 -*-
{
    "name": "LGX — Integrasi NLE / INSW",
    "summary": "DO Online, SP2, dan penarikan status dokumen serta kontainer dari Customs API, "
               "seluruhnya lewat antrian dengan jejak pesan.",
    "description": """
LGX — NLE / INSW (custom_lgx_nle)
=================================

**Customs API adalah nilai tambah yang paling sering terlewat.** DO Online dan
SP2 menghemat pengetikan, tetapi yang benar-benar mengubah pekerjaan harian
adalah penarikan status: rekonsiliasi otomatis status dokumen pabean dan posisi
kontainer, tanpa staf operasi membuka portal berkali-kali sehari lalu menyalin
angkanya dengan tangan.

Status yang ditarik menjadi `lgx.milestone` dengan `source = 'nle'`. Sumbernya
disimpan justru karena penting: saat pelanggan menanyakan kenapa ETA berubah,
"siapa yang bilang" adalah setengah dari jawabannya.

**Job yang sudah `closed` tidak ikut ditarik.** Menarik status dokumen pada job
yang bukunya sudah tutup hanya menghasilkan perubahan yang tidak boleh lagi
memengaruhi apa pun — dan cron yang menyentuh periode tertutup adalah cron yang
suatu saat mengubah angka yang sudah dilaporkan.

⚠ `id_platform` dan API key produksi diperoleh lewat REGISTRASI ke NLE. Itu
pekerjaan administratif klien, bukan pekerjaan kode, dan masuk daftar prasyarat
proyek. Sampai itu terbit, modul ini bekerja penuh terhadap `lgx-mock`.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Logistics/LGX",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["custom_lgx_ff", "queue_job"],
    "capability_tags": ["logistics", "nle", "insw", "do-online", "integration", "indonesia"],
    "data": [
        "security/ir.model.access.csv",
        "data/lgx_nle_data.xml",
        "views/res_config_settings_views.xml",
        "views/lgx_nle_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
