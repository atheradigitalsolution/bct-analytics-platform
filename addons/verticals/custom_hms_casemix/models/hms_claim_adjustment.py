# -*- coding: utf-8 -*-
"""Penyesuaian klaim — satu-satunya jalan mengubah angka yang sudah keluar.

=============================================================================
KEPUTUSAN: KLAIM TIDAK PERNAH DIEDIT SETELAH DIBAYAR; SELISIHNYA DIBUKUKAN
=============================================================================

Godaan terbesar pada modul klaim adalah membiarkan angka yang salah diperbaiki
di tempatnya. Setelah berkas dikirim ke penjamin, itu berarti pembukuan rumah
sakit dan pembukuan penjamin diam-diam berbeda, dan tidak ada satu pun baris
yang menjelaskan sejak kapan.

Karena itu ``hms.claim.action_mark_paid`` menolak pembayaran yang tidak sama
dengan nilai disetujui kecuali selisihnya sudah punya baris di sini, dan baris
itu sudah **diotorisasi**. Otorisasinya bukan formalitas: kerugian akibat
klaim kedaluwarsa atau dispute yang kalah adalah kerugian rumah sakit, dan
yang menanggungnya manajemen — bukan koder yang kebetulan membuka layarnya.

=============================================================================
KEPUTUSAN: SIAPA YANG BOLEH MENGOTORISASI DITENTUKAN SATU ANGKA DI PENGATURAN
=============================================================================

Menuntut tanda tangan manajemen untuk **setiap** selisih, termasuk selisih
pembulatan seratus rupiah, menghasilkan satu hal saja: antrian otorisasi yang
tidak pernah dibaca, lalu kebiasaan menandatangani tanpa melihat. Wewenangnya
karena itu berjenjang, dan batasnya diambil dari
``hms.settings.claim_adjustment_authorization_limit`` — tidak pernah ditulis
sebagai angka rupiah di dalam kode.

Mengapa **bukan** ``claim_variance_threshold`` yang sudah ada: parameter itu
mengukur selisih tarif rumah sakit terhadap tarif grouper dan menentukan kapan
sebuah klaim wajib direview empat mata. Dua besaran yang berbeda, dua
keputusan yang berbeda. Memakai satu kolom untuk keduanya berarti seseorang
yang menaikkan ambang review — pekerjaan casemix yang wajar — diam-diam ikut
menaikkan plafon kerugian yang boleh disahkan tanpa manajemen.

=============================================================================
KEPUTUSAN: PLAFON DIBACA SAAT OTORISASI, BUKAN DIBEKUKAN SAAT DIUSULKAN
=============================================================================

Berbeda dengan ``deadline_at`` dan ``grace_hours_applied`` yang sengaja beku,
plafon ini dibaca **hidup** pada detik tanda tangan diberikan, lalu nilainya
disalin ke ``authorization_limit_applied`` sebagai bukti. Alasannya: sebuah
tenggat adalah fakta kepatuhan yang bertanggal pada pelayanannya, sedangkan
plafon otorisasi adalah **pendelegasian wewenang** — dan wewenang berlaku
sebagaimana adanya pada saat seseorang menandatangani, bukan sebagaimana
adanya pada saat dokumennya diketik. Batas yang dicabut direksi hari ini tidak
boleh masih berlaku untuk usulan yang dibuat kemarin.

=============================================================================
KEPUTUSAN: BARIS INI APPEND-ONLY SETELAH DIOTORISASI
=============================================================================

Sesudah ``state = 'authorized'``, jumlah, jenis dan alasan tidak dapat diubah
lagi oleh siapa pun — termasuk oleh manajemen yang mengesahkannya. Koreksinya
selalu berupa **baris baru**. Kalau angka yang sudah disahkan boleh disunting,
seluruh gunanya hilang: ``action_mark_paid`` akan tetap cocok, laporan tetap
seimbang, dan tidak ada apa pun yang menunjukkan bahwa yang disahkan
sebenarnya angka lain.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

# Kolom yang masih boleh bergerak setelah otorisasi. Semuanya kolom
# keputusan, bukan kolom nilai.
MUTABLE_AFTER_AUTHORIZATION = {
    "state", "authorized_by_id", "authorized_at", "authorization_limit_applied",
    "write_date", "write_uid",
}

ADJUSTMENT_TYPES = [
    ("verification_gap", "Selisih Verifikasi Penjamin"),
    ("pending_reject", "Pending yang Berakhir Tidak Layak"),
    ("dispute_loss", "Dispute yang Tidak Dimenangkan"),
    ("expired", "Klaim Kedaluwarsa"),
    ("penalty", "Denda / Potongan"),
]


class HmsClaimAdjustment(models.Model):
    _name = "hms.claim.adjustment"
    _description = "Penyesuaian Klaim"
    _order = "id desc"

    name = fields.Char("Nomor", required=True, readonly=True, copy=False,
                       default=lambda s: _("Baru"), index=True)
    claim_id = fields.Many2one("hms.claim", "Klaim", required=True,
                               ondelete="restrict", index=True)
    encounter_id = fields.Many2one(related="claim_id.encounter_id", store=True, index=True)
    type = fields.Selection(ADJUSTMENT_TYPES, string="Jenis Penyesuaian",
                            required=True, default="verification_gap", index=True)
    currency_id = fields.Many2one(
        "res.currency", default=lambda s: s.env.company.currency_id, required=True,
    )
    amount = fields.Monetary(
        "Jumlah", required=True,
        help="Nilai yang TIDAK akan diterima rumah sakit. Selalu positif: "
             "arah kerugiannya sudah ditentukan jenis penyesuaian, dan angka "
             "bertanda campur pada satu kolom membuat penjumlahan laporan "
             "salah tanpa terlihat.",
    )
    reason = fields.Text("Alasan", required=True)
    state = fields.Selection(
        [("draft", "Diusulkan"), ("authorized", "Diotorisasi"), ("cancelled", "Dibatalkan")],
        default="draft", required=True, index=True,
    )
    proposed_by_id = fields.Many2one("res.users", "Diusulkan Oleh", readonly=True,
                                     default=lambda s: s.env.user)
    authorized_by_id = fields.Many2one("res.users", "Diotorisasi Oleh",
                                       readonly=True, copy=False)
    authorized_at = fields.Datetime("Waktu Otorisasi", readonly=True, copy=False)
    authorization_limit_applied = fields.Monetary(
        "Plafon Otorisasi Terpakai", readonly=True, copy=False,
        help="Nilai hms.settings.claim_adjustment_authorization_limit pada "
             "detik penyesuaian ini disahkan. Disimpan supaya keputusan lama "
             "tetap bisa dijelaskan setelah plafonnya diubah.",
    )
    requires_management = fields.Boolean(
        "Perlu Otorisasi Manajemen", compute="_compute_requires_management",
        help="Benar bila jumlahnya melewati plafon otorisasi casemix yang "
             "berlaku sekarang.",
    )
    company_id = fields.Many2one("res.company", default=lambda s: s.env.company, required=True)

    _name_uniq = models.Constraint("unique(name)", "Nomor penyesuaian klaim harus unik.")
    _amount_positive = models.Constraint(
        "CHECK (amount > 0)",
        "Jumlah penyesuaian harus lebih besar dari nol.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == _("Baru"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "hms.claim.adjustment") or "/"
        return super().create(vals_list)

    @api.depends("name", "type", "amount")
    def _compute_display_name(self):
        types = dict(ADJUSTMENT_TYPES)
        for rec in self:
            rec.display_name = f"{rec.name} — {types.get(rec.type, '')}"

    @api.constrains("amount", "claim_id")
    def _check_amount_within_claim(self):
        """Penyesuaian tidak boleh melebihi nilai yang pernah diajukan."""
        for rec in self:
            ceiling = max(rec.claim_id.hospital_bill_amount,
                          rec.claim_id.approved_amount,
                          rec.claim_id.grouped_tariff)
            if ceiling and rec.amount > ceiling:
                raise ValidationError(_(
                    "Penyesuaian %(a)s melebihi nilai klaim %(n)s (%(c)s). "
                    "Periksa kembali angkanya."
                ) % {"a": rec.amount, "n": rec.claim_id.name, "c": ceiling})

    @api.model
    def _authorization_limit(self):
        """Plafon otorisasi casemix, dari pengaturan. Nol = semua ke manajemen.

        Nol atau negatif sengaja diartikan "tidak ada plafon casemix sama
        sekali" dan bukan "plafon tak terbatas": sebuah parameter yang belum
        pernah diisi tidak boleh berarti setiap kerugian boleh disahkan tanpa
        manajemen.
        """
        value = self.env["hms.settings"].get_settings(
        ).claim_adjustment_authorization_limit
        return value if value and value > 0 else 0.0

    @api.depends("amount")
    def _compute_requires_management(self):
        limit = self._authorization_limit()
        for rec in self:
            rec.requires_management = not limit or rec.amount > limit

    def _check_authorizer(self):
        """Wewenang berjenjang, batasnya dari ``hms.settings``.

        Kerugian di atas plafon adalah kerugian rumah sakit, dan yang
        menanggungnya manajemen — bukan koder yang kebetulan membuka
        layarnya. Di bawah plafon, verifikator internal casemix mengesahkan
        sendiri: selisih kecil adalah pekerjaan hariannya, dan memaksanya naik
        ke direksi hanya melatih direksi menandatangani tanpa membaca.

        Koder yang mengusulkan tetap tidak boleh mengesahkan; pemisahan itu
        ada di ``action_authorize``, bukan di sini, karena bergantung pada
        record.
        """
        self.ensure_one()
        user = self.env.user
        if user.has_group("custom_hms_base.group_hms_manager"):
            return
        limit = self._authorization_limit()
        if (limit and self.amount <= limit
                and user.has_group("custom_hms_casemix.group_hms_casemix_verifier")):
            return
        if not limit:
            raise UserError(_(
                "Plafon otorisasi penyesuaian belum diatur, sehingga seluruh "
                "penyesuaian klaim harus disahkan manajemen (grup Manajemen "
                "Rumah Sakit)."
            ))
        raise UserError(_(
            "Penyesuaian %(n)s bernilai %(a)s, melewati plafon otorisasi "
            "casemix %(l)s, sehingga hanya dapat disahkan manajemen (grup "
            "Manajemen Rumah Sakit)."
        ) % {"n": self.name, "a": self.amount, "l": limit})

    def action_authorize(self):
        for rec in self:
            rec._check_authorizer()
            if rec.state != "draft":
                raise UserError(_("Penyesuaian %s sudah diputuskan.") % rec.name)
            if rec.proposed_by_id == self.env.user and rec.requires_management:
                # Pengusul boleh mengesahkan selisih rutin miliknya sendiri,
                # tetapi tidak kerugian yang seharusnya naik ke manajemen.
                # Tanpa pagar ini, seorang manajer yang mengusulkan sekaligus
                # mengesahkan membuat plafonnya tidak berarti apa-apa.
                raise UserError(_(
                    "Penyesuaian %s diusulkan oleh Anda sendiri dan nilainya "
                    "di atas plafon otorisasi casemix. Persetujuan yang "
                    "diberikan sendiri bukan persetujuan."
                ) % rec.name)
            rec.write({
                "state": "authorized",
                "authorized_by_id": self.env.uid,
                "authorized_at": fields.Datetime.now(),
                "authorization_limit_applied": self._authorization_limit(),
            })
        return True

    def action_cancel(self):
        for rec in self:
            rec._check_authorizer()
        for rec in self:
            if rec.state == "authorized" and rec.claim_id.state == "paid":
                raise UserError(_(
                    "Penyesuaian yang sudah dipakai menutup pembayaran klaim "
                    "%s tidak dapat dibatalkan."
                ) % rec.claim_id.name)
            rec.write({"state": "cancelled"})
        return True

    def write(self, vals):
        """Append-only: yang sudah disahkan tidak pernah disunting.

        Yang masih boleh bergerak hanyalah kolom keputusan itu sendiri —
        penulisan otorisasi, dan pembatalan lewat ``action_cancel``. Jumlah,
        jenis, alasan dan klaimnya beku. Koreksi atas angka yang keliru
        dilakukan dengan membatalkannya lalu menerbitkan baris baru, sehingga
        keduanya tetap terbaca di riwayat.
        """
        authorized = self.filtered(lambda r: r.state == "authorized")
        if authorized:
            forbidden = set(vals) - MUTABLE_AFTER_AUTHORIZATION
            if forbidden:
                raise UserError(_(
                    "Penyesuaian %(n)s sudah diotorisasi; %(f)s tidak dapat "
                    "diubah lagi. Terbitkan penyesuaian baru untuk "
                    "mengoreksinya — angka yang sudah disahkan tidak pernah "
                    "disunting di tempatnya."
                ) % {"n": ", ".join(authorized.mapped("name")),
                     "f": ", ".join(sorted(forbidden))})
        return super().write(vals)

    def unlink(self):
        if any(rec.state == "authorized" for rec in self):
            raise UserError(_(
                "Penyesuaian yang sudah diotorisasi tidak dapat dihapus."
            ))
        return super().unlink()
