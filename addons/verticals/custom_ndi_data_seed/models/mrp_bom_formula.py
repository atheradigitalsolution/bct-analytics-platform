# -*- coding: utf-8 -*-
"""Jejak formulasi berbasis persen di balik ``mrp.bom``.

``mrp.bom`` menyimpan kebutuhan bahan sebagai kuantitas absolut per batch
(``mrp.bom.line.product_qty``). Formulasi pabrik pakan tidak ditulis begitu: ia
ditulis sebagai persentase yang berjumlah 100, dan angka kilogram adalah
turunannya terhadap ukuran batch. Sekali dikonversi ke kilogram, persentasenya
hilang — dan bersamanya hilang pula kemampuan menjawab "berapa persen jagung di
BR-1?" tanpa membagi ulang secara manual terhadap ukuran batch yang, pada MO
non-standar, bukan 5.000 KG.

Karena itu persen aslinya disimpan, bukan dihitung ulang. ``custom_ndi_mrp_formula``
(konversi otomatis persen -> kilogram saat ukuran batch berubah) belum dibangun;
sampai modul itu ada, kolom-kolom ini adalah satu-satunya tempat jejak formulasi
hidup, dan sample data harus bisa memperagakan bahwa resepnya memang berbasis
persentase.

Kolomnya diumumkan di sini dan bukan di ``custom_ndi_master`` karena ia melayani
lapisan produksi, bukan lapisan master produk; ketika ``custom_ndi_mrp_formula``
dibangun, definisi ini pindah ke sana beserta migrasinya. Ketiganya sudah
diklasifikasi ``internal`` di ``custom_pdp_core``.
"""

from odoo import fields, models


class MrpBom(models.Model):
    _inherit = "mrp.bom"

    ndi_batch_standar_kg = fields.Float(
        string="Batch Standar (KG)",
        digits="Product Unit",
        help="Ukuran batch yang dipakai saat persentase formula dikonversi menjadi "
             "kuantitas baris BOM. Pembagi yang benar untuk memulihkan persentase.",
    )
    ndi_formula_note = fields.Text(
        string="Formula (%)",
        help="Formulasi asli dalam persen, apa adanya dari dokumen formulasi. "
             "Disimpan supaya konversi ke kilogram tidak menghapus sumbernya.",
    )


class MrpBomLine(models.Model):
    _inherit = "mrp.bom.line"

    ndi_persen = fields.Float(
        string="Persen Formula",
        digits=(16, 4),
        help="Porsi bahan ini dalam formula, dalam persen terhadap total 100. "
             "0 untuk baris kemasan, yang bukan bagian dari formula bahan.",
    )
