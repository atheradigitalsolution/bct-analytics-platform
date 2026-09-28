# -*- coding: utf-8 -*-
"""Identitas pasien demo: NIK yang sah secara struktur, dan pembersihan pasien uji.

KENAPA NIK DIBANGKITKAN, BUKAN DIKARANG
---------------------------------------
NIK Indonesia bukan nomor acak. Enam digit pertama adalah kode wilayah
(provinsi, kabupaten/kota, kecamatan), enam berikutnya adalah tanggal lahir
``DDMMYY`` dengan **tanggal ditambah 40 untuk perempuan**, dan empat terakhir
nomor urut. Orang rumah sakit membaca NIK setiap hari; mereka melihat kaidah
+40 tanpa perlu berpikir.

Karena itu dua bentuk kegagalan harus dihindari sekaligus:

* **Seragam.** Lima puluh pasien dengan awalan yang sama persis terbaca
  sebagai data karangan pada pandangan pertama.
* **Sah tapi berbohong.** NIK yang mengkode tanggal lahir yang BUKAN milik
  pasiennya justru lebih buruk daripada yang seragam: ia terlihat benar
  sampai seseorang membandingkannya dengan kolom tanggal lahir — dan orang
  itu biasanya adalah calon klien yang sedang mencari alasan untuk tidak
  percaya.

Yang dipalsukan adalah **orangnya**, bukan strukturnya. Kode wilayah di bawah
adalah kode BPS yang benar untuk wilayah di sekitar Bandung (tempat rumah
sakit fiktif ini berada); nama, tanggal lahir, dan nomor urutnya karangan.

DETERMINISTIK, DAN KENAPA ITU SYARAT
------------------------------------
NIK diturunkan dari ``id`` pasien, bukan dari angka acak. Penyemai berjalan
lagi pada setiap ``-u``; NIK yang berubah tiap kali akan memutus setiap
berkas, klaim, dan tangkapan layar yang sudah menyebutnya.

Keunikannya **struktural, bukan kebetulan**: indeks wilayah adalah
``id % len(NIK_REGIONS)`` dan nomor urutnya ``id // len(NIK_REGIONS)``,
sehingga pasangan (wilayah, nomor urut) memetakan balik ke satu ``id`` saja.
Dua pasien yang lahir pada tanggal yang sama tetap tidak dapat bertabrakan.
Pembungkusan nomor urut empat digit akan merusak sifat itu diam-diam, jadi
ia **ditolak keras** alih-alih dibungkus.
"""
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Kode wilayah BPS yang nyata — itulah yang membuat NIK sah secara struktur.
# Semuanya di sekitar Bandung, tempat RS Athera Medika berada. Tujuh kode
# yang BERBEDA: dua entri dengan kode yang sama akan meruntuhkan pembuktian
# keunikan di atas.
NIK_REGIONS = [
    ("327301", "Kota Bandung — Sukasari"),
    ("327306", "Kota Bandung — Andir"),
    ("327311", "Kota Bandung — Kiaracondong"),
    ("327318", "Kota Bandung — Buahbatu"),
    ("320410", "Kabupaten Bandung — Dayeuhkolot"),
    ("327701", "Kota Cimahi — Cimahi Selatan"),
    ("321108", "Kabupaten Sumedang — Jatinangor"),
]

# Nomor urut NIK hanya empat digit dan dimulai dari 1.
NIK_MAX_SERIAL = 9999

# Tiga pasien yang lahir dari uji coba endpoint, bukan dari penyemaian.
#
# KENAPA DIPULIHKAN, BUKAN DIHAPUS
# --------------------------------
# Rencana pertama adalah menghapus ketiganya beserta tanggungannya. Tiga
# pagar yang berbeda, ketiganya disengaja dan ketiganya benar, menolak:
#
#   * ``hms.access.log.unlink()`` menolak siapa pun kecuali pembersihan
#     retensi — "jejak audit yang bisa dihapus bukan jejak audit";
#   * ``hms.medical.letter.unlink()`` menolak surat yang sudah bernomor
#     (SKM-202609-0058 sudah ditandatangani) supaya deret nomornya tidak
#     berlubang;
#   * ``hms.roi.request.unlink()`` menolak permintaan yang sudah diajukan
#     (ROI-202609-0243) dengan alasan yang sama.
#
# Ketiganya memakai ``ondelete='restrict'`` di Postgres, jadi selama anaknya
# ada, pasiennya tidak dapat dihapus sama sekali. Menghapusnya menuntut
# melanggar tiga invariant sekaligus — dan invariant yang dilanggar untuk
# merapikan data demo adalah invariant yang sudah tidak berlaku.
#
# Yang dikerjakan sebagai gantinya mencapai hasil yang sama di layar tanpa
# menyentuh satu pun pagar: ketiganya DIBERI IDENTITAS FIKTIF YANG PANTAS.
# Mereka memang pasien demo — seluruh isi klinisnya (nilai kritis IGD,
# hipokalemia, KLPCM gigi) dibuat oleh penyemai ini sendiri, karena
# ``_patient_pools()`` mengurutkan per id dan merekalah pasien UMUM dengan id
# terendah. Yang salah hanya namanya, dan nama placeholder yang diganti nama
# fiktif yang benar bukan pemalsuan apa pun: keduanya sama-sama karangan,
# yang satu kebetulan terbaca sebagai sisa uji coba.
#
# RM-2026-000050 tidak ada di sini dan tidak perlu disentuh: ia dibuat pada
# stempel waktu yang sama dengan 47 pasien semaian massal lainnya.
PROBE_PATIENTS = [
    # (nomor RM, nama lama yang harus hilang, nama baru, tgl lahir, telepon,
    #  alamat, golongan darah, status perkawinan)
    ("RM-2026-000001", "Uji API", "Rizky Firmansyah", "1991-07-14",
     "081120000114", "Jl. Sukajadi No. 112, Bandung", "o", "married"),
    ("RM-2026-000002", "Beda", "Teguh Wibowo", "1984-03-02",
     "081120000232", "Jl. Cibaduyut Raya No. 27, Bandung", "b", "married"),
    ("RM-2026-000003", "Uji API Dua", "Salma Nuraini", "1996-11-25",
     "081120000376", "Jl. Jatinangor Km. 20 No. 8, Sumedang", "a", "single"),
]

# Layanan antrian kembar yang lahir dari uji coba: kodenya POLI-UM sementara
# layanan semaian bernama POLI-UMUM, dan keduanya berjudul "Poli Umum" di
# layar. Diarsipkan, bukan dihapus — tiketnya sudah terbit dan nomor yang
# pernah keluar tidak dihapus dari riwayat.
PROBE_QMS_SERVICES = ["POLI-UM"]


def nik_for(patient_id, birth_date, gender):
    """NIK 16 digit yang konsisten dengan tanggal lahir dan jenis kelamin.

    ``PPRRSS`` + ``DDMMYY`` (tanggal +40 bila perempuan) + ``NNNN``.
    """
    if not patient_id or patient_id < 1:
        raise ValueError("nik_for membutuhkan id pasien yang sudah tersimpan.")
    if not birth_date:
        raise ValueError("nik_for membutuhkan tanggal lahir.")
    slot = patient_id // len(NIK_REGIONS)
    if slot + 1 > NIK_MAX_SERIAL:
        raise ValueError(
            "id pasien %s melampaui nomor urut NIK empat digit; membungkusnya "
            "akan menghasilkan NIK kembar tanpa satu pun galat." % patient_id
        )
    region = NIK_REGIONS[patient_id % len(NIK_REGIONS)][0]
    day = birth_date.day + (40 if gender == "female" else 0)
    return "%s%02d%02d%02d%04d" % (
        region, day, birth_date.month, birth_date.year % 100, slot + 1,
    )


class HmsDemoBuilder(models.AbstractModel):
    _inherit = "hms.demo.builder"

    # ------------------------------------------------------------------
    # NIK
    # ------------------------------------------------------------------
    @api.model
    def _assign_niks(self):
        """Tulis ulang NIK setiap pasien demo agar cocok dengan recordnya.

        Idempoten: pasien yang NIK-nya sudah benar tidak disentuh sama sekali,
        jadi ``-u`` kedua tidak menghasilkan satu pun tulisan.
        """
        self._assert_demo_database()
        Patient = self.env["hms.patient"].sudo()
        patients = Patient.search([
            ("birth_date", "!=", False),
            ("is_anonymous", "=", False),
        ], order="id")
        targets = {p: nik_for(p.id, p.birth_date, p.gender) for p in patients}
        changing = {p: nik for p, nik in targets.items() if p.nik != nik}
        if not changing:
            return 0
        # Tabrakan SEMENTARA nyata: NIK tujuan seorang pasien bisa kebetulan
        # sama dengan NIK LAMA pasien lain yang juga sedang diganti. Urutan
        # penulisan apa pun bisa menabraknya, jadi yang bertabrakan diparkir
        # dulu di nilai antara yang mustahil dipakai (tidak ada provinsi 99)
        # sebelum nilai sebenarnya ditulis.
        occupied = {p.nik: p for p in patients if p.nik}
        blocked = [p for p, nik in changing.items()
                   if occupied.get(nik) is not None and occupied[nik] != p]
        for index, patient in enumerate(blocked, start=1):
            patient.write({"nik": "99%014d" % index})
        if blocked:
            self.env.flush_all()
        for patient, nik in changing.items():
            patient.write({"nik": nik})
        self.env.flush_all()
        _logger.info("SIMRS demo: %s NIK pasien diselaraskan", len(changing))
        return len(changing)

    @api.model
    def _deduplicate_patient_names(self):
        """Satu nama, satu pasien — di register demo, bukan di dunia nyata.

        Nama kembar memang terjadi di rumah sakit sungguhan; itulah gunanya
        nomor rekam medis. Tetapi pada papan bed berisi dua puluh baris, dua
        baris bernama sama terbaca sebagai data yang dibangkitkan, bukan
        sebagai kebetulan — dan di sini memang begitu asalnya.

        Yang dipertahankan adalah pasien dengan id terkecil, supaya nama yang
        sudah lebih lama dipakai tidak berubah. Idempoten: sesudah lintasan
        pertama tidak ada lagi nama kembar.
        """
        self._assert_demo_database()
        Patient = self.env["hms.patient"].sudo()
        patients = Patient.search([], order="id")
        seen, duplicates = set(), []
        for patient in patients:
            if patient.name in seen:
                duplicates.append(patient)
            else:
                seen.add(patient.name)
        if not duplicates:
            return 0
        for patient in duplicates:
            name = self._unused_patient_name(patient.gender or "male", seen)
            seen.add(name)
            patient.write({"name": name})
        _logger.info("SIMRS demo: %s nama pasien kembar diganti", len(duplicates))
        return len(duplicates)

    # ------------------------------------------------------------------
    # Pasien uji
    # ------------------------------------------------------------------
    @api.model
    def _restore_probe_patients(self):
        """Beri identitas yang pantas kepada tiga pasien sisa uji coba.

        Lihat catatan di ``PROBE_PATIENTS`` untuk alasan ini bukan
        penghapusan. Idempoten: pasien yang namanya sudah benar dilewati,
        dan nama lama dicocokkan persis supaya menjalankan ini dua kali tidak
        menimpa apa pun.
        """
        self._assert_demo_database()
        Patient = self.env["hms.patient"].sudo()
        touched = 0
        for (mrn, old_name, new_name, birth, phone, address,
             blood, marital) in PROBE_PATIENTS:
            patient = Patient.search([("mrn", "=", mrn)], limit=1)
            if not patient or patient.name != old_name:
                continue
            patient.write({
                "name": new_name,
                "birth_date": birth,
                "phone": phone,
                "address_street": address,
                "blood_type": blood,
                "marital_status": marital,
                "default_payer_id": self.env["hms.payer"].search(
                    [("code", "=", "UMUM")], limit=1).id,
            })
            # Chatter masih menyimpan nama lamanya sebagai riwayat perubahan,
            # dan form pasien di backend menampilkannya. Yang dibuang hanya
            # pesan pada record pasien ini; log akses rekam medis — jejak
            # audit yang sesungguhnya — tidak disentuh sama sekali.
            self.env["mail.message"].sudo().search([
                ("model", "=", "hms.patient"), ("res_id", "=", patient.id),
            ]).unlink()
            touched += 1
        if touched:
            _logger.info("SIMRS demo: %s pasien sisa uji coba diberi identitas "
                         "fiktif yang pantas", touched)
        return touched

    @api.model
    def _cancel_stale_registrations(self):
        """Batalkan pendaftaran yang tidak pernah dilayani sampai harinya lewat.

        Kunjungan berstatus Terdaftar dari dua hari lalu bukan kunjungan yang
        sedang berjalan; di loket sungguhan ia batal saat jam pelayanan
        tutup. Dibiarkan, ia muncul selamanya di daftar pasien yang sedang
        dilayani. Dibatalkan lewat ``action_cancel()`` supaya jejaknya tetap
        ada — kunjungan memang tidak boleh dihapus.
        """
        self._assert_demo_database()
        today = fields.Date.context_today(self)
        stale = self.env["hms.encounter"].sudo().search([
            ("state", "=", "registered"),
            ("arrival_at", "<", "%s 00:00:00" % today),
        ])
        if not stale:
            return 0
        stale.action_cancel()
        _logger.info("SIMRS demo: %s pendaftaran basi dibatalkan", len(stale))
        return len(stale)

    @api.model
    def _archive_probe_qms_services(self):
        """Arsipkan layanan antrian kembar sisa uji coba."""
        self._assert_demo_database()
        duplicates = self.env["hms.qms.service"].sudo().search([
            ("code", "in", PROBE_QMS_SERVICES), ("active", "=", True),
        ])
        if not duplicates:
            return 0
        duplicates.write({"active": False})
        _logger.info("SIMRS demo: %s layanan antrian kembar diarsipkan",
                     len(duplicates))
        return len(duplicates)
