# -*- coding: utf-8 -*-
"""Katalog pemeriksaan radiologi.

Sebelum modul ini, modalitas, regio dan kebutuhan kontras diketik ulang pada
setiap ekspertise sebagai teks/boolean bebas. Akibatnya "Thorax PA", "thorax
pa" dan "Ro Thorax" adalah tiga pemeriksaan berbeda bagi mesin, dan tidak ada
tempat untuk menyimpan persiapan pasien maupun acuan dosis — dua hal yang
harus dibaca radiografer SEBELUM pasien masuk ruangan.

Katalog ini bersifat ADITIF. ``hms.rad.report.exam_name``, ``modality`` dan
``body_part`` tidak dihapus dan tidak berubah makna: ekspertise yang dibuat
tanpa entri katalog tetap sah, dan nilai yang sudah tersimpan tidak pernah
ditimpa. Yang ditambahkan hanyalah pengisian awal dari katalog ketika
``exam_id`` dipilih.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# Sumber tunggal daftar modalitas. ``hms.rad.report`` mengimpor konstanta yang
# sama supaya katalog dan ekspertise tidak bisa menyimpang satu sama lain.
MODALITIES = [
    ("xray", "Radiografi (X-Ray)"),
    ("usg", "Ultrasonografi"),
    ("ct", "CT Scan"),
    ("mri", "MRI"),
    ("mammo", "Mamografi"),
    ("fluoro", "Fluoroskopi"),
    ("panoramic", "Panoramik"),
    ("other", "Lainnya"),
]


class HmsRadExam(models.Model):
    _name = "hms.rad.exam"
    _description = "Katalog Pemeriksaan Radiologi"
    _order = "modality, code"
    _rec_names_search = ["code", "name"]

    code = fields.Char("Kode", required=True, index=True)
    name = fields.Char("Nama Pemeriksaan", required=True)
    tariff_id = fields.Many2one(
        "hms.tariff", "Item Tarif", required=True, index=True, ondelete="cascade",
        help="Tarif yang dipesan dokter. Saat baris order radiologi dibuat, "
             "ekspertisenya langsung memakai katalog tarif ini.",
    )
    modality = fields.Selection(MODALITIES, "Modalitas", required=True, default="xray", index=True)
    body_part = fields.Char("Regio / Bagian Tubuh")
    requires_contrast = fields.Boolean(
        "Memerlukan Kontras",
        help="Menentukan nilai awal 'Menggunakan Kontras' pada ekspertise. "
             "Radiografer tetap boleh mengubahnya sesuai pelaksanaan nyata.",
    )
    preparation_note = fields.Text(
        "Persiapan Pasien",
        help="Mis. puasa 6 jam, kandung kemih penuh, lepas perhiasan logam. "
             "Dibaca petugas sebelum pasien dipanggil.",
    )
    estimated_minutes = fields.Integer(
        "Perkiraan Durasi (menit)",
        help="Dipakai untuk menata slot alat. Acuan, bukan batas keras.",
    )
    dose_reference = fields.Char(
        "Acuan Dosis (DRL)",
        help="Diagnostic Reference Level rujukan beserta satuannya, mis. "
             "'0,3 mGy (PA dewasa)' atau '7 mGy·cm'. Disimpan sebagai teks "
             "karena satuannya berbeda per modalitas; angka tanpa satuan "
             "justru menyesatkan.",
    )
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint("unique(code)", "Kode pemeriksaan radiologi harus unik.")
    # Satu tarif aktif = satu entri katalog, supaya pengisian otomatis tidak
    # pernah bergantung pada urutan pencarian.
    _tariff_active_uniq = models.UniqueIndex("(tariff_id) WHERE active IS TRUE")

    @api.constrains("estimated_minutes")
    def _check_estimated_minutes(self):
        for rec in self:
            if rec.estimated_minutes < 0:
                raise ValidationError(_("Perkiraan durasi tidak boleh negatif."))

    @api.depends("code", "name")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"[{rec.code}] {rec.name}"

    def _report_defaults(self):
        """Nilai awal untuk ekspertise yang memakai katalog ini."""
        self.ensure_one()
        vals = {"modality": self.modality, "contrast_used": self.requires_contrast}
        if self.body_part:
            vals["body_part"] = self.body_part
        return vals
