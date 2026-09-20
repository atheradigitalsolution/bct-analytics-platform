# -*- coding: utf-8 -*-
"""Kontainer: identitas yang divalidasi, dan dua hitungan yang menahan uang.

VALIDASI ISO 6346
-----------------
Nomor kontainer adalah empat huruf, enam digit, satu digit periksa. Digit
periksanya bukan formalitas: nomor yang salah ketik lolos ke B/L, ke PIB, dan ke
sistem carrier, lalu ditemukan saat kontainer tidak bisa ditelusuri. Karena itu
validasinya berjalan di ORM — bukan hanya di layar — sehingga data yang masuk
lewat API ikut diperiksa.

DEMURRAGE VERSUS DETENSI
------------------------
Dua hal berbeda yang sering tertukar, dan tertukarnya mahal:

* **Demurrage** kontainer terlalu lama DI DALAM terminal melewati masa bebas.
  Dihitung dari tanggal bongkar sampai kontainer keluar gerbang.
* **Detensi** kontainer sudah KELUAR terminal dan terlambat dikembalikan ke
  depo. Dihitung dari keluar gerbang sampai masuk depo.

Keduanya dihitung PER KONTAINER, bukan per shipment, karena masa bebasnya
berjalan per kontainer dan satu shipment bisa punya sepuluh kontainer yang
keluar di hari berbeda.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# ISO 6346: huruf dipetakan ke angka mulai 10, MELEWATI setiap kelipatan 11.
# Itulah sebabnya tidak ada 11, 22, atau 33 di tabel ini — bukan salah ketik.
ISO6346_LETTER_VALUES = {
    "A": 10, "B": 12, "C": 13, "D": 14, "E": 15, "F": 16, "G": 17, "H": 18,
    "I": 19, "J": 20, "K": 21, "L": 23, "M": 24, "N": 25, "O": 26, "P": 27,
    "Q": 28, "R": 29, "S": 30, "T": 31, "U": 32, "V": 34, "W": 35, "X": 36,
    "Y": 37, "Z": 38,
}


def iso6346_check_digit(prefix_and_serial):
    """Digit periksa untuk 10 karakter pertama nomor kontainer.

    Mengembalikan None bila bentuknya sudah salah sebelum digit periksa relevan.
    """
    value = (prefix_and_serial or "").upper().strip()
    if len(value) != 10:
        return None
    owner, serial = value[:4], value[4:]
    if not owner.isalpha() or not serial.isdigit():
        return None
    total = 0
    for index, char in enumerate(owner):
        if char not in ISO6346_LETTER_VALUES:
            return None
        total += ISO6346_LETTER_VALUES[char] * (2 ** index)
    for index, char in enumerate(serial):
        total += int(char) * (2 ** (index + 4))
    return (total % 11) % 10


class LgxContainer(models.Model):
    _name = "lgx.container"
    _description = "Kontainer"
    _order = "shipment_id, container_no"
    _inherit = ["mail.thread"]
    _rec_name = "container_no"

    shipment_id = fields.Many2one("lgx.shipment", "Shipment", required=True,
                                  ondelete="cascade", index=True)
    job_id = fields.Many2one(related="shipment_id.job_id", store=True, index=True)
    company_id = fields.Many2one(related="shipment_id.company_id", store=True, index=True)
    container_no = fields.Char("Nomor Kontainer", required=True, index=True, tracking=True)
    seal_no = fields.Char("Nomor Segel")
    container_type_id = fields.Many2one("lgx.container.type", "Tipe", required=True)

    tare_weight = fields.Float("Berat Kosong (kg)")
    gross_weight = fields.Float("Berat Kotor (kg)")
    vgm_weight = fields.Float("VGM (kg)", help="Verified Gross Mass — wajib untuk ekspor laut.")
    vgm_method = fields.Selection(
        [("method1", "Metode 1 — penimbangan kontainer terisi"),
         ("method2", "Metode 2 — penjumlahan berat isi + tare")],
        string="Metode VGM",
    )
    vgm_date = fields.Date("Tanggal VGM")

    stuffing_date = fields.Date("Tanggal Stuffing")
    destuffing_date = fields.Date("Tanggal Destuffing")
    discharge_date = fields.Date(
        "Tanggal Bongkar", tracking=True,
        help="Titik awal perhitungan demurrage. Per kontainer, bukan per shipment.",
    )
    gate_out_date = fields.Date("Keluar Terminal", tracking=True,
                               help="Akhir demurrage, sekaligus awal detensi.")
    gate_in_date = fields.Date("Masuk Depo", tracking=True, help="Akhir detensi.")
    depot_id = fields.Many2one("lgx.location", "Depo Pengembalian",
                               domain="[('location_type','in',('depot','terminal','cfs'))]")

    free_days_demurrage = fields.Integer("Masa Bebas Demurrage (hari)")
    free_days_detention = fields.Integer("Masa Bebas Detensi (hari)")
    demurrage_days = fields.Integer("Hari Demurrage", compute="_compute_charge_days", store=True)
    detention_days = fields.Integer("Hari Detensi", compute="_compute_charge_days", store=True)
    demurrage_deadline = fields.Date("Batas Bebas Demurrage", compute="_compute_charge_days", store=True)
    detention_deadline = fields.Date("Batas Bebas Detensi", compute="_compute_charge_days", store=True)
    at_risk = fields.Boolean(
        "Berisiko", compute="_compute_charge_days", store=True,
        help="Masa bebas sudah lewat atau akan lewat dalam tiga hari, dan kontainer "
             "belum dikembalikan. Inilah daftar yang dibaca setiap pagi.",
    )
    is_returned = fields.Boolean(
        "Sudah Dikembalikan", compute="_compute_is_returned", store=True, readonly=False,
        help="Selama False, job TIDAK DAPAT diselesaikan. Kontainer yang belum "
             "kembali adalah tagihan carrier yang belum muncul.",
    )
    note = fields.Char("Catatan")

    _container_no_uniq = models.Constraint(
        "unique(shipment_id, container_no)",
        "Nomor kontainer ini sudah tercatat pada shipment yang sama.",
    )

    @api.constrains("container_no")
    def _check_container_no(self):
        """Validasi ISO 6346, dan sebutkan digit periksa yang BENAR.

        Menolak tanpa menyebut nilai yang benar memaksa orang menebak, dan
        tebakan berikutnya biasanya mengganti digit yang sudah benar.
        """
        for container in self:
            raw = (container.container_no or "").upper().replace(" ", "").replace("-", "")
            if not raw:
                continue
            if len(raw) != 11:
                raise ValidationError(_(
                    "Nomor kontainer '%s' harus 11 karakter: empat huruf, enam digit, "
                    "satu digit periksa.", container.container_no,
                ))
            expected = iso6346_check_digit(raw[:10])
            if expected is None:
                raise ValidationError(_(
                    "Nomor kontainer '%s' tidak berbentuk empat huruf diikuti enam digit.",
                    container.container_no,
                ))
            if not raw[10].isdigit() or int(raw[10]) != expected:
                raise ValidationError(_(
                    "Nomor kontainer '%s' gagal uji digit periksa ISO 6346. "
                    "Digit periksa yang benar untuk %s adalah %s.",
                    container.container_no, raw[:10], expected,
                ))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("container_no"):
                vals["container_no"] = vals["container_no"].upper().replace(" ", "").replace("-", "")
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("container_no"):
            vals["container_no"] = vals["container_no"].upper().replace(" ", "").replace("-", "")
        return super().write(vals)

    @api.depends("discharge_date", "gate_out_date", "gate_in_date",
                 "free_days_demurrage", "free_days_detention")
    def _compute_charge_days(self):
        """Hitungan BERJALAN, bukan hanya saat kontainer sudah kembali.

        Demurrage yang baru dihitung setelah kontainer kembali adalah demurrage
        yang baru ketahuan setelah tidak bisa ditagihkan lagi.
        """
        today = fields.Date.context_today(self)
        for container in self:
            dem_days = det_days = 0
            dem_deadline = det_deadline = False
            if container.discharge_date:
                dem_deadline = fields.Date.add(
                    container.discharge_date, days=container.free_days_demurrage or 0)
                end = container.gate_out_date or today
                dem_days = max(0, (end - dem_deadline).days)
            if container.gate_out_date:
                det_deadline = fields.Date.add(
                    container.gate_out_date, days=container.free_days_detention or 0)
                end = container.gate_in_date or today
                det_days = max(0, (end - det_deadline).days)
            container.demurrage_days = dem_days
            container.detention_days = det_days
            container.demurrage_deadline = dem_deadline
            container.detention_deadline = det_deadline
            warn_from = fields.Date.add(today, days=3)
            open_dem = bool(dem_deadline) and not container.gate_out_date and dem_deadline <= warn_from
            open_det = bool(det_deadline) and not container.gate_in_date and det_deadline <= warn_from
            container.at_risk = open_dem or open_det

    @api.depends("gate_in_date")
    def _compute_is_returned(self):
        for container in self:
            container.is_returned = bool(container.gate_in_date)

    @api.model
    def _cron_warn_containers_at_risk(self):
        """Kontainer yang melewati masa bebas menjadi aktivitas pada job-nya.

        Daftar di dashboard yang tidak menempel pada siapa pun adalah daftar yang
        tidak dibaca siapa pun.
        """
        at_risk = self.search([("at_risk", "=", True), ("is_returned", "=", False)])
        for job in at_risk.mapped("job_id"):
            containers = at_risk.filtered(lambda c: c.job_id == job)
            job.activity_schedule(
                "mail.mail_activity_data_todo",
                summary=_("%s kontainer melewati atau mendekati masa bebas", len(containers)),
                note=_(
                    "Kontainer: %s. Demurrage dan detensi yang tidak diteruskan ke pelanggan "
                    "sebelum job ditutup adalah kebocoran margin yang paling umum di forwarding.",
                    ", ".join(containers.mapped("container_no")),
                ),
                user_id=(job.operator_id or job.salesperson_id or self.env.user).id,
            )
        return len(at_risk)


class LgxPackage(models.Model):
    _name = "lgx.package"
    _description = "Kemasan Shipment"
    _order = "shipment_id, id"

    shipment_id = fields.Many2one("lgx.shipment", "Shipment", required=True,
                                  ondelete="cascade", index=True)
    container_id = fields.Many2one("lgx.container", "Kontainer")
    description = fields.Char("Uraian", required=True)
    package_type = fields.Selection(
        [("carton", "Karton"), ("pallet", "Pallet"), ("crate", "Peti Kayu"), ("drum", "Drum"),
         ("bag", "Karung"), ("bundle", "Bundel"), ("roll", "Roll"), ("other", "Lainnya")],
        string="Jenis", default="carton", required=True,
    )
    quantity = fields.Integer("Jumlah Koli", default=1, required=True)
    length_cm = fields.Float("Panjang (cm)")
    width_cm = fields.Float("Lebar (cm)")
    height_cm = fields.Float("Tinggi (cm)")
    gross_weight_kg = fields.Float("Berat Kotor (kg)")
    volume_cbm = fields.Float("Volume (CBM)", compute="_compute_volume", store=True, readonly=False)
    volume_cm3 = fields.Float("Volume (cm³)", compute="_compute_volume", store=True)
    marks = fields.Char("Marking")

    _quantity_positive = models.Constraint(
        "check(quantity > 0)", "Jumlah koli harus lebih dari nol.",
    )

    @api.depends("length_cm", "width_cm", "height_cm", "quantity")
    def _compute_volume(self):
        """`lgx.package` ADALAH pengganti product.packaging yang dihapus di Odoo 19.

        Jangan mencoba memakai model lama itu; ia tidak ada lagi, dan setiap
        contoh kode versi 17/18 yang menyebutnya akan gagal dalam diam saat
        di-import.
        """
        for package in self:
            cm3 = (package.length_cm or 0.0) * (package.width_cm or 0.0) * (package.height_cm or 0.0)
            package.volume_cm3 = cm3 * (package.quantity or 0)
            package.volume_cbm = package.volume_cm3 / 1_000_000.0
