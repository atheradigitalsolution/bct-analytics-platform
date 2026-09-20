# -*- coding: utf-8 -*-
"""Master jenis diet.

``hms.admission.diet`` adalah kolom teks bebas, dan tetap begitu — 16 tes
rawat inap dan laporan serah terima SBAR membacanya. Yang ditambahkan di
sini adalah masternya, karena teks bebas tidak bisa menjawab tiga pertanyaan
yang justru harus dijawab dapur gizi setiap pagi: berapa porsi per jenis
diet, mana yang terapeutik (dan karena itu tidak boleh ditukar), dan apa
pantangannya.

"DM 1700 kkal", "dm 1700", dan "Diet DM" adalah tiga jenis diet berbeda bagi
mesin, dan itulah kenapa rekap porsi tidak pernah bisa dibuat dari kolom
teks.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

DIET_CATEGORIES = [
    ("regular", "Biasa"),
    ("soft", "Lunak"),
    ("liquid", "Cair"),
    ("special", "Khusus / Terapeutik"),
]

DIET_TEXTURES = [
    ("regular", "Biasa"),
    ("chopped", "Cincang"),
    ("minced", "Saring / Halus"),
    ("pureed", "Bubur / Puree"),
    ("liquid", "Cair"),
    ("enteral", "Enteral (Sonde)"),
    ("npo", "Puasa (Nil per Oral)"),
]


class HmsDietType(models.Model):
    _name = "hms.diet.type"
    _description = "Jenis Diet"
    _order = "category, code"
    _rec_names_search = ["code", "name"]

    code = fields.Char("Kode", required=True, index=True)
    name = fields.Char("Nama Diet", required=True)
    category = fields.Selection(
        DIET_CATEGORIES, "Kategori", required=True, default="regular", index=True,
    )
    texture = fields.Selection(
        DIET_TEXTURES, "Tekstur", required=True, default="regular",
        help="Bentuk makanan yang disajikan. Menentukan alur penyiapan di "
             "dapur, dan pada pasien disfagia menentukan keselamatannya.",
    )
    energy_kcal = fields.Float("Energi (kkal)", digits=(16, 0))
    protein_g = fields.Float("Protein (g)", digits=(16, 1))
    restrictions = fields.Text(
        "Pantangan",
        help="Bahan yang tidak boleh diberikan, mis. garam, gula sederhana, "
             "purin tinggi. Dibaca petugas dapur, bukan hanya ahli gizi.",
    )
    is_therapeutic = fields.Boolean(
        "Diet Terapeutik",
        help="Diet yang merupakan bagian dari terapi, mis. DM, rendah garam, "
             "rendah protein. Tidak boleh ditukar tanpa perintah dokter/ahli gizi.",
    )
    note = fields.Text("Catatan")
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint("unique(code)", "Kode jenis diet harus unik.")

    @api.constrains("energy_kcal", "protein_g")
    def _check_nutrition(self):
        for rec in self:
            if rec.energy_kcal < 0 or rec.protein_g < 0:
                raise ValidationError(_("Nilai energi dan protein tidak boleh negatif."))

    @api.constrains("category", "is_therapeutic")
    def _check_therapeutic(self):
        """Diet khusus yang tidak ditandai terapeutik hampir selalu salah entri.

        Dijadikan galat, bukan peringatan: penanda terapeutik inilah yang
        nanti mencegah porsi ditukar di dapur.
        """
        for rec in self:
            if rec.category == "special" and not rec.is_therapeutic:
                raise ValidationError(
                    _("Diet '%s' berkategori khusus tetapi tidak ditandai terapeutik.")
                    % rec.name
                )

    @api.depends("code", "name")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"[{rec.code}] {rec.name}"


class HmsAdmission(models.Model):
    _inherit = "hms.admission"

    diet_type_id = fields.Many2one(
        "hms.diet.type", "Jenis Diet (Master)", index=True,
        help="Diet yang sedang berjalan untuk pasien ini. Kolom teks 'Diet' "
             "tetap ada dan tidak berubah artinya — ia menampung catatan "
             "bebas seperti jadwal atau modifikasi porsi.",
    )


class HmsOrderLine(models.Model):
    _inherit = "hms.order.line"

    # KENAPA JENIS DIET MENEMPEL DI DUA TEMPAT
    # ----------------------------------------
    # Jalur yang dipilih BUKAN salah satu, melainkan keduanya, karena
    # keduanya memang kejadian yang berbeda:
    #
    #   * ``hms.order`` bertipe ``diet`` adalah PERINTAH dokter. Ia melekat
    #     pada kunjungan, punya tarif, masuk penagihan, dan tunduk pada
    #     kewenangan klinis. Di sinilah "pasien ini berdiet DM 1700 kkal"
    #     menjadi keputusan medis yang tercatat.
    #   * ``hms.unit.request`` ke unit gizi adalah PERMINTAAN pelaksanaan.
    #     Ia melekat pada admisi dan nurse station, punya prioritas dan
    #     status terbuka/selesai, dan terjadi berulang kali (per waktu makan,
    #     per shift) untuk satu perintah diet yang sama.
    #
    # Menaruh jenis diet hanya di order membuat dapur tidak pernah menerima
    # tiketnya; menaruhnya hanya di permintaan unit membuat diet berubah
    # tanpa perintah dokter dan tanpa tagihan. Penyambungnya ada di
    # ``custom_hms_nursing``: ``action_request_nutrition()`` pada baris order.
    diet_type_id = fields.Many2one(
        "hms.diet.type", "Jenis Diet", index=True,
        help="Diet yang diperintahkan. Hanya berlaku pada baris order "
             "bertipe Diet / Gizi.",
    )

    @api.constrains("diet_type_id", "order_type")
    def _check_diet_type(self):
        for line in self:
            if line.diet_type_id and line.order_type != "diet":
                raise ValidationError(
                    _("Jenis diet hanya dapat diisi pada baris order bertipe Diet / Gizi.")
                )
