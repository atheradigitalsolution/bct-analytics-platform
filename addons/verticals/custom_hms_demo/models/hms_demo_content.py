# -*- coding: utf-8 -*-
"""Isi demo klinis: katalog penunjang, episode klaim, rekam medis, keselamatan.

KENAPA BERKAS INI ADA
---------------------
``hms_demo_builder.py`` membangun *rumah sakitnya* — poli, dokter, bed, obat,
tarif. Yang tidak dibangunnya adalah *riwayat*: klaim yang sudah berjalan
beberapa bulan, temuan KLPCM yang lewat tenggat, insiden yang sudah digrading,
hasil kritis yang sudah (dan belum) diakui. Layar yang benar tetapi kosong
tidak memperagakan apa pun, jadi di sinilah isinya dibuat.

IDEMPOTENSI: JANGKAR ``ir.model.data``, BUKAN TEBAKAN DOMAIN
------------------------------------------------------------
Master data punya kode unik, jadi ``_get_or_create`` lewat domain sudah cukup.
Sebuah *episode* tidak punya kode unik: dua kunjungan pasien yang sama di poli
yang sama pada bulan yang sama adalah dua kejadian yang sah berbeda. Menebak
keunikannya dari domain akan salah pada kedua arah — kadang menggandakan,
kadang menolak data yang memang harus ada.

Karena itu setiap episode diberi jangkar ``ir.model.data`` dengan nama yang
tetap. Modulnya sengaja **bukan** ``custom_hms_demo`` melainkan
``__simrs_demo__``: di akhir pembaruan modul, Odoo menghapus baris
``ir.model.data`` milik modul yang sedang diperbarui yang tidak tersentuh oleh
berkas datanya (``_process_end``). Jangkar yang lahir dari kode tidak pernah
tersentuh, sehingga akan dihapus setiap kali modul di-``-u`` — dan bersamanya
hilang pula idempotensinya. ``noupdate=True`` dipasang sebagai lapis kedua.

PAGAR ``*_demo``
----------------
``seed_all()`` memanggil ``_assert_demo_database()`` lebih dulu, persis
sekeras ``post_init_hook``. Jalur baru tidak boleh menjadi pintu belakang
untuk memasang pasien demo ke database produksi.
"""
import logging
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

ANCHOR_MODULE = "__simrs_demo__"

# --- katalog referensi ----------------------------------------------------
ICD10 = [
    ("A09.9", "Gastroenteritis dan kolitis infeksi, tidak spesifik",
     "Gastroenteritis and colitis of unspecified origin"),
    ("A91", "Demam berdarah dengue", "Dengue haemorrhagic fever"),
    ("D64.9", "Anemia, tidak spesifik", "Anaemia, unspecified"),
    ("E11.9", "Diabetes melitus tipe 2 tanpa komplikasi",
     "Type 2 diabetes mellitus without complications"),
    ("E87.6", "Hipokalemia", "Hypokalaemia"),
    ("I10", "Hipertensi esensial (primer)", "Essential (primary) hypertension"),
    ("I50.0", "Gagal jantung kongestif", "Congestive heart failure"),
    ("I63.9", "Infark serebri, tidak spesifik", "Cerebral infarction, unspecified"),
    ("J18.9", "Pneumonia, organisme tidak spesifik", "Pneumonia, unspecified organism"),
    ("J44.1", "PPOK dengan eksaserbasi akut",
     "Chronic obstructive pulmonary disease with acute exacerbation"),
    ("K29.7", "Gastritis, tidak spesifik", "Gastritis, unspecified"),
    ("K35.80", "Apendisitis akut, tidak spesifik", "Acute appendicitis, unspecified"),
    ("K80.2", "Batu kandung empedu tanpa kolesistitis",
     "Calculus of gallbladder without cholecystitis"),
    ("N18.5", "Penyakit ginjal kronik stadium 5", "Chronic kidney disease, stage 5"),
    ("N39.0", "Infeksi saluran kemih, lokasi tidak spesifik",
     "Urinary tract infection, site not specified"),
    ("R50.9", "Demam, tidak spesifik", "Fever, unspecified"),
    ("S06.0", "Komosio serebri", "Concussion"),
    ("W19", "Jatuh tidak spesifik", "Unspecified fall"),
]

ICD9 = [
    ("47.09", "Apendektomi lain", True, False),
    ("51.23", "Kolesistektomi laparoskopik", True, True),
    ("53.00", "Herniorafi inguinal unilateral", True, False),
    ("86.59", "Penjahitan kulit dan jaringan subkutan lain", False, False),
    ("87.44", "Radiografi toraks rutin", False, False),
    ("88.76", "Ultrasonografi abdomen", False, False),
    ("93.94", "Terapi nebulisasi", False, False),
    ("99.04", "Transfusi packed red cell", False, True),
]

# Tarif tambahan yang dibutuhkan katalog penunjang dan jadwal tindakan.
EXTRA_TARIFFS = [
    # code, name, category, unit, price, duration_minutes, requires_consent
    ("LAB-KIMIA", "Kimia Darah (Profil Lipid & Glukosa)", "lab", "LAB", 165000, 0, False),
    ("LAB-GINJAL", "Fungsi Ginjal", "lab", "LAB", 120000, 0, False),
    ("LAB-HATI", "Fungsi Hati", "lab", "LAB", 140000, 0, False),
    ("LAB-ELEK", "Elektrolit", "lab", "LAB", 110000, 0, False),
    ("LAB-URIN", "Urinalisis", "lab", "LAB", 45000, 0, False),
    ("RAD-ABD3", "Rontgen Abdomen 3 Posisi", "rad", "RAD", 320000, 0, False),
    ("RAD-CTKEP", "CT Scan Kepala Non-Kontras", "rad", "RAD", 950000, 0, False),
    ("TND-APP", "Apendektomi", "procedure", "RANAP", 6500000, 90, True),
    ("TND-HERN", "Herniotomi", "procedure", "RANAP", 5800000, 75, True),
    ("TND-CHOL", "Kolesistektomi Laparoskopik", "procedure", "RANAP", 12500000, 120, True),
]

# Parameter lab baru. Panel lama (LAB-DL, LAB-GDS) TIDAK disentuh daftar
# parameternya supaya hasil skenario rawat jalan yang sudah diuji tidak
# bergeser.
EXTRA_LAB_PARAMETERS = [
    # code, name, uom, specimen, ranges [(gender, age_from, age_to, low, high, clow, chigh)]
    ("CHOL", "Kolesterol Total", "mg/dL", "Serum", [(None, 0, 0, 0.0, 200.0, 0.0, 400.0)]),
    ("TG", "Trigliserida", "mg/dL", "Serum", [(None, 0, 0, 0.0, 150.0, 0.0, 600.0)]),
    ("GDP", "Gula Darah Puasa", "mg/dL", "Serum", [(None, 0, 0, 70.0, 100.0, 45.0, 400.0)]),
    ("UREUM", "Ureum", "mg/dL", "Serum", [(None, 0, 0, 15.0, 45.0, 0.0, 200.0)]),
    ("KREAT", "Kreatinin", "mg/dL", "Serum", [
        ("male", 15, 0, 0.7, 1.3, 0.0, 8.0),
        ("female", 15, 0, 0.6, 1.1, 0.0, 8.0),
        (None, 0, 14, 0.3, 0.7, 0.0, 6.0),
    ]),
    ("UA", "Asam Urat", "mg/dL", "Serum", [
        ("male", 15, 0, 3.4, 7.0, 0.0, 15.0),
        ("female", 15, 0, 2.4, 5.7, 0.0, 15.0),
    ]),
    ("SGOT", "SGOT (AST)", "U/L", "Serum", [(None, 0, 0, 0.0, 40.0, 0.0, 400.0)]),
    ("SGPT", "SGPT (ALT)", "U/L", "Serum", [(None, 0, 0, 0.0, 41.0, 0.0, 400.0)]),
    ("BILT", "Bilirubin Total", "mg/dL", "Serum", [(None, 0, 0, 0.1, 1.2, 0.0, 15.0)]),
    ("ALB", "Albumin", "g/dL", "Serum", [(None, 0, 0, 3.5, 5.2, 1.5, 7.0)]),
    ("NA", "Natrium", "mmol/L", "Serum", [(None, 0, 0, 135.0, 145.0, 120.0, 160.0)]),
    ("K", "Kalium", "mmol/L", "Serum", [(None, 0, 0, 3.5, 5.1, 2.5, 6.5)]),
    ("CL", "Klorida", "mmol/L", "Serum", [(None, 0, 0, 98.0, 107.0, 80.0, 120.0)]),
    ("UR-PROT", "Protein Urin", "mg/dL", "Urin sewaktu", [(None, 0, 0, 0.0, 15.0, 0.0, 300.0)]),
    ("UR-GLU", "Glukosa Urin", "mg/dL", "Urin sewaktu", [(None, 0, 0, 0.0, 15.0, 0.0, 500.0)]),
    ("UR-LEU", "Leukosit Urin", "/LPB", "Urin sewaktu", [(None, 0, 0, 0.0, 5.0, 0.0, 100.0)]),
    ("UR-ERI", "Eritrosit Urin", "/LPB", "Urin sewaktu", [(None, 0, 0, 0.0, 3.0, 0.0, 100.0)]),
]

# Katalog hms.lab.test. LAB-WIDAL sengaja TIDAK dikatalogkan: ia bukti hidup
# bahwa jalur lama (hms.lab.parameter.tariff_ids) masih dipakai apa adanya
# untuk tarif yang belum berkatalog. LAB-DL dan LAB-GDS dikatalogkan dengan
# parameter yang PERSIS SAMA dengan M2M lamanya, sehingga menyalakan katalog
# tidak mengubah satu baris hasil pun.
LAB_TESTS = [
    # code, name, tariff, parameters, panel, specimen, container, tat, note
    ("LT-DL", "Darah Lengkap", "LAB-DL", ["HB", "WBC", "PLT", "HCT"], True,
     "Darah vena EDTA", "Tutup ungu (EDTA) 3 mL", 60, False),
    ("LT-GDS", "Gula Darah Sewaktu", "LAB-GDS", ["GDS"], False,
     "Darah vena / kapiler", "Tutup abu-abu (NaF) 2 mL", 30, False),
    ("LT-KIMIA", "Kimia Darah (Profil Lipid & Glukosa)", "LAB-KIMIA",
     ["GDP", "CHOL", "TG", "UA"], True, "Serum", "Tutup kuning (SST) 5 mL", 180,
     "Puasa 10-12 jam, air putih diperbolehkan."),
    ("LT-GINJAL", "Fungsi Ginjal", "LAB-GINJAL", ["UREUM", "KREAT", "UA"], True,
     "Serum", "Tutup kuning (SST) 5 mL", 120, False),
    ("LT-HATI", "Fungsi Hati", "LAB-HATI", ["SGOT", "SGPT", "BILT", "ALB"], True,
     "Serum", "Tutup kuning (SST) 5 mL", 120, False),
    ("LT-ELEK", "Elektrolit", "LAB-ELEK", ["NA", "K", "CL"], True,
     "Serum", "Tutup kuning (SST) 3 mL", 60, False),
    ("LT-URIN", "Urinalisis", "LAB-URIN", ["UR-PROT", "UR-GLU", "UR-LEU", "UR-ERI"], True,
     "Urin sewaktu", "Pot urin steril 20 mL", 45,
     "Urin porsi tengah, ditampung setelah pembersihan area genital."),
]

RAD_EXAMS = [
    # code, name, tariff, modality, body_part, contrast, minutes, dose, preparation
    ("RX-THX", "Thorax PA", "RAD-THX", "xray", "Toraks", False, 10, "0,3 mGy (PA dewasa)",
     "Lepas perhiasan logam dan pakaian berkancing logam. Tahan napas saat eksposi."),
    ("RX-ABD3", "Abdomen 3 Posisi", "RAD-ABD3", "xray", "Abdomen", False, 20,
     "4,0 mGy (AP dewasa)",
     "Pasien dapat berdiri/LLD. Beri tahu bila hamil atau kemungkinan hamil."),
    ("CT-KEP", "CT Kepala Non-Kontras", "RAD-CTKEP", "ct", "Kepala", False, 15,
     "60 mGy·cm (CTDIvol dewasa)",
     "Lepas jepit rambut, anting dan gigi palsu. Tidak perlu puasa."),
    ("US-ABD", "USG Abdomen", "RAD-USG", "usg", "Abdomen", False, 25, False,
     "Puasa 6 jam. Kandung kemih penuh bila menilai buli dan ginekologi."),
]

DIET_TYPES = [
    # code, name, category, texture, kcal, protein, therapeutic, restrictions
    ("DIET-NB", "Nasi Biasa", "regular", "regular", 2100, 60.0, False, False),
    ("DIET-NT", "Nasi Tim", "soft", "chopped", 1900, 55.0, False, False),
    ("DIET-BB", "Bubur", "soft", "pureed", 1700, 50.0, False, False),
    ("DIET-BS", "Bubur Saring", "soft", "minced", 1500, 45.0, False,
     "Tanpa serat kasar, tanpa bumbu tajam."),
    ("DIET-CAIR", "Makanan Cair", "liquid", "liquid", 1200, 40.0, False,
     "Tanpa makanan padat. Diberikan bertahap 6-8 kali sehari."),
    ("DIET-SONDE", "Cair Enteral (Sonde)", "liquid", "enteral", 1500, 55.0, False,
     "Melalui NGT. Bilas selang dengan air matang setiap pemberian."),
    ("DIET-DM17", "DM 1700 kkal", "special", "regular", 1700, 60.0, True,
     "Tanpa gula sederhana, sirup, dan makanan manis. Jadwal makan 3x utama + 3x selingan."),
    ("DIET-RG", "Rendah Garam", "special", "regular", 1900, 55.0, True,
     "Natrium maksimal 2 g/hari. Tanpa garam meja, ikan asin, dan makanan olahan."),
    ("DIET-RP", "Rendah Protein", "special", "regular", 1800, 35.0, True,
     "Protein 0,6-0,8 g/kgBB. Batasi daging merah, kacang-kacangan, dan jeroan."),
]

CONSENT_TEMPLATES = [
    ("CONS-UMUM", "Persetujuan Umum (General Consent)", "general",
     "<p>Pasien menyetujui pelayanan kesehatan umum, penyimpanan dan pengolahan data "
     "rekam medis sesuai peraturan yang berlaku.</p>"),
    ("CONS-TIND", "Informed Consent Tindakan Kedokteran", "procedure",
     "<p>Pasien/keluarga telah menerima penjelasan mengenai diagnosis, tindakan yang "
     "diusulkan, tujuan, risiko, komplikasi, alternatif, dan prognosis; serta "
     "menyatakan persetujuan atas tindakan tersebut.</p>"),
    ("CONS-ANEST", "Persetujuan Tindakan Anestesi", "anesthesia",
     "<p>Pasien/keluarga menyetujui tindakan anestesi setelah menerima penjelasan "
     "mengenai jenis anestesi, risiko, dan penyulit yang mungkin terjadi.</p>"),
]


class HmsDemoBuilder(models.AbstractModel):
    """Pagar database demo + satu pintu masuk untuk seluruh penyemaian."""
    _inherit = "hms.demo.builder"

    @api.model
    def _database_name(self):
        """Dipisah supaya pagarnya bisa diuji tanpa database kedua."""
        return self.env.cr.dbname

    @api.model
    def _assert_demo_database(self):
        """Tolak keras di luar database ``*_demo``.

        Sama kerasnya dengan ``post_init_hook``, dan memang harus: jalur
        seeding baru yang lebih longgar daripada jalur lama hanya memindahkan
        kecelakaannya, tidak mencegahnya.
        """
        dbname = self._database_name()
        if not dbname.endswith("_demo"):
            raise UserError(
                _("Data demo SIMRS hanya boleh disemai di database demo. Database "
                  "'%s' tidak berakhiran '_demo', sehingga penyemaian dibatalkan.")
                % dbname
            )
        return dbname

    @api.model
    def seed_all(self):
        """Pintu masuk penyemaian — dipanggil berkas data dan post_init_hook.

        Dipanggil dari ``data/hms_demo_seed.xml`` supaya ``-u
        custom_hms_demo`` menyemai database yang SUDAH ada, bukan hanya
        instalasi bersih. Seluruhnya idempoten, jadi memanggilnya dua kali
        tidak menambah apa pun.
        """
        self._assert_demo_database()
        self.build_all()
        self.env["hms.demo.content"].build_content()
        return True


class HmsDemoContent(models.AbstractModel):
    _name = "hms.demo.content"
    _description = "Isi Demo SIMRS"

    # ------------------------------------------------------------------
    # Jangkar idempotensi
    # ------------------------------------------------------------------
    def _anchor(self, key):
        data = self.env["ir.model.data"].sudo().search(
            [("module", "=", ANCHOR_MODULE), ("name", "=", key)], limit=1
        )
        if not data:
            return None
        record = self.env[data.model].browse(data.res_id)
        if not record.exists():
            # Jangkar yatim (record dihapus manual): buang, jangan diam-diam
            # mengembalikan recordset kosong yang lolos sebagai "sudah ada".
            data.unlink()
            return None
        return record

    def _keep(self, key, record):
        self.env["ir.model.data"].sudo().create({
            "module": ANCHOR_MODULE,
            "name": key,
            "model": record._name,
            "res_id": record.id,
            "noupdate": True,
        })
        return record

    def _get_or_create(self, model, domain, vals):
        record = self.env[model].search(domain, limit=1)
        if record:
            return record
        return self.env[model].create(vals)

    # ------------------------------------------------------------------
    # Pintasan pencarian
    # ------------------------------------------------------------------
    def _unit(self, code):
        return self.env["hms.unit"].search([("code", "=", code)], limit=1)

    def _tariff(self, code):
        return self.env["hms.tariff"].search([("code", "=", code)], limit=1)

    def _icd10(self, code):
        return self.env["hms.icd10"].search([("code", "=", code)], limit=1)

    def _icd9(self, code):
        return self.env["hms.icd9"].search([("code", "=", code)], limit=1)

    def _payer(self, code):
        return self.env["hms.payer"].search([("code", "=", code)], limit=1)

    def _doctor(self, specialty_code):
        return self.env["hms.practitioner"].search([
            ("type", "in", ("doctor", "dentist")),
            ("specialty_id.code", "=", specialty_code),
        ], limit=1)

    def _nurse(self, index=0):
        nurses = self.env["hms.practitioner"].search(
            [("type", "=", "nurse")], order="id"
        )
        return nurses[index % len(nurses)] if nurses else self.env["hms.practitioner"]

    def _user(self, slug):
        return self.env["hms.demo.builder"].demo_user(slug)

    def _as(self, record, slug):
        """Jalankan sebuah aksi sebagai peran yang memang berwenang.

        Bukan ``sudo()``: gerbang yang diperiksa model (grup pengesah, praktisi
        yang terhubung ke akun) memang harus dipenuhi orang yang benar, dan
        seeding yang melewatinya dengan elevasi hak hanya menghasilkan demo
        yang membuktikan sebaliknya dari yang ingin diperagakan.
        """
        user = self._user(slug)
        return record.with_user(user) if user else record

    def _ack_actor(self, record, encounter):
        """Yang mengakui nilai kritis adalah DPJP-nya, bukan siapa pun.

        ``hms.lab.result`` dan ``hms.rad.report`` hanya boleh ditulis klinisi
        yang merawat pasiennya. Memakai satu akun dokter untuk semua episode
        akan ditolak record rule — dan seharusnya memang ditolak.
        """
        user = encounter.practitioner_id.user_id
        if user:
            return record.with_user(user)
        return self._as(record, "dokter")

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    @api.model
    def build_content(self):
        self.env["hms.demo.builder"]._assert_demo_database()
        self._masters()
        self._episodes()
        self._realign_klpcm()
        self._batches()
        self._medrec()
        self._safety()
        self._followups()
        self._quiesce_bridging_jobs()
        _logger.info("SIMRS: isi demo (skenario) selesai disemai")
        return True

    def _quiesce_bridging_jobs(self):
        """Batalkan antrian bridging yang lahir dari data demo.

        Setiap kunjungan yang dibuat di sini mengantrikan pembuatan SEP dan
        dorongan SATUSEHAT, persis seperti kunjungan sungguhan. Di lingkungan
        ini tidak ada VClaim dan tidak ada SATUSEHAT — hanya mock — sehingga
        job-job itu tidak akan pernah menghasilkan apa pun selain:

        * layar antrian job yang isinya puluhan baris menunggu selamanya,
          yang justru memperagakan sistem yang macet;
        * pekerja job yang mengunyahnya terus-menerus di latar belakang,
          termasuk mengambil dan menyimpan token mock ke ir.config_parameter.

        Nomor SEP kunjungan demo sudah diisi langsung saat kunjungan dibuat,
        jadi tidak ada pekerjaan yang benar-benar hilang. Hanya berjalan di
        database demo, karena seluruh penyemaian ini berjalan di balik
        ``_assert_demo_database()``.
        """
        stale = self.env["hms.job"].sudo().search([
            ("state", "in", ("pending", "failed")),
            "|", ("name", "=like", "bpjs.%"), ("name", "=like", "satusehat.%"),
        ])
        if not stale:
            return 0
        stale.write({
            "last_error": "Dibatalkan penyemaian data demo: bridging BPJS/SATUSEHAT "
                          "belum tersambung di lingkungan ini.",
        })
        stale.action_cancel()
        _logger.info("SIMRS demo: %s job bridging dibatalkan", len(stale))
        return len(stale)

    def _realign_klpcm(self):
        """Kembalikan tenggat KLPCM ke jam kunjungan demo ditutup.

        ``hms.encounter.action_close()`` memanggil analisis KLPCM, dan
        ``due_at`` dibekukan di sana dari ``closed_at`` — yang pada detik itu
        masih bernilai "sekarang". Kunjungan demo baru dimundurkan tanggalnya
        SETELAH ditutup, sehingga tenggatnya tertinggal di masa depan dan
        tidak satu pun temuan tampak lewat tenggat.

        Yang dilakukan di sini bukan melonggarkan aturan pembekuan, melainkan
        menghitung ulang nilai yang SAMA dengan yang akan dihasilkan model
        bila jamnya benar sejak awal: ``closed_at + due_hours_applied``.
        Hanya menyentuh kunjungan berjangkar demo.
        """
        Klpcm = self.env["hms.klpcm"].sudo()
        anchors = self.env["ir.model.data"].sudo().search([
            ("module", "=", ANCHOR_MODULE), ("model", "=", "hms.encounter"),
        ])
        encounters = self.env["hms.encounter"].browse(anchors.mapped("res_id")).exists()
        for encounter in encounters.filtered("closed_at"):
            for row in Klpcm.search([("encounter_id", "=", encounter.id)]):
                hours = row.due_hours_applied or 48
                due = encounter.closed_at + timedelta(hours=hours)
                if row.due_at != due:
                    row.write({"due_at": due, "analyzed_at": encounter.closed_at})
        return True

    # ------------------------------------------------------------------
    # A. Katalog master
    # ------------------------------------------------------------------
    def _masters(self):
        self._reference_codes()
        self._consent_templates()
        self._extra_tariffs()
        self._extra_lab_parameters()
        self._lab_tests()
        self._rad_exams()
        self._diet_types()

    def _reference_codes(self):
        for code, name_id, name_en in ICD10:
            self._get_or_create("hms.icd10", [("code", "=", code)], {
                "code": code, "name_id": name_id, "name_en": name_en,
                "is_icd10_im": True,
            })
        for code, name, surgical, special in ICD9:
            self._get_or_create("hms.icd9", [("code", "=", code)], {
                "code": code, "name": name,
                "is_surgical": surgical, "is_special_cmg": special,
            })

    def _consent_templates(self):
        for code, name, kind, body in CONSENT_TEMPLATES:
            self._get_or_create("hms.consent.template", [("code", "=", code)], {
                "code": code, "name": name, "type": kind, "body": body,
            })

    def _extra_tariffs(self):
        categories = {
            "lab": "custom_hms_base.tariff_cat_lab",
            "rad": "custom_hms_base.tariff_cat_rad",
            "procedure": "custom_hms_base.tariff_cat_procedure",
        }
        for code, name, category, unit_code, price, minutes, consent in EXTRA_TARIFFS:
            tariff = self._get_or_create("hms.tariff", [("code", "=", code)], {
                "code": code, "name": name,
                "category_id": self.env.ref(categories[category]).id,
                "unit_id": self._unit(unit_code).id,
                "duration_minutes": minutes,
                "requires_consent": consent,
            })
            if not tariff.price_ids:
                # Harga tanpa kelas: penunjang dan tindakan bedah di RS ini
                # satu harga untuk semua kelas, dan tarif tanpa harga akan
                # menahan tagihan di hms.bill.action_open().
                self.env["hms.tariff.price"].create({
                    "tariff_id": tariff.id,
                    "price_total": price,
                    "amount_facility": round(price * 0.6),
                    "amount_medical": round(price * 0.35),
                    "amount_consumable": price - round(price * 0.6) - round(price * 0.35),
                })

    def _extra_lab_parameters(self):
        for code, name, uom, specimen, ranges in EXTRA_LAB_PARAMETERS:
            parameter = self._get_or_create("hms.lab.parameter", [("code", "=", code)], {
                "code": code, "name": name, "uom_name": uom,
                "value_type": "numeric", "specimen_type": specimen, "tat_minutes": 120,
            })
            if not parameter.range_ids:
                for gender, age_from, age_to, low, high, crit_low, crit_high in ranges:
                    self.env["hms.lab.reference.range"].create({
                        "parameter_id": parameter.id, "gender": gender,
                        "age_from": age_from, "age_to": age_to,
                        "ref_low": low, "ref_high": high,
                        "critical_low": crit_low, "critical_high": crit_high,
                    })

    def _lab_tests(self):
        Parameter = self.env["hms.lab.parameter"]
        for code, name, tariff_code, params, panel, specimen, container, tat, note \
                in LAB_TESTS:
            tariff = self._tariff(tariff_code)
            if not tariff:
                continue
            parameters = Parameter.search([("code", "in", params)])
            if len(parameters) != len(params):
                # Katalog setengah jadi lebih berbahaya daripada tidak ada
                # katalog sama sekali: ia MENANG atas jalur lama dan akan
                # memangkas daftar parameter tanpa memberi tahu siapa pun.
                _logger.warning(
                    "SIMRS demo: katalog lab %s dilewati, parameter belum lengkap", code
                )
                continue
            self._get_or_create("hms.lab.test", [("code", "=", code)], {
                "code": code, "name": name, "tariff_id": tariff.id,
                "parameter_ids": [(6, 0, parameters.ids)],
                "is_panel": panel, "specimen_type": specimen,
                "container": container, "tat_minutes": tat, "note": note or False,
            })

    def _rad_exams(self):
        for code, name, tariff_code, modality, body_part, contrast, minutes, dose, prep \
                in RAD_EXAMS:
            tariff = self._tariff(tariff_code)
            if not tariff:
                continue
            self._get_or_create("hms.rad.exam", [("code", "=", code)], {
                "code": code, "name": name, "tariff_id": tariff.id,
                "modality": modality, "body_part": body_part,
                "requires_contrast": contrast, "estimated_minutes": minutes,
                "dose_reference": dose or False, "preparation_note": prep,
            })

    def _diet_types(self):
        for code, name, category, texture, kcal, protein, therapeutic, restrictions \
                in DIET_TYPES:
            self._get_or_create("hms.diet.type", [("code", "=", code)], {
                "code": code, "name": name, "category": category, "texture": texture,
                "energy_kcal": kcal, "protein_g": protein,
                "is_therapeutic": therapeutic, "restrictions": restrictions or False,
            })

    # ------------------------------------------------------------------
    # B. Mesin episode
    # ------------------------------------------------------------------
    def _patient_pools(self):
        """Dua daftar pasien dengan urutan stabil, supaya demo tidak berubah."""
        Patient = self.env["hms.patient"]
        bpjs = Patient.search(
            [("bpjs_no", "!=", False), ("state", "=", "active")], order="id"
        )
        umum = Patient.search(
            [("bpjs_no", "=", False), ("state", "=", "active")], order="id"
        )
        return bpjs, umum

    def _plan_for(self, payer, patient):
        if payer.code != "BPJS":
            return payer.plan_ids[:1]
        by_class = {"1": "NONPBI-1", "2": "NONPBI-2", "3": "PBI"}
        wanted = by_class.get(patient.bpjs_class or "3", "PBI")
        return (payer.plan_ids.filtered(lambda p: p.code == wanted)[:1]
                or payer.plan_ids[:1])

    def _open_encounter(self, patient, unit, doctor, payer, arrival, enc_type,
                        complaint, triage=None, arrival_mode="walk_in"):
        plan = self._plan_for(payer, patient)
        vals = {
            "patient_id": patient.id,
            "unit_id": unit.id,
            "practitioner_id": doctor.id,
            "payer_id": payer.id,
            "payer_plan_id": plan.id,
            "class_id": plan.class_id.id if plan.class_id else False,
            "type": enc_type,
            "arrival_at": arrival,
            "arrival_mode": arrival_mode,
            "chief_complaint": complaint,
        }
        if enc_type == "emergency":
            vals.update({"triage_level": triage or "yellow", "triage_at": arrival,
                         "triage_by_id": self._nurse(5).id})
        encounter = self.env["hms.encounter"].create(vals)
        if payer.requires_sep and patient.bpjs_no:
            # SEP demo: bridging VClaim belum tersambung, tetapi tanpa nomor SEP
            # hms.bill.line._resolve_coverage() menetapkan tanggungan 0% dan
            # seluruh tagihan BPJS tampak dibayar pasien — angka yang salah di
            # layar kasir dan di klaim.
            encounter.write({
                "sep_no": "0001R001%s%04d" % (arrival.strftime("%m%y"), encounter.id % 10000),
                "sep_state": "issued",
            })
        encounter.action_start_service()
        return encounter

    def _observation(self, encounter, at, **vitals):
        base = {
            "encounter_id": encounter.id, "context": "initial",
            "systolic": 124, "diastolic": 78, "pulse": 88, "respiratory_rate": 20,
            "temperature": 37.2, "spo2": 98, "pain_score": 2,
            "taken_at": at,
        }
        base.update(vitals)
        return self.env["hms.observation"].create(base)

    def _note(self, encounter, doctor, at, note_type, s, o, a, p, instruction=None):
        note = self.env["hms.clinical.note"].create({
            "encounter_id": encounter.id, "author_id": doctor.id,
            "author_role": "doctor", "note_type": note_type, "noted_at": at,
            "subjective": s, "objective": o, "assessment": a, "plan": p,
            "instruction": instruction or False,
        })
        note.action_sign()
        return note

    def _diagnoses(self, encounter, doctor, at, entries):
        """entries: [(icd10 code, rank, stage)] — diagnosis dokter, bukan koder."""
        created = self.env["hms.diagnosis"]
        for code, rank, stage in entries:
            icd = self._icd10(code)
            if not icd:
                continue
            created |= self.env["hms.diagnosis"].create({
                "encounter_id": encounter.id, "icd10_id": icd.id,
                "rank": rank, "stage": stage, "practitioner_id": doctor.id,
                "diagnosed_at": at,
            })
        return created

    def _consent(self, encounter, doctor, template_code, signer_relation="Pasien sendiri"):
        template = self.env["hms.consent.template"].search(
            [("code", "=", template_code)], limit=1
        )
        if not template:
            return self.env["hms.consent"]
        consent = self.env["hms.consent"].create({
            "encounter_id": encounter.id,
            "patient_id": encounter.patient_id.id,
            "template_id": template.id,
            "explained_by_id": doctor.id,
            "signer_type": "patient",
            "signer_name": encounter.patient_id.name,
            "signer_relation": signer_relation,
            "witness_name": self._nurse(1).name,
        })
        consent.action_sign()
        return consent

    def _nursing_assessment(self, encounter, at, fall=25, braden=18, pain=3):
        assessment = self.env["hms.nursing.assessment"].create({
            "encounter_id": encounter.id, "type": "initial",
            "nurse_id": self._nurse(0).id, "assessed_at": at,
            "fall_risk_score": fall, "braden_score": braden, "pain_score": pain,
            "nutrition_screen": "mild", "functional_status": "partial",
            "psychosocial": "Pasien kooperatif, didampingi keluarga inti.",
            "education_need": "Edukasi tanda bahaya dan jadwal obat.",
            "evaluation": "Masalah keperawatan teratasi sebagian, intervensi dilanjutkan.",
        })
        assessment.action_sign()
        return assessment

    # --- penunjang --------------------------------------------------------
    LAB_DEFAULTS = {
        "HB": 13.4, "WBC": 8.2, "PLT": 254.0, "HCT": 41.0, "GDS": 112.0,
        "GDP": 96.0, "CHOL": 186.0, "TG": 132.0, "UA": 5.2,
        "UREUM": 28.0, "KREAT": 0.9, "SGOT": 26.0, "SGPT": 31.0,
        "BILT": 0.8, "ALB": 4.1, "NA": 139.0, "K": 4.1, "CL": 102.0,
        "UR-PROT": 5.0, "UR-GLU": 2.0, "UR-LEU": 2.0, "UR-ERI": 1.0,
    }

    def _lab(self, encounter, doctor, tariff_code, ordered_at, values=None,
             clinical_note=None, ack=None, verified_at=None, acknowledged_at=None):
        """Order lab yang benar-benar dikerjakan sampai terverifikasi.

        ``ack`` menentukan nasib nilai kritis: ``"acknowledged"`` menutup
        lingkaran TBaK, ``None`` membiarkannya menunggu. Yang TIDAK dilakukan
        adalah menulis ``ack_state`` langsung — status itu turunan dari
        ``acknowledged_at`` dan ambang ``critical_result_ack_minutes``, dan
        menulisnya sendiri hanya menghasilkan layar yang berbohong.
        """
        tariff = self._tariff(tariff_code)
        if not tariff:
            return self.env["hms.lab.result"]
        order = self.env["hms.order"].create({
            "encounter_id": encounter.id, "order_type": "lab",
            "practitioner_id": doctor.id, "ordered_at": ordered_at,
            "target_unit_id": self._unit("LAB").id,
            "clinical_note": clinical_note or encounter.chief_complaint,
            "line_ids": [(0, 0, {"tariff_id": tariff.id})],
        })
        order.action_submit()
        line = order.line_ids
        line.action_start()
        analyst = self._user("analis")
        values = values or {}
        for result in line.lab_result_ids:
            code = result.parameter_id.code
            result.write({
                "value_numeric": values.get(code, self.LAB_DEFAULTS.get(code, 1.0)),
            })
            actor = result.with_user(analyst) if analyst else result
            actor.action_enter()
            actor.action_validate()
            actor.action_verify()
        results = line.lab_result_ids
        critical = results.filtered("is_critical")
        if critical:
            actor = critical.with_user(analyst) if analyst else critical
            actor.action_notify(
                practitioner_id=encounter.practitioner_id.id, channel="phone"
            )
            if ack == "acknowledged":
                self._ack_actor(critical, encounter).action_acknowledge(
                    readback="Dibacakan ulang oleh DPJP: nilai kritis diterima, "
                             "terapi disesuaikan."
                )
        if verified_at:
            # Jam TBaK berjalan dari verifikasi. Hasil yang diverifikasi
            # "sekarang" untuk kunjungan bulan lalu membuat setiap nilai
            # kritis tampak baru saja keluar.
            results.write({"verified_at": verified_at})
            if critical:
                critical.write({"notified_at": verified_at + timedelta(minutes=6)})
        if acknowledged_at and critical:
            critical.filtered("acknowledged_at").write(
                {"acknowledged_at": acknowledged_at}
            )
        return results

    def _rad(self, encounter, doctor, tariff_code, ordered_at, findings, impression,
             is_critical=False, ack=None, suggestion=None,
             verified_at=None, acknowledged_at=None):
        tariff = self._tariff(tariff_code)
        if not tariff:
            return self.env["hms.rad.report"]
        order = self.env["hms.order"].create({
            "encounter_id": encounter.id, "order_type": "radiology",
            "practitioner_id": doctor.id, "ordered_at": ordered_at,
            "target_unit_id": self._unit("RAD").id,
            "clinical_note": encounter.chief_complaint,
            "line_ids": [(0, 0, {"tariff_id": tariff.id})],
        })
        order.action_submit()
        report = order.line_ids.rad_report_ids
        if not report:
            return report
        actor = self._as(report, "radiolog")
        actor.write({
            "technique": "Proyeksi standar, kondisi cukup.",
            "findings": findings,
            "impression": impression,
            "suggestion": suggestion or False,
            "is_critical": is_critical,
        })
        actor.action_perform()
        actor.action_report()
        actor.action_verify()
        if is_critical:
            actor.action_notify(
                practitioner_id=encounter.practitioner_id.id, channel="phone"
            )
            if ack == "acknowledged":
                self._ack_actor(report, encounter).action_acknowledge(
                    readback="Dibacakan ulang oleh DPJP: temuan kritis diterima."
                )
        if verified_at:
            report.write({"verified_at": verified_at})
            if is_critical:
                report.write({"notified_at": verified_at + timedelta(minutes=5)})
        if acknowledged_at and report.acknowledged_at:
            report.write({"acknowledged_at": acknowledged_at})
        return report

    def _procedure_order(self, encounter, doctor, tariff_code, scheduled_at,
                         room=None, ordered_at=None):
        """Order tindakan terjadwal — inilah yang melahirkan papan operasi."""
        tariff = self._tariff(tariff_code)
        if not tariff:
            return self.env["hms.order.line"]
        order = self.env["hms.order"].create({
            "encounter_id": encounter.id, "order_type": "procedure",
            "practitioner_id": doctor.id,
            "ordered_at": ordered_at or (scheduled_at - timedelta(days=1)),
            "target_unit_id": tariff.unit_id.id or encounter.unit_id.id,
            "clinical_note": encounter.chief_complaint,
            "line_ids": [(0, 0, {"tariff_id": tariff.id,
                                 "scheduled_at": scheduled_at})],
        })
        order.action_submit()
        schedule = order.line_ids.procedure_schedule_ids
        if schedule and room:
            schedule.write({"room_id": room.id})
        return order.line_ids

    def _summary_for(self, encounter, condition="improved", disposition="home",
                     followup_days=None, followup_unit=None, instruction=None,
                     lab_summary=None):
        summary_type = "discharge" if encounter.type == "inpatient" else "outpatient"
        summary = self.env["hms.summary"].generate_for(encounter, summary_type)
        if summary.state == "final":
            return summary
        vals = {"condition_at_discharge": condition, "disposition": disposition}
        if lab_summary:
            vals["lab_summary"] = lab_summary
        if followup_days:
            vals.update({
                "followup_date": fields.Date.add(
                    fields.Date.context_today(self), days=followup_days
                ),
                "followup_unit_id": (followup_unit or encounter.unit_id).id,
                "followup_instruction": instruction or
                    "Kontrol ke poli membawa hasil pemeriksaan dan sisa obat.",
            })
        summary.write(vals)
        summary.action_finalize()
        return summary

    def _close_and_bill(self, encounter, closed_at, extra_tariffs=(),
                        disposition="home", open_bill=True):
        encounter.action_close()
        vals = {"closed_at": closed_at}
        if disposition:
            vals["discharge_disposition"] = disposition
        encounter.write(vals)
        bill = self.env["hms.bill"].get_or_create_for(encounter)
        BillLine = self.env["hms.bill.line"]
        for code in extra_tariffs:
            tariff = self._tariff(code)
            if not tariff or bill.line_ids.filtered(lambda l, t=tariff: l.tariff_id == t):
                continue
            BillLine.charge(
                bill, tariff, practitioner=encounter.practitioner_id,
                service_date=closed_at.date(),
            )
        if (open_bill and bill.state == "draft" and bill.line_ids
                and not bill.unpriced_line_count):
            bill.action_open()
        return bill

    def _build_episode(self, patient, unit_code, specialty, payer_code, enc_type,
                       days_ago, complaint, notes, diagnoses, hours=5,
                       labs=(), rads=(), procedures=(), consent_code=None,
                       nursing=False, want_summary=True, followup_days=None,
                       disposition="home", triage=None, arrival_mode="walk_in",
                       bill_tariffs=("ADM-RJ", "KONS-SP"), vitals=None,
                       done_procedure=None):
        """Satu episode pelayanan lengkap, dari pendaftaran sampai tagihan.

        Urutannya bukan selera: dokumen klinis dibuat SEBELUM klaim
        difinalisasi, karena finalisasi mengunci kunjungan dan sejak itu
        catatan, diagnosis, tindakan dan resume tidak bisa ditambah lagi
        kecuali lewat permintaan koreksi yang disetujui.
        """
        now = fields.Datetime.now()
        arrival = now - timedelta(days=days_ago)
        closed = arrival + timedelta(hours=hours)
        unit = self._unit(unit_code)
        # ``specialty`` boleh berupa kode spesialisasi atau langsung record
        # praktisi: beberapa episode HARUS dipegang DPJP yang punya akun,
        # karena pengakuan nilai kritis dicatat atas nama pengguna yang login.
        doctor = (specialty if getattr(specialty, "_name", None) == "hms.practitioner"
                  else self._doctor(specialty))
        payer = self._payer(payer_code)
        encounter = self._open_encounter(
            patient, unit, doctor, payer, arrival, enc_type, complaint,
            triage=triage, arrival_mode=arrival_mode,
        )
        self._observation(encounter, arrival + timedelta(minutes=10), **(vitals or {}))
        for note_type, subjective, objective, assessment, plan in notes:
            self._note(encounter, doctor, arrival + timedelta(minutes=30),
                       note_type, subjective, objective, assessment, plan)
        self._diagnoses(encounter, doctor, arrival + timedelta(minutes=40), diagnoses)
        consent = self.env["hms.consent"]
        if consent_code:
            consent = self._consent(encounter, doctor, consent_code)
        if nursing:
            self._nursing_assessment(encounter, arrival + timedelta(minutes=20))
        for lab in labs:
            self._lab(encounter, doctor, ordered_at=arrival + timedelta(hours=1), **lab)
        for rad in rads:
            self._rad(encounter, doctor, ordered_at=arrival + timedelta(hours=1), **rad)
        for icd9_code, name, tariff_code in procedures:
            self.env["hms.procedure"].create({
                "encounter_id": encounter.id,
                "icd9_id": self._icd9(icd9_code).id,
                "tariff_id": self._tariff(tariff_code).id,
                "name": name,
                "performed_at": arrival + timedelta(hours=2),
                "practitioner_id": doctor.id,
                "consent_id": consent.id if consent else False,
                "outcome": "success",
                "note": "Tindakan berjalan lancar, tidak ada penyulit intraoperatif.",
            })
        if done_procedure:
            line = self._procedure_order(
                encounter, doctor, done_procedure,
                scheduled_at=arrival + timedelta(hours=2),
            )
            schedule = line.procedure_schedule_ids
            if schedule:
                schedule.action_confirm()
                schedule.action_start()
                schedule.action_done()
        bill = self._close_and_bill(
            encounter, closed, extra_tariffs=bill_tariffs, disposition=disposition,
        )
        # Analisis pertama dijalankan SEBELUM resume difinalkan: itulah yang
        # membuat baris KLPCM benar-benar pernah terbuka lalu tertutup, bukan
        # tidak pernah ada.
        self.env["hms.klpcm"].analyze_encounter(encounter)
        if want_summary:
            self._summary_for(
                encounter, followup_days=followup_days,
                disposition="deceased" if disposition == "deceased" else "home",
                condition="deceased" if disposition == "deceased" else "improved",
                lab_summary="Hasil penunjang terlampir pada berkas kunjungan.",
            )
            self.env["hms.klpcm"].analyze_encounter(encounter)
        _logger.info("SIMRS demo: episode %s (%s) selesai, tagihan %s",
                     encounter.name, patient.name, bill.name)
        return encounter

    def _episode(self, key, **spec):
        encounter = self._anchor(key)
        if encounter:
            return encounter
        return self._keep(key, self._build_episode(**spec))

    # ------------------------------------------------------------------
    # C. Klaim casemix
    # ------------------------------------------------------------------
    def _claim_for(self, encounter, grouped_ratio=1.0, topup=0.0):
        """Buka klaim untuk satu episode dan isi tarif grouper-nya.

        Tarif grouper DIISI MANUSIA dari aplikasi E-Klaim; di demo ini ia
        diturunkan dari tarif rumah sakit dengan selisih yang masuk akal dan
        tetap di bawah ambang review empat mata, supaya klaim demo tidak
        semuanya tertahan di meja verifikator.
        """
        claim = self.env["hms.claim"].create_for_encounter(encounter)
        if not claim.grouped_tariff:
            grouped = round((claim.hospital_bill_amount or 0.0) * grouped_ratio, -3)
            claim.write({"grouped_tariff": grouped, "topup_amount": topup})
        return claim

    def _code_claim(self, claim, principal, comorbidities=(), procedures=(),
                    added_by_coder=None):
        """Koding: kode klaim yang benar-benar menunjuk catatan dokternya."""
        koder = self._as(claim, "koder")
        if claim.state == "to_code":
            koder.action_start_coding()
        if claim.is_readmission and not claim.readmission_reason:
            claim.write({
                "readmission_reason": "Perburukan kondisi yang sama dalam masa "
                                      "pemulihan; bukan pemulangan dini.",
            })
        Code = self.env["hms.claim.code"].with_user(koder.env.user)
        dxs = self.env["hms.diagnosis"].search(
            [("encounter_id", "=", claim.encounter_id.id)]
        )
        by_icd10 = {d.icd10_id.code: d for d in dxs}
        procs = self.env["hms.procedure"].search(
            [("encounter_id", "=", claim.encounter_id.id)]
        )
        by_icd9 = {p.icd9_id.code: p for p in procs if p.icd9_id}
        if not claim.code_ids.filtered(lambda c: c.kind == "icd10" and c.role == "principal"):
            Code.create({
                "claim_id": claim.id, "kind": "icd10", "role": "principal", "seq": 10,
                "icd10_id": self._icd10(principal).id,
                "source_diagnosis_id": by_icd10.get(principal).id
                if by_icd10.get(principal) else False,
                "change_reason": False if by_icd10.get(principal) else
                    "Kode ditegakkan koder dari resume; diagnosis dokter belum "
                    "mencantumkan kode ini.",
            })
        seq = 20
        for code, role in comorbidities:
            if claim.code_ids.filtered(lambda c, x=code: c.code_display == x):
                continue
            source = by_icd10.get(code)
            Code.create({
                "claim_id": claim.id, "kind": "icd10", "role": role, "seq": seq,
                "icd10_id": self._icd10(code).id,
                "source_diagnosis_id": source.id if source else False,
                "change_reason": False if source else
                    "Ditambahkan koder dari hasil penunjang pada berkas; belum "
                    "tertulis sebagai diagnosis pada CPPT.",
            })
            seq += 10
        for index, (code, role) in enumerate(procedures):
            if claim.code_ids.filtered(lambda c, x=code: c.code_display == x):
                continue
            source = by_icd9.get(code)
            Code.create({
                "claim_id": claim.id, "kind": "icd9", "role": role, "seq": 10 + index * 10,
                "icd9_id": self._icd9(code).id,
                "source_procedure_id": source.id if source else False,
                "change_reason": False if source else
                    "Tindakan terbaca pada laporan operasi tetapi belum "
                    "tercatat sebagai prosedur terstruktur.",
            })
        return claim

    def _coding_query(self, claim, topic, question, answer=None, outcome=None):
        existing = self.env["hms.coding.query"].search(
            [("claim_id", "=", claim.id), ("question", "=", question)], limit=1
        )
        if existing:
            return existing
        query = self.env["hms.coding.query"].with_user(
            self._as(claim, "koder").env.user
        ).create({
            "claim_id": claim.id, "topic": topic, "question": question,
            "addressed_to_id": claim.encounter_id.practitioner_id.id,
        })
        if answer:
            query.write({"answer": answer})
            query.action_answer()
            if outcome:
                query.write({"outcome": outcome})
                query.action_close()
        return query

    def _advance_to_finalized(self, claim, review_note=None):
        koder = self._as(claim, "koder")
        if claim.state == "coding":
            koder.action_code_done()
        verifier = self._as(claim, "verifikator")
        if claim.state == "internal_review":
            if review_note:
                claim.write({"review_note": review_note})
            verifier.action_verify_internal()
        if claim.state == "internal_verified":
            verifier.action_finalize()
        return claim

    def _days_ago(self, target):
        return max((fields.Date.context_today(self) - target).days, 1)

    def _dpjp_with_account(self):
        """DPJP yang punya akun login — dipakai episode nilai kritis.

        Pengakuan nilai kritis dicatat atas nama pengguna yang menekan
        tombolnya, dan record rule hanya mengizinkan klinisi menulis pada
        pasien yang memang dirawatnya. Tanpa DPJP yang punya akun, lingkaran
        TBaK tidak bisa ditutup oleh siapa pun yang pantas menutupnya.
        """
        user = self._user("dokter")
        if not user:
            return self._doctor("SPU")
        return (self.env["hms.practitioner"].search(
            [("user_id", "=", user.id)], limit=1) or self._doctor("SPU"))

    # ------------------------------------------------------------------
    # Roster episode + klaim
    # ------------------------------------------------------------------
    def _episodes(self):
        bpjs, umum = self._patient_pools()
        if len(bpjs) < 14 or len(umum) < 5:
            _logger.warning(
                "SIMRS demo: pasien belum cukup (%s BPJS, %s umum) — "
                "skenario berisi dilewati", len(bpjs), len(umum)
            )
            return
        today = fields.Date.context_today(self)
        p1 = (today - relativedelta(days=45)).replace(day=1)
        p2 = (today - relativedelta(days=75)).replace(day=1)
        dpjp = self._dpjp_with_account()

        # --- 1. Berkas belum lengkap: klaim berhenti di gerbang KLPCM -----
        enc = self._episode(
            "ep_klpcm_open",
            patient=bpjs[0], unit_code="POLI-PD", specialty="INT", payer_code="BPJS",
            enc_type="outpatient", days_ago=11, hours=4,
            complaint="Batuk berdahak dan sesak sejak 5 hari",
            notes=[("soap",
                    "Batuk berdahak kehijauan 5 hari, demam naik turun, sesak saat aktivitas.",
                    "TD 128/80, nadi 96, suhu 38,1 °C, ronki basah kasar paru kanan bawah.",
                    "Pneumonia komunitas pada hipertensi terkontrol.",
                    "Antibiotik empiris, mukolitik, foto toraks ulang 5 hari.")],
            diagnoses=[("J18.9", "primary", "final"), ("I10", "comorbidity", "final")],
            labs=[{"tariff_code": "LAB-DL", "values": {"WBC": 15.6, "HB": 12.8}}],
            rads=[{"tariff_code": "RAD-THX",
                   "findings": "Perselubungan inhomogen lapangan paru kanan bawah, "
                               "sinus dan diafragma baik.",
                   "impression": "Pneumonia lobaris kanan bawah."}],
            want_summary=False,
            vitals={"temperature": 38.1, "pulse": 96, "respiratory_rate": 24, "spo2": 96},
        )
        self._claim_for(enc, 0.95)

        # --- 2. Sedang dikoding, menunggu jawaban DPJP --------------------
        enc = self._episode(
            "ep_coding",
            patient=bpjs[1], unit_code="POLI-UMUM", specialty=dpjp, payer_code="BPJS",
            enc_type="outpatient", days_ago=23, hours=5,
            complaint="Lemas, pucat, dan mudah lelah sejak 2 minggu",
            notes=[("soap",
                    "Lemas dan pucat 2 minggu, riwayat menstruasi banyak.",
                    "Konjungtiva anemis, TD 106/68, nadi 98, tidak ada perdarahan aktif.",
                    "Anemia berat, curiga defisiensi besi.",
                    "Cek darah lengkap, suplementasi besi, evaluasi 2 minggu.")],
            diagnoses=[("D64.9", "primary", "final")],
            labs=[{"tariff_code": "LAB-DL",
                   "values": {"HB": 6.2, "HCT": 21.0, "WBC": 7.4, "PLT": 320.0},
                   "ack": "acknowledged",
                   "verified_at": fields.Datetime.now() - timedelta(days=23, hours=-6),
                   "acknowledged_at": fields.Datetime.now()
                   - timedelta(days=23, hours=-6) + timedelta(minutes=18)}],
            want_summary=True, followup_days=12,
            vitals={"systolic": 106, "diastolic": 68, "pulse": 98},
        )
        claim = self._claim_for(enc, 0.92)
        self._code_claim(claim, "D64.9")
        self._coding_query(
            claim, "specificity",
            "Anemia pada resume belum menyebut jenisnya. Apakah dapat "
            "ditegakkan anemia defisiensi besi (D50.9) berdasarkan hasil "
            "Hb 6,2 g/dL dan gambaran klinis?",
        )

        # --- 3. Final, menunggu berkas susulan ----------------------------
        enc = self._episode(
            "ep_final",
            patient=bpjs[2], unit_code="POLI-BEDAH", specialty="BED", payer_code="BPJS",
            enc_type="outpatient", days_ago=self._days_ago(p1 + timedelta(days=13)),
            hours=3, complaint="Luka robek tungkai kanan akibat terjatuh",
            notes=[("soap",
                    "Terjatuh dari sepeda motor, luka robek tungkai kanan bawah.",
                    "Vulnus laceratum 6 cm regio cruris dextra, perdarahan terkontrol.",
                    "Vulnus laceratum cruris dextra.",
                    "Debridemen dan hecting, profilaksis tetanus, ganti balut 3 hari.")],
            diagnoses=[("S06.0", "secondary", "working"), ("W19", "primary", "final")],
            procedures=[("86.59", "Hecting luka tungkai kanan (8 jahitan)", "TND-HECT")],
            consent_code="CONS-TIND",
            want_summary=True, followup_days=9,
            bill_tariffs=("ADM-RJ", "KONS-SP", "TND-HECT"),
        )
        claim = self._claim_for(enc, 0.97)
        self._code_claim(claim, "W19", comorbidities=[("S06.0", "comorbidity")],
                         procedures=[("86.59", "principal")])
        self._coding_query(
            claim, "procedure",
            "Jumlah jahitan pada laporan tindakan tidak disebutkan. Berapa "
            "jahitan yang dikerjakan, untuk menentukan kelipatan tarif?",
            answer="Delapan jahitan, satu lapis, tanpa penyulit.",
            outcome="documentation_added",
        )
        self._advance_to_finalized(claim)

        # --- 4 & 5. Dua klaim rawat jalan yang sudah diajukan -------------
        enc = self._episode(
            "ep_sub_a",
            patient=bpjs[3], unit_code="POLI-PD", specialty="INT", payer_code="BPJS",
            enc_type="outpatient", days_ago=self._days_ago(p1 + timedelta(days=4)),
            hours=4, complaint="Kontrol diabetes melitus, gula darah tidak terkontrol",
            notes=[("soap",
                    "Kontrol rutin DM tipe 2, sering haus dan sering berkemih malam.",
                    "BB 78 kg, TD 138/86, tidak ada luka kaki, akral hangat.",
                    "DM tipe 2 tidak terkontrol dengan hipertensi.",
                    "Titrasi metformin, diet DM 1700 kkal, cek profil lipid.")],
            diagnoses=[("E11.9", "primary", "final"), ("I10", "comorbidity", "final")],
            labs=[{"tariff_code": "LAB-GDS", "values": {"GDS": 268.0}},
                  {"tariff_code": "LAB-KIMIA",
                   "values": {"GDP": 178.0, "CHOL": 244.0, "TG": 310.0, "UA": 7.8}}],
            want_summary=True, followup_days=21,
            vitals={"systolic": 138, "diastolic": 86, "weight_kg": 78, "height_cm": 165},
        )
        claim_a = self._claim_for(enc, 0.93)
        self._code_claim(claim_a, "E11.9", comorbidities=[("I10", "comorbidity")])
        self._advance_to_finalized(claim_a)

        enc = self._episode(
            "ep_sub_b",
            patient=bpjs[4], unit_code="POLI-ANAK", specialty="ANA", payer_code="BPJS",
            enc_type="outpatient", days_ago=self._days_ago(p1 + timedelta(days=9)),
            hours=3, complaint="Demam tinggi hari ke-4 pada anak",
            notes=[("soap",
                    "Demam tinggi 4 hari, nyeri perut, mimisan satu kali.",
                    "Suhu 38,9 °C, uji torniket positif, hepar tidak membesar.",
                    "Demam berdarah dengue derajat I.",
                    "Rawat jalan dengan pemantauan ketat, cek trombosit harian.")],
            diagnoses=[("A91", "primary", "final")],
            labs=[{"tariff_code": "LAB-DL",
                   "values": {"PLT": 96.0, "HCT": 45.0, "WBC": 3.2, "HB": 13.1}}],
            want_summary=True, followup_days=6,
            vitals={"temperature": 38.9, "pulse": 112, "pain_score": 4},
        )
        claim_b = self._claim_for(enc, 0.9)
        self._code_claim(claim_b, "A91")
        self._advance_to_finalized(claim_b)

        # --- 6..9. Empat episode rawat inap yang sudah diajukan -----------
        enc = self._episode(
            "ep_appr",
            patient=bpjs[5], unit_code="RANAP", specialty="BED", payer_code="BPJS",
            enc_type="inpatient", days_ago=self._days_ago(p2 + timedelta(days=5)),
            hours=72, complaint="Nyeri perut kanan bawah hebat sejak 12 jam",
            notes=[("medical_initial",
                    "Nyeri perut kanan bawah 12 jam, mual, muntah dua kali.",
                    "Nyeri tekan McBurney positif, rebound tenderness positif, suhu 38,2 °C.",
                    "Apendisitis akut.",
                    "Apendektomi cito, antibiotik profilaksis, puasa pra-operasi."),
                   ("soap",
                    "Hari ke-2 pasca operasi, nyeri luka berkurang, flatus sudah ada.",
                    "Luka operasi kering, tidak ada tanda infeksi, bising usus normal.",
                    "Pasca apendektomi hari ke-2, perbaikan.",
                    "Mobilisasi bertahap, diet lunak, rencana pulang besok.")],
            diagnoses=[("K35.80", "primary", "final")],
            procedures=[("47.09", "Apendektomi terbuka", "TND-APP")],
            consent_code="CONS-TIND", nursing=True,
            labs=[{"tariff_code": "LAB-DL", "values": {"WBC": 17.8, "HB": 13.6}}],
            want_summary=True, followup_days=8,
            bill_tariffs=("ADM-RI", "VISITE", "KAMAR", "ASKEP"),
            done_procedure="TND-APP",
            vitals={"temperature": 38.2, "pulse": 104, "pain_score": 8},
        )
        claim_appr = self._claim_for(enc, 1.03)
        self._code_claim(claim_appr, "K35.80", procedures=[("47.09", "principal")])
        self._advance_to_finalized(claim_appr)

        enc = self._episode(
            "ep_paid",
            patient=bpjs[6], unit_code="RANAP", specialty="INT", payer_code="BPJS",
            enc_type="inpatient", days_ago=self._days_ago(p2 + timedelta(days=10)),
            hours=96, complaint="Sesak napas memberat dan kaki bengkak",
            notes=[("medical_initial",
                    "Sesak memberat 3 hari, tidur dengan dua bantal, kaki bengkak.",
                    "JVP meningkat, ronki basah halus kedua basal, edema pretibial +2.",
                    "Gagal jantung kongestif dekompensasi.",
                    "Diuretik intravena, restriksi cairan, pantau balans cairan."),
                   ("soap",
                    "Sesak berkurang, kaki masih sedikit bengkak.",
                    "Ronki minimal, balans cairan negatif 900 mL/24 jam.",
                    "CHF perbaikan.",
                    "Lanjutkan diuretik oral, edukasi diet rendah garam.")],
            diagnoses=[("I50.0", "primary", "final"), ("I10", "comorbidity", "final")],
            consent_code="CONS-UMUM", nursing=True,
            labs=[{"tariff_code": "LAB-GINJAL", "values": {"UREUM": 62.0, "KREAT": 1.8}},
                  {"tariff_code": "LAB-ELEK", "values": {"NA": 132.0, "K": 3.2, "CL": 98.0}}],
            rads=[{"tariff_code": "RAD-THX",
                   "findings": "Kardiomegali dengan CTR 62%, corakan bronkovaskular meningkat.",
                   "impression": "Kardiomegali dengan tanda bendungan paru."}],
            want_summary=True, followup_days=10,
            bill_tariffs=("ADM-RI", "VISITE", "KAMAR", "ASKEP"),
        )
        claim_paid = self._claim_for(enc, 0.96)
        self._code_claim(claim_paid, "I50.0", comorbidities=[("I10", "comorbidity")])
        self._advance_to_finalized(claim_paid)

        enc = self._episode(
            "ep_pending",
            patient=bpjs[7], unit_code="RANAP", specialty="INT", payer_code="BPJS",
            enc_type="inpatient", days_ago=self._days_ago(p2 + timedelta(days=15)),
            hours=120, complaint="Demam, nyeri berkemih, dan menggigil",
            notes=[("medical_initial",
                    "Demam menggigil 3 hari, nyeri saat berkemih, nyeri pinggang kanan.",
                    "Nyeri ketok CVA kanan positif, suhu 39,1 °C, TD 100/62.",
                    "Pielonefritis akut.",
                    "Antibiotik intravena, hidrasi, kultur urin."),
                   ("soap",
                    "Demam turun, nyeri pinggang berkurang.",
                    "Suhu 37,2 °C, nyeri ketok CVA minimal.",
                    "Pielonefritis perbaikan.",
                    "Ganti antibiotik oral, rencana pulang.")],
            diagnoses=[("N39.0", "primary", "final")],
            consent_code="CONS-UMUM", nursing=True,
            labs=[{"tariff_code": "LAB-URIN",
                   "values": {"UR-LEU": 45.0, "UR-ERI": 12.0, "UR-PROT": 30.0}},
                  {"tariff_code": "LAB-DL", "values": {"WBC": 19.2}}],
            want_summary=True,
            bill_tariffs=("ADM-RI", "VISITE", "KAMAR", "ASKEP"),
            vitals={"temperature": 39.1, "systolic": 100, "diastolic": 62, "pulse": 110},
        )
        claim_pending = self._claim_for(enc, 0.88)
        self._code_claim(claim_pending, "N39.0")
        self._advance_to_finalized(claim_pending)

        enc = self._episode(
            "ep_dispute",
            patient=bpjs[8], unit_code="RANAP", specialty="INT", payer_code="BPJS",
            enc_type="inpatient", days_ago=self._days_ago(p2 + timedelta(days=19)),
            hours=60, complaint="Penurunan kesadaran mendadak",
            notes=[("medical_initial",
                    "Penurunan kesadaran mendadak, sebelumnya nyeri kepala hebat.",
                    "GCS E2M4V2, pupil anisokor, hemiparese kiri, TD 196/110.",
                    "Stroke infark luas hemisfer kanan.",
                    "Stabilisasi jalan napas, kontrol tekanan darah, CT kepala."),
                   ("soap",
                    "Kesadaran belum membaik, keluarga sudah diberi penjelasan prognosis.",
                    "GCS E1M3V1, refleks batang otak menurun.",
                    "Stroke infark luas dengan perburukan.",
                    "Perawatan suportif, komunikasi prognosis dengan keluarga.")],
            diagnoses=[("I63.9", "primary", "final"), ("I10", "comorbidity", "final")],
            consent_code="CONS-UMUM", nursing=True,
            rads=[{"tariff_code": "RAD-CTKEP",
                   "findings": "Area hipodens luas pada teritori arteri serebri media kanan "
                               "disertai efek massa ringan.",
                   "impression": "Infark luas teritori MCA kanan.",
                   "is_critical": True, "ack": "acknowledged",
                   "suggestion": "Evaluasi ulang bila terjadi perburukan klinis."}],
            want_summary=True, disposition="deceased",
            bill_tariffs=("ADM-RI", "VISITE", "KAMAR", "ASKEP"),
            vitals={"systolic": 196, "diastolic": 110, "pulse": 92, "spo2": 93},
        )
        claim_dispute = self._claim_for(enc, 0.82)
        self._code_claim(claim_dispute, "I63.9", comorbidities=[("I10", "comorbidity")])
        self._advance_to_finalized(
            claim_dispute,
            review_note="Tarif rumah sakit jauh di atas tarif grouper karena lama "
                        "rawat ICU; berkas dilengkapi resume dan CT kepala.",
        )

        # --- 10. Klaim yang tenggatnya tinggal hitungan hari --------------
        enc = self._episode(
            "ep_deadline",
            patient=bpjs[9], unit_code="POLI-PD", specialty="INT", payer_code="BPJS",
            enc_type="outpatient", days_ago=168, hours=4,
            complaint="Nyeri ulu hati berulang sejak 1 bulan",
            notes=[("soap",
                    "Nyeri ulu hati berulang, memberat saat telat makan.",
                    "Nyeri tekan epigastrium, tidak ada tanda perdarahan saluran cerna.",
                    "Gastritis kronik.",
                    "PPI 2 minggu, edukasi pola makan.")],
            diagnoses=[("K29.7", "primary", "final")],
            labs=[{"tariff_code": "LAB-DL", "values": {"HB": 12.2}}],
            want_summary=True,
        )
        self._claim_for(enc, 0.94)

        # --- Episode penunjang: nilai kritis yang belum diakui ------------
        self._episode(
            "ep_igd_critical",
            patient=umum[0], unit_code="IGD", specialty="BED", payer_code="UMUM",
            enc_type="emergency", days_ago=4, hours=6, triage="red",
            arrival_mode="ambulance",
            complaint="Trauma kepala setelah kecelakaan lalu lintas",
            notes=[("medical_initial",
                    "Kecelakaan lalu lintas, sempat pingsan, muntah dua kali.",
                    "GCS E3M5V4, hematom temporal kanan, tidak ada lateralisasi.",
                    "Cedera kepala sedang.",
                    "Observasi ketat, CT kepala, konsul bedah saraf.")],
            diagnoses=[("S06.0", "primary", "final")],
            consent_code="CONS-UMUM", nursing=True,
            rads=[{"tariff_code": "RAD-CTKEP",
                   "findings": "Perdarahan epidural tipis regio temporal kanan, "
                               "ketebalan 7 mm, tanpa midline shift.",
                   "impression": "Epidural hematoma temporal kanan.",
                   "is_critical": True,
                   "verified_at": fields.Datetime.now() - timedelta(days=4, hours=-7)}],
            want_summary=True,
            bill_tariffs=("ADM-RJ", "KONS-SP"),
            vitals={"pulse": 102, "systolic": 134, "diastolic": 84, "pain_score": 6},
        )

        self._episode(
            "ep_lab_pending",
            patient=umum[1], unit_code="POLI-UMUM", specialty=dpjp, payer_code="UMUM",
            enc_type="outpatient", days_ago=1, hours=4,
            complaint="Lemas dan kram otot sejak kemarin",
            notes=[("soap",
                    "Lemas seluruh badan, kram tungkai, riwayat diare 3 hari.",
                    "Turgor menurun, TD 104/66, nadi 100, refleks fisiologis menurun.",
                    "Hipokalemia pada gastroenteritis akut.",
                    "Koreksi kalium, rehidrasi oral, cek elektrolit ulang.")],
            diagnoses=[("E87.6", "primary", "final"), ("A09.9", "comorbidity", "final")],
            labs=[{"tariff_code": "LAB-ELEK",
                   "values": {"K": 2.3, "NA": 133.0, "CL": 96.0}}],
            want_summary=True, followup_days=4,
            bill_tariffs=("ADM-RJ", "KONS-UM"),
            vitals={"systolic": 104, "diastolic": 66, "pulse": 100},
        )

        # --- Episode dengan KLPCM terbuka lain (belum lewat tenggat) ------
        self._episode(
            "ep_klpcm_fresh",
            patient=umum[2], unit_code="POLI-GIGI", specialty="GIG", payer_code="UMUM",
            enc_type="outpatient", days_ago=1, hours=2,
            complaint="Gigi geraham bawah kanan berlubang dan nyeri",
            notes=[("soap",
                    "Nyeri gigi geraham bawah kanan, memberat saat minum dingin.",
                    "Karies profunda gigi 46, perkusi positif, tidak ada abses.",
                    "Pulpitis ireversibel gigi 46.",
                    "Perawatan saluran akar bertahap, analgetik.")],
            diagnoses=[("K29.7", "primary", "working")],
            want_summary=False,
            bill_tariffs=("ADM-RJ", "KONS-SP"),
        )

        self._episode(
            "ep_klpcm_igd",
            patient=umum[3], unit_code="IGD", specialty="SPU", payer_code="UMUM",
            enc_type="emergency", days_ago=7, hours=5, triage="yellow",
            complaint="Muntah dan diare cair sejak pagi",
            notes=[("medical_initial",
                    "Muntah 5 kali dan diare cair 7 kali sejak pagi.",
                    "Turgor menurun, mata cekung, TD 100/60, nadi 108.",
                    "Gastroenteritis akut dengan dehidrasi sedang.",
                    "Rehidrasi intravena, antiemetik, observasi 6 jam.")],
            diagnoses=[("A09.9", "primary", "final")],
            nursing=False, consent_code=None,
            want_summary=True,
            bill_tariffs=("ADM-RJ", "KONS-UM"),
            vitals={"systolic": 100, "diastolic": 60, "pulse": 108},
        )

        self._surgical_waitlist(umum)

    def _waitlist_case(self, key, patient, complaint, note, icd10, tariff_code,
                       days_ago, schedule_in_days, outcome, postpone=None):
        """Kunjungan bedah yang MASIH TERBUKA, menunggu jadwal operasinya.

        Sengaja tidak ditutup: papan operasi berisi pasien yang belum selesai
        dilayani, dan menutup kunjungannya hanya demi kerapian akan membuat
        angka penundaan operasi elektif kehilangan pasiennya.
        """
        encounter = self._anchor(key)
        if encounter:
            return encounter
        now = fields.Datetime.now()
        arrival = now - timedelta(days=days_ago)
        doctor = self._doctor("BED")
        encounter = self._open_encounter(
            patient, self._unit("POLI-BEDAH"), doctor, self._payer("UMUM"),
            arrival, "outpatient", complaint,
        )
        self._observation(encounter, arrival + timedelta(minutes=10))
        self._note(encounter, doctor, arrival + timedelta(minutes=30), "soap", *note)
        self._diagnoses(encounter, doctor, arrival + timedelta(minutes=40),
                        [(icd10, "primary", "final")])
        self._consent(encounter, doctor, "CONS-TIND")
        line = self._procedure_order(
            encounter, doctor, tariff_code,
            scheduled_at=now + timedelta(days=schedule_in_days),
            ordered_at=arrival + timedelta(hours=1),
        )
        schedule = line.procedure_schedule_ids
        if schedule:
            if outcome == "confirmed":
                schedule.action_confirm()
            elif outcome == "postponed":
                schedule.write({"planned_start": now - timedelta(days=1),
                                "planned_end": False,
                                "original_planned_start": now - timedelta(days=1)})
                schedule.action_postpone(
                    reason=postpone or "preparation",
                    note="Hasil laboratorium pra-operasi belum lengkap; "
                         "dijadwalkan ulang setelah hasil keluar.",
                    new_start=now + timedelta(days=schedule_in_days),
                )
        return self._keep(key, encounter)

    def _surgical_waitlist(self, umum):
        self._waitlist_case(
            "ep_sched_planned", umum[4],
            "Benjolan di lipat paha kanan yang keluar masuk",
            ("Benjolan lipat paha kanan sejak 6 bulan, keluar saat mengejan.",
             "Benjolan reponibel regio inguinal dextra, tidak nyeri, tidak ada tanda strangulasi.",
             "Hernia inguinalis lateralis dextra reponibel.",
             "Rencana herniotomi elektif, persiapan pra-operasi."),
            "K80.2", "TND-HERN", days_ago=3, schedule_in_days=4, outcome="planned",
        )
        self._waitlist_case(
            "ep_sched_confirmed", umum[5],
            "Nyeri perut kanan atas berulang setelah makan berlemak",
            ("Nyeri perut kanan atas berulang, memberat setelah makan berlemak.",
             "Murphy sign positif, tidak ikterik, USG: batu kandung empedu multipel.",
             "Kolelitiasis simtomatik.",
             "Rencana kolesistektomi laparoskopik elektif."),
            "K80.2", "TND-CHOL", days_ago=5, schedule_in_days=6, outcome="confirmed",
        )
        self._waitlist_case(
            "ep_sched_postponed", umum[6],
            "Nyeri perut kanan bawah hilang timbul",
            ("Nyeri perut kanan bawah hilang timbul 2 minggu, tanpa demam tinggi.",
             "Nyeri tekan McBurney ringan, tanda peritonitis tidak ada.",
             "Apendisitis kronik eksaserbasi akut.",
             "Rencana apendektomi elektif."),
            "K35.80", "TND-APP", days_ago=9, schedule_in_days=5,
            outcome="postponed", postpone="preparation",
        )

    # ------------------------------------------------------------------
    # D. Batch pengajuan, penyesuaian, dan nasib klaim di penjamin
    # ------------------------------------------------------------------
    def _claim_of(self, episode_key):
        encounter = self._anchor(episode_key)
        if not encounter:
            return self.env["hms.claim"]
        return self.env["hms.claim"].search(
            [("encounter_id", "=", encounter.id)], limit=1
        )

    def _batch(self, key, period, care_type, batch_type, fpk_no):
        existing = self._anchor(key)
        if existing:
            return existing
        Batch = self.env["hms.claim.batch"]
        payer = self._payer("BPJS")
        found = Batch.search([
            ("service_period", "=", period), ("care_type", "=", care_type),
            ("batch_type", "=", batch_type), ("payer_id", "=", payer.id),
        ], limit=1)
        if not found:
            found = self._as(Batch, "koder").create({
                "service_period": period, "care_type": care_type,
                "batch_type": batch_type, "payer_id": payer.id, "fpk_no": fpk_no,
            })
        return self._keep(key, found)

    def _fill_batch(self, batch, claims):
        ready = claims.filtered(lambda c: c.state == "finalized" and not c.batch_id)
        if ready and batch.reconciliation_state == "draft":
            self._as(batch, "koder").action_add_claims(ready.ids)
        return batch

    def _adjustment(self, key, claim, kind, amount, reason, authorize=False):
        existing = self._anchor(key)
        if existing:
            return existing
        adjustment = self._as(claim, "koder").action_issue_adjustment({
            "type": kind, "amount": amount, "reason": reason,
        })
        if authorize:
            # Pengesahan kerugian adalah wewenang berjenjang; yang mengesahkan
            # harus benar-benar manajemen, bukan seeding yang mengaku-ngaku.
            self._as(adjustment, "manajer").action_authorize()
        return self._keep(key, adjustment)

    def _batches(self):
        today = fields.Date.context_today(self)
        p1 = (today - relativedelta(days=45)).replace(day=1)
        p2 = (today - relativedelta(days=75)).replace(day=1)
        Claim = self.env["hms.claim"]

        # --- berkas reguler rawat jalan: sudah diajukan -------------------
        b1 = self._batch("batch_rj_reguler", p1, "outpatient", "regular",
                         "FPK/%s/RJ/001" % p1.strftime("%Y%m"))
        rj = self._claim_of("ep_sub_a") | self._claim_of("ep_sub_b")
        self._fill_batch(b1, rj)
        if b1.reconciliation_state == "draft" and b1.claim_ids:
            self._as(b1, "koder").action_submit()

        # --- berkas susulan rawat jalan: masih disusun --------------------
        b3 = self._batch("batch_rj_susulan", p1, "outpatient", "supplementary",
                         "FPK/%s/RJ/002" % p1.strftime("%Y%m"))
        self._fill_batch(b3, self._claim_of("ep_final"))

        # --- berkas reguler rawat inap: sudah direkonsiliasi --------------
        b2 = self._batch("batch_ri_reguler", p2, "inpatient", "regular",
                         "FPK/%s/RI/001" % p2.strftime("%Y%m"))
        ri = (self._claim_of("ep_appr") | self._claim_of("ep_paid")
              | self._claim_of("ep_pending") | self._claim_of("ep_dispute"))
        self._fill_batch(b2, ri)
        if b2.reconciliation_state == "draft" and b2.claim_ids:
            self._as(b2, "koder").action_submit()

        self._settle_claims()

        if b2.reconciliation_state == "submitted":
            self._as(b2, "verifikator").action_mark_verified()
        if b2.reconciliation_state == "verified":
            b2.write({
                "ba_no": "BA/%s/KC-BDG/001" % p2.strftime("%Y%m"),
                "ba_date": p2 + relativedelta(months=1, days=14),
                "note": "Berita acara hasil verifikasi diterima dari Kantor Cabang; "
                        "selisih verifikasi sudah dibukukan sebagai penyesuaian.",
            })
            self._as(b2, "verifikator").action_reconcile()
        return True

    def _settle_claims(self):
        """Nasib masing-masing klaim di meja penjamin."""
        claim = self._claim_of("ep_appr")
        if claim and claim.state == "submitted":
            self._as(claim, "verifikator").action_start_verification()
        if claim and claim.state == "bpjs_verifying":
            self._as(claim, "verifikator").action_approve(
                amount=round(claim.grouped_tariff + claim.topup_amount, 0)
            )

        claim = self._claim_of("ep_paid")
        if claim and claim.state == "submitted":
            self._as(claim, "verifikator").action_start_verification()
        if claim and claim.state == "bpjs_verifying":
            self._as(claim, "verifikator").action_approve(
                amount=round(claim.grouped_tariff + claim.topup_amount, 0)
            )
        if claim and claim.state == "approved":
            gap = round(claim.approved_amount * 0.02, -3) or 250000.0
            self._adjustment(
                "adj_verification_gap", claim, "verification_gap", gap,
                "Selisih hasil verifikasi penjamin: dua baris penunjang "
                "dinilai sudah termasuk paket CBG.", authorize=True,
            )
            self._as(claim, "verifikator").action_mark_paid(
                amount=claim.approved_amount - claim.adjustment_total
            )

        claim = self._claim_of("ep_pending")
        if claim and claim.state == "submitted":
            self._as(claim, "verifikator").action_start_verification()
        if claim and claim.state == "bpjs_verifying":
            claim.write({
                "pending_category": "document",
                "pending_reason": "Hasil kultur urin dan lembar persetujuan umum "
                                  "belum terlampir pada berkas klaim.",
            })
            self._as(claim, "verifikator").action_set_pending()
        if claim and claim.state == "pending" and not claim.pending_at:
            claim.write({"pending_at": fields.Datetime.now() - timedelta(days=21)})

        claim = self._claim_of("ep_dispute")
        if claim and claim.state == "submitted":
            self._as(claim, "verifikator").action_start_verification()
        if claim and claim.state == "bpjs_verifying":
            claim.write({
                "dispute_level": "branch",
                "review_note": "Penjamin menilai lama rawat tidak sesuai severity "
                               "level; rumah sakit mengajukan dispute dengan "
                               "melampirkan CT kepala dan catatan perkembangan.",
            })
            self._as(claim, "verifikator").action_open_dispute()
        if claim and claim.state == "dispute":
            self._adjustment(
                "adj_dispute_usulan", claim, "dispute_loss",
                round(claim.hospital_bill_amount * 0.05, -3) or 500000.0,
                "Usulan pembukuan kerugian bila dispute tingkat kantor cabang "
                "tidak dimenangkan. Belum diotorisasi — menunggu hasil dispute.",
            )
        return True

    # ------------------------------------------------------------------
    # E. Rekam medis: surat, sertifikat kematian, ROI, koreksi
    # ------------------------------------------------------------------
    def _medrec(self):
        self._medical_letters()
        self._death_certificate()
        self._roi_requests()
        self._correction_requests()

    def _letter(self, key, encounter, letter_type, purpose, body, sign=True, **extra):
        existing = self._anchor(key)
        if existing:
            return existing
        vals = {
            "type": letter_type,
            "patient_id": encounter.patient_id.id,
            "encounter_id": encounter.id,
            "practitioner_id": encounter.practitioner_id.id,
            "purpose": purpose,
            "body": body,
        }
        vals.update(extra)
        letter = self.env["hms.medical.letter"].create(vals)
        if sign:
            letter.action_sign()
        return self._keep(key, letter)

    def _medical_letters(self):
        today = fields.Date.context_today(self)
        enc = self._anchor("ep_coding")
        if enc:
            self._letter(
                "letter_sakit", enc, "sick_leave",
                "Keperluan izin kerja",
                "Yang bersangkutan memerlukan istirahat karena anemia berat yang "
                "sedang dalam pengobatan.",
                rest_from=today - timedelta(days=22),
                rest_to=today - timedelta(days=20),
            )
        enc = self._anchor("ep_paid")
        if enc:
            self._letter(
                "letter_ranap", enc, "hospitalization",
                "Keperluan klaim asuransi swasta",
                "Yang bersangkutan dirawat inap di RS Athera Medika karena gagal "
                "jantung kongestif dan telah dipulangkan dalam kondisi membaik.",
            )
        enc = self._anchor("ep_klpcm_fresh")
        if enc:
            self._letter(
                "letter_sehat", enc, "fit",
                "Keperluan melamar pekerjaan",
                "Berdasarkan pemeriksaan pada tanggal kunjungan, yang bersangkutan "
                "dalam keadaan sehat dan tidak ditemukan kelainan yang bermakna.",
                valid_until=today + timedelta(days=30),
            )
        enc = self._anchor("ep_igd_critical")
        if enc:
            # Sengaja dibiarkan draf: surat rujukan yang belum ditandatangani
            # adalah keadaan yang benar-benar ada di meja dokter, dan draf
            # memang tidak bernomor.
            self._letter(
                "letter_rujukan_draf", enc, "referral_support",
                "Rujukan ke RS tipe B untuk bedah saraf",
                "Mohon penanganan lebih lanjut atas pasien dengan epidural "
                "hematoma temporal kanan. Terlampir hasil CT kepala.",
                sign=False,
            )

    def _death_certificate(self):
        key = "death_cert_stroke"
        if self._anchor(key):
            return self._anchor(key)
        encounter = self._anchor("ep_dispute")
        if not encounter:
            return self.env["hms.death.certificate"]
        certificate = self.env["hms.death.certificate"].create({
            "patient_id": encounter.patient_id.id,
            "encounter_id": encounter.id,
            "died_at": (encounter.closed_at or fields.Datetime.now()) - timedelta(hours=2),
            "admitted_at": encounter.arrival_at,
            "place_of_death": "hospital",
            "manner": "natural",
            "cause_a_id": self._icd10("I63.9").id,
            "cause_a_interval": "2 hari",
            "cause_b_id": self._icd10("I10").id,
            "cause_b_interval": "10 tahun",
            "contributing_ids": [(6, 0, [self._icd10("E11.9").id])],
            "certified_by_id": encounter.practitioner_id.id,
            "note": "Keluarga telah diberi penjelasan; jenazah dibawa pulang keluarga.",
        })
        certificate.action_sign()
        return self._keep(key, certificate)

    def _roi_requests(self):
        Roi = self.env["hms.roi.request"]
        pmik = self._user("pmik")
        RoiAs = Roi.with_user(pmik) if pmik else Roi
        now = fields.Datetime.now()

        def consent_of(encounter):
            return self.env["hms.consent"].search([
                ("patient_id", "=", encounter.patient_id.id),
                ("state", "=", "signed"),
            ], limit=1)

        # 1. Penegak hukum, Ps. 35 — masih menunggu keputusan pimpinan.
        key = "roi_polisi"
        encounter = self._anchor("ep_igd_critical")
        if encounter and not self._anchor(key):
            request = RoiAs.create({
                "patient_id": encounter.patient_id.id,
                "encounter_ids": [(6, 0, encounter.ids)],
                "requester_type": "law_enforcement",
                "requester_name": "Bripka Dedi Firmansyah",
                "requester_identity_no": "NRP 87050123",
                "requester_organization": "Polrestabes Bandung",
                "requester_contact": "(022) 555-0912",
                "purpose": "Penyidikan perkara kecelakaan lalu lintas nomor "
                           "LP/B/214/IX/2026/SPKT.",
                "legal_basis": "art35",
                "requested_at": now - timedelta(days=2),
            })
            request.action_submit()
            self._keep(key, request)

        # 2. Pasien sendiri, Ps. 34 — sudah disetujui, dokumen belum diambil.
        key = "roi_pasien"
        encounter = self._anchor("ep_paid")
        if encounter and not self._anchor(key):
            consent = consent_of(encounter)
            request = RoiAs.create({
                "patient_id": encounter.patient_id.id,
                "encounter_ids": [(6, 0, encounter.ids)],
                "requester_type": "patient",
                "requester_name": encounter.patient_id.name,
                "requester_identity_no": encounter.patient_id.nik,
                "requester_contact": encounter.patient_id.phone,
                "purpose": "Pengurusan klaim asuransi kesehatan swasta.",
                "legal_basis": "art34",
                "consent_id": consent.id if consent else False,
                "requested_at": now - timedelta(days=5),
                "delivery_channel": "in_person",
                "document_ids": [
                    (0, 0, {"doc_type": "summary",
                            "description": "Ringkasan pulang rawat inap", "page_count": 2}),
                    (0, 0, {"doc_type": "lab_result",
                            "description": "Hasil laboratorium selama perawatan",
                            "page_count": 3}),
                ],
            })
            request.action_submit()
            self._as(request, "manajer").action_approve()
            self._keep(key, request)

        # 3. Asuransi, Ps. 34 — sudah diserahkan dengan tanda terima.
        key = "roi_asuransi"
        encounter = self._anchor("ep_appr")
        if encounter and not self._anchor(key):
            consent = consent_of(encounter)
            request = RoiAs.create({
                "patient_id": encounter.patient_id.id,
                "encounter_ids": [(6, 0, encounter.ids)],
                "requester_type": "insurance",
                "requester_name": "Rina Marlina",
                "requester_organization": "Asuransi Sehat Sentosa",
                "requester_contact": "klaim@sehatsentosa.example",
                "purpose": "Verifikasi klaim rawat inap peserta.",
                "legal_basis": "art34",
                "consent_id": consent.id if consent else False,
                "requested_at": now - timedelta(days=12),
                "delivery_channel": "courier_internal",
                "receipt_name": "Rina Marlina",
                "receipt_identity_no": "3273015507920004",
                "receipt_note": "Diterima dalam amplop tertutup, 5 lembar.",
                "document_ids": [
                    (0, 0, {"doc_type": "summary",
                            "description": "Ringkasan pulang", "page_count": 2}),
                    (0, 0, {"doc_type": "procedure_report",
                            "description": "Laporan apendektomi", "page_count": 1}),
                    (0, 0, {"doc_type": "lab_result",
                            "description": "Hasil darah lengkap", "page_count": 2}),
                ],
            })
            request.action_submit()
            self._as(request, "manajer").action_approve()
            request.action_deliver()
            self._keep(key, request)
        return True

    def _correction_requests(self):
        pmik = self._user("pmik")
        Correction = self.env["hms.correction.request"]
        CorrectionAs = Correction.with_user(pmik) if pmik else Correction

        def first_note(encounter):
            return self.env["hms.clinical.note"].search(
                [("encounter_id", "=", encounter.id)], order="id", limit=1
            )

        specs = [
            ("corr_diajukan", "ep_sub_a", "submitted",
             "Berat badan tertulis 78 kg pada asesmen, seharusnya 87 kg",
             "BB 78 kg", "BB 87 kg",
             "Salah ketik saat entri; angka 87 tertukar menjadi 78. Berat badan "
             "menentukan dosis metformin, sehingga perlu dikoreksi."),
            ("corr_disetujui", "ep_coding", "approved",
             "Sisi keluhan tertulis kanan, seharusnya kiri",
             "nyeri tungkai kanan", "nyeri tungkai kiri",
             "Sisi keluhan tertukar pada CPPT; pemeriksaan fisik dan hasil "
             "penunjang seluruhnya menunjuk sisi kiri."),
            ("corr_diterapkan", "ep_sub_b", "applied",
             "Jumlah muntah tertulis 2 kali, seharusnya 5 kali",
             "muntah 2 kali", "muntah 5 kali",
             "Jumlah muntah keliru dicatat; berpengaruh pada penilaian derajat "
             "dehidrasi yang dilaporkan."),
        ]
        for key, episode_key, target_state, field_label, old, new, reason in specs:
            if self._anchor(key):
                continue
            encounter = self._anchor(episode_key)
            if not encounter:
                continue
            note = first_note(encounter)
            if not note:
                continue
            request = CorrectionAs.create({
                "encounter_id": encounter.id,
                "target_model": note._name,
                "target_res_id": note.id,
                "target_label": "CPPT %s oleh %s" % (
                    fields.Datetime.to_string(note.noted_at),
                    note.author_id.display_name,
                ),
                "field_label": field_label,
                "entry_created_at": note.noted_at,
                "old_value": old,
                "new_value": new,
                "reason": reason,
            })
            request.action_submit()
            if target_state in ("approved", "applied"):
                self._as(request, "kapmik").action_approve()
            if target_state == "applied":
                request.write({
                    "addendum_reference": "Adendum CPPT pada kunjungan %s"
                                          % encounter.name,
                })
                request.action_mark_applied()
            self._keep(key, request)
        return True

    # ------------------------------------------------------------------
    # F. Keselamatan pasien: IKP dan komplain
    # ------------------------------------------------------------------
    INCIDENTS = [
        # key, type, category, unit, days_ago, report_after_hours, anonymous,
        # title/chronology, immediate action, target state, grade, root cause, recommendation
        ("ikp_obat_knc", "knc", "medication", "RANAP", 3, 6, False,
         "Perawat menyiapkan injeksi ceftriakson 2 g untuk pasien yang diresepkan 1 g. "
         "Kesalahan tertangkap saat double check sebelum obat diberikan.",
         "Obat dikembalikan ke depo, dosis disiapkan ulang sesuai resep.",
         "reported", False, False, False),
        ("ikp_jatuh_ktc", "ktc", "fall", "RANAP", 6, 10, False,
         "Pasien lansia turun dari tempat tidur tanpa bantuan dan terpeleset di kamar "
         "mandi. Tidak ditemukan cedera pada pemeriksaan.",
         "Pasien dibantu kembali ke tempat tidur, dilakukan pemeriksaan fisik lengkap.",
         "investigating", False, False, False),
        ("ikp_jatuh_ktd", "ktd", "fall", "RANAP", 14, 20, False,
         "Pasien risiko jatuh tinggi terjatuh saat hendak ke kamar mandi pada dini hari; "
         "gelang risiko jatuh tidak terpasang dan pagar tempat tidur turun.",
         "Pemeriksaan segera oleh dokter jaga, foto pergelangan tangan kiri, imobilisasi.",
         "graded", "yellow",
         "Asesmen risiko jatuh tidak diulang setelah pasien mendapat sedatif malam; "
         "penanda risiko dan pagar tempat tidur tidak diverifikasi saat operan shift.",
         "Wajibkan verifikasi penanda risiko jatuh dan posisi pagar pada setiap operan "
         "shift, dan ulang asesmen setelah pemberian sedatif."),
        ("ikp_sentinel", "sentinel", "procedure", "RANAP", 45, 8, False,
         "Kasa operasi tertinggal dan baru diketahui pada foto evaluasi pasca operasi, "
         "sehingga pasien menjalani operasi ulang.",
         "Operasi pengangkatan kasa dilakukan hari yang sama; keluarga diberi penjelasan "
         "terbuka oleh DPJP.",
         "graded", "red",
         "Penghitungan kasa dilakukan satu kali dan tidak didokumentasikan pada surgical "
         "safety checklist; jumlah kasa awal tidak dicatat.",
         "Terapkan penghitungan kasa dua orang pada tiga titik (sebelum, saat menutup, "
         "setelah menutup) dengan dokumentasi wajib pada checklist."),
        ("ikp_identifikasi", "knc", "identification", "LAB", 22, 5, False,
         "Dua tabung darah dengan nama pasien mirip hampir tertukar saat pelabelan; "
         "perbedaan tanggal lahir menyelamatkan proses.",
         "Pelabelan diulang di depan pasien dengan verifikasi dua identitas.",
         "closed", "blue",
         "Pelabelan dilakukan jauh dari sisi pasien dan hanya memakai nama.",
         "Pelabelan wajib dilakukan di sisi pasien dengan verifikasi nama dan tanggal lahir."),
        ("ikp_spesimen", "ktd", "specimen", "LAB", 30, 12, False,
         "Spesimen darah hemolisis tidak terdeteksi sehingga hasil kalium dilaporkan "
         "palsu tinggi; pasien sempat mendapat terapi yang tidak diperlukan.",
         "Hasil ditarik, pengambilan ulang dilakukan, DPJP diberi tahu langsung.",
         "closed", "green",
         "Kriteria penolakan spesimen belum dipakai konsisten pada shift malam.",
         "Sosialisasi ulang kriteria penolakan spesimen dan pemasangan daftar periksa "
         "di meja penerimaan sampel."),
        ("ikp_anonim", "kpc", "equipment", "IGD", 2, 4, True,
         "Dua dari empat monitor tanda vital di ruang tindakan tidak berfungsi sejak "
         "pekan lalu dan belum diperbaiki.",
         "Monitor dipindahkan dari ruang observasi sebagai pengganti sementara.",
         "reported", False, False, False),
        ("ikp_komunikasi", "ktc", "communication", "POLI-PD", 9, 60, False,
         "Hasil kritis kalium rendah disampaikan lewat pesan singkat dan tidak "
         "dikonfirmasi ulang; DPJP baru membaca enam jam kemudian.",
         "DPJP dihubungi langsung lewat telepon dan instruksi koreksi dijalankan.",
         "investigating", False, False, False),
    ]

    COMPLAINTS = [
        # key, channel, category, grade, days_ago, unit, subject, detail, state, outcome
        ("kom_tunggu", "verbal", "waiting_time", "green", 2, "POLI-PD",
         "Waktu tunggu poli lebih dari dua jam",
         "Pasien datang pukul 08.00 dan baru dipanggil pukul 10.20 padahal nomor "
         "antrian urutan kesembilan.",
         "in_progress", False),
        ("kom_sikap", "whatsapp", "service_attitude", "yellow", 5, "IGD",
         "Petugas dinilai kurang ramah saat pendaftaran IGD",
         "Keluarga merasa dijawab dengan nada tinggi saat menanyakan kondisi pasien.",
         "responded", False),
        ("kom_biaya", "email", "cost", "yellow", 11, "MANAJ",
         "Rincian biaya tidak dijelaskan sebelum tindakan",
         "Pasien umum merasa tidak menerima perkiraan biaya sebelum tindakan hecting "
         "dilakukan.",
         "closed", "resolved"),
        ("kom_fasilitas", "suggestion_box", "facility", "green", 16, "RANAP",
         "Kamar mandi bangsal licin dan pegangan tangan longgar",
         "Pelapor khawatir pasien lansia terpeleset; pegangan di dinding goyang.",
         "closed", "resolved"),
        ("kom_makanan", "survey", "food", "green", 8, "RANAP",
         "Makanan pasien datang dalam keadaan dingin",
         "Makan siang tiba pukul 13.30 dalam keadaan dingin selama tiga hari berturut-turut.",
         "received", False),
        ("kom_klinis", "regulator", "clinical", "red", 20, "RANAP",
         "Keluarga mempertanyakan keterlambatan penanganan",
         "Keluarga menyampaikan keberatan melalui dinas kesehatan atas dugaan "
         "keterlambatan tindakan pada pasien stroke.",
         "responded", False),
    ]

    def _safety(self):
        self._incidents()
        self._complaints()

    def _incidents(self):
        Report = self.env["hms.incident.report"]
        now = fields.Datetime.now()
        for (key, kind, category, unit_code, days_ago, report_after, anonymous,
             chronology, immediate, target, grade, root_cause, recommendation) \
                in self.INCIDENTS:
            if self._anchor(key):
                continue
            occurred = now - timedelta(days=days_ago)
            report = Report.create({
                "is_anonymous": anonymous,
                "reporter_id": False if anonymous else self._nurse(days_ago % 8).id,
                "reporter_unit_id": self._unit(unit_code).id,
                "unit_id": self._unit(unit_code).id,
                "occurred_at": occurred,
                "incident_type": kind,
                "category": category,
                "chronology": chronology,
                "immediate_action": immediate,
                "patient_harmed": kind in ("ktd", "sentinel"),
            })
            report.action_report()
            # Waktu lapor dikembalikan ke waktu nyatanya: penanda "terlambat
            # lapor" adalah indikator mutu, dan seluruh laporan demo yang
            # dilaporkan "sekarang" akan membuat indikator itu selalu merah.
            report.write({"reported_at": occurred + timedelta(hours=report_after)})
            actor = self._as(report, "kp")
            if target in ("investigating", "graded", "closed"):
                actor.action_start_investigation()
            if target in ("graded", "closed"):
                report.write({"grade": grade, "root_cause": root_cause,
                              "recommendation": recommendation})
                actor.action_grade()
            if target == "closed":
                report.write({
                    "closure_note": "Rekomendasi sudah dijalankan dan dipantau selama "
                                    "satu bulan tanpa kejadian berulang.",
                })
                actor.action_close()
            self._keep(key, report)
        return True

    def _complaints(self):
        Complaint = self.env["hms.complaint"]
        now = fields.Datetime.now()
        for (key, channel, category, grade, days_ago, unit_code, subject, detail,
             target, outcome) in self.COMPLAINTS:
            if self._anchor(key):
                continue
            received = now - timedelta(days=days_ago)
            complaint = Complaint.create({
                "channel": channel, "category": category, "grade": grade,
                "unit_id": self._unit(unit_code).id,
                "complainant_name": "Keluarga pasien",
                "complainant_relation": "family",
                "contact": "08%d" % (1200000000 + days_ago * 7777),
                "subject": subject, "detail": detail,
                "received_at": received,
            })
            actor = self._as(complaint, "kp")
            actor.action_receive()
            if target in ("in_progress", "responded", "closed"):
                actor.action_start()
            if target in ("responded", "closed"):
                complaint.write({
                    "response": "Kami menyampaikan permohonan maaf dan telah "
                                "menjelaskan langkah perbaikan kepada pelapor.",
                    "corrective_action": "Unit terkait menjalankan perbaikan dan "
                                         "hasilnya dipantau kepala unit.",
                })
                actor.action_respond()
                complaint.write({"responded_at": received + timedelta(hours=8)})
            if target == "closed":
                complaint.write({"outcome": outcome})
                actor.action_close()
            self._keep(key, complaint)
        return True

    # ------------------------------------------------------------------
    # G. Rencana kontrol
    # ------------------------------------------------------------------
    def _followups(self):
        Plan = self.env["hms.followup.plan"]
        today = fields.Date.context_today(self)

        # Satu rencana yang sudah dipasangkan ke jadwal poli.
        encounter = self._anchor("ep_sub_a")
        if encounter:
            plan = Plan.search([("encounter_id", "=", encounter.id)], limit=1)
            if plan and plan.state == "planned":
                plan.action_schedule()

        # Satu rencana yang pasiennya tidak datang. Dibuat langsung, bukan dari
        # resume: rencana kontrol memang boleh lahir di meja pendaftaran.
        key = "fup_missed"
        encounter = self._anchor("ep_deadline")
        if encounter and not self._anchor(key):
            plan = Plan.create({
                "encounter_id": encounter.id,
                "practitioner_id": encounter.practitioner_id.id,
                "unit_id": encounter.unit_id.id,
                "planned_date": today - timedelta(days=12),
                "kind": "control",
                "instruction": "Kontrol ulang membawa hasil endoskopi dan sisa obat.",
            })
            plan.action_mark_missed()
            self._keep(key, plan)
        return True
