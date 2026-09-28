# -*- coding: utf-8 -*-
"""Pekerjaan penunjang yang SEDANG BERJALAN: lab, radiologi, apotek.

KENAPA BERKAS INI ADA
---------------------
``hms_demo_content.py`` menyemai riwayat dan ``hms_demo_today.py`` menyemai
papan hari ini. Keduanya menjalankan setiap order sampai tuntas — hasil lab
``verified``, ekspertise ``verified``, resep ``dispensed`` — karena yang
dibuktikan di sana adalah alurnya bisa selesai.

Akibatnya tiga layar justru kosong. Worklist laboratorium, worklist radiologi,
dan antrian apotek semuanya menampilkan **pekerjaan yang belum selesai**::

    /api/v1/lab/worklist        hms.lab.result.state  IN (pending, entered, validated)
    /api/v1/radiology/worklist  hms.rad.report.state  IN (scheduled, performed, reported)
    /api/v1/pharmacy/queue      hms.prescription.state IN (submitted, verified, preparing, ready)

Rumah sakit yang tidak punya satu pun pemeriksaan di meja adalah rumah sakit
yang tutup — dan ketiga layar itu diperagakan berdampingan dengan dasbor yang
penuh, sehingga kekosongannya justru yang paling terlihat.

TIGA KEPUTUSAN YANG MEMBENTUK BERKAS INI
----------------------------------------
**Pekerjaan yang selesai tidak dihapus.** Yang ditambahkan di sini adalah
lapisan pekerjaan berjalan DI ATAS pekerjaan selesai yang sudah ada. Penyemai
yang memindahkan semuanya ke antrian akan membuat ketiga layar penuh sambil
membuat alurnya berbohong: laboratorium yang tidak pernah mengeluarkan hasil.

**Setiap order menempel pada kunjungan yang memang menjelaskannya.** Order
digantung pada jangkar kunjungan hari ini (``tv_*``) dan admisi yang sedang
berjalan (``adm_*``), dan indikasi klinisnya diambil dari rencana yang sudah
tertulis di CPPT kunjungan itu — "evaluasi foto toraks" pada pasien pneumonia,
"pantau trombosit" pada pasien DBD, "koreksi kalium" pada pasien hipokalemia.
Order penunjang yang menggantung pada pasien acak adalah hal pertama yang
ditunjuk orang rumah sakit.

**Sedikit tapi bersebaran.** Lima sampai delapan baris per layar dengan status
yang berbeda-beda lebih meyakinkan daripada daftar panjang yang seluruhnya
berada di satu status — yang terakhir memperagakan antrian macet, bukan alur
yang hidup.

SPESIMEN
--------
Hasil lab baru lahir saat ``hms.order.line.action_start()`` dipanggil, dan di
laboratorium sungguhan yang memulai pemeriksaan adalah PENERIMAAN SPESIMEN
(``action_receive_specimen`` — satu tombol, dua akibat). Penyemai lama
memanggil ``action_start()`` langsung, sehingga tiga belas pemeriksaan
tercatat selesai atas spesimen yang tidak pernah diterima. ``_lab()`` sekarang
lewat gerbang pra-analitik, dan ``_repair_specimen_history()`` membereskan
baris lama.

IDEMPOTENSI
-----------
Semua berjangkar ``ir.model.data`` seperti bagian demo lainnya, jadi ``-u``
kedua tidak menambah apa pun.
"""
import logging
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# --- laboratorium ---------------------------------------------------------
# (kunci, jangkar kunjungan, tarif, indikasi klinis, prioritas, menit lalu,
#  berhenti di, nilai)
#
# "berhenti di" adalah status yang harus terlihat di worklist:
#   ordered    — order masuk, SPESIMEN BELUM DIAMBIL (belum ada baris hasil)
#   pending    — spesimen diterima, pemeriksaan di meja, angka belum ada
#   entered    — angka sudah diinput analis, menunggu validasi
#   validated  — divalidasi analis, menunggu verifikasi dokter penanggung jawab
#   verified   — selesai; dipakai hanya untuk nilai kritis yang lingkarannya
#                masih terbuka, karena jam TBaK baru berjalan setelah verifikasi
LAB_WORKLIST = [
    ("wl_lab_dl_anemia", "tv_pd_04", "LAB-DL",
     "Lemas dan pucat 2 minggu, konjungtiva anemis — telusur anemia.",
     "routine", 40, "pending", {}),
    ("wl_lab_dl_febris", "tv_um_05", "LAB-DL",
     "Demam 2 hari tanpa fokus infeksi yang jelas — evaluasi leukosit dan trombosit.",
     "routine", 55, "entered",
     {"HB": 13.1, "WBC": 3.8, "PLT": 118.0, "HCT": 39.5}),
    ("wl_lab_urin_isk", "tv_igd_04", "LAB-URIN",
     "Demam menggigil dengan nyeri berkemih dan nyeri ketok CVA kanan positif.",
     "urgent", 35, "validated",
     {"UR-PROT": 30.0, "UR-GLU": 2.0, "UR-LEU": 45.0, "UR-ERI": 8.0}),
    ("wl_lab_dl_dbd", "adm_ang_08", "LAB-DL",
     "Demam berdarah dengue hari ke-4 — pemantauan trombosit dan hematokrit tiap 12 jam.",
     "urgent", 25, "entered",
     {"HB": 15.2, "WBC": 3.1, "PLT": 42.0, "HCT": 49.0}),
    ("wl_lab_ginjal_ckd", "adm_ang_05", "LAB-GINJAL",
     "Penyakit ginjal kronik stadium 5 — ureum dan kreatinin ulang sebelum "
     "pemasangan akses hemodialisis.",
     "routine", 70, "validated",
     {"UREUM": 178.0, "KREAT": 7.2, "UA": 9.8}),
    ("wl_lab_dl_pneumonia", "adm_mel_01", "LAB-DL",
     "Pneumonia komunitas hari rawat ke-3 — evaluasi leukosit setelah antibiotik.",
     "routine", 20, "pending", {}),
    ("wl_lab_dl_pratransfusi", "adm_mel_06", "LAB-DL",
     "Anemia berat — hemoglobin ulang sebelum kantong transfusi berikutnya.",
     "urgent", 15, "ordered", {}),
    ("wl_lab_dl_dbd_anak", "adm_dah_01", "LAB-DL",
     "Demam berdarah dengue anak hari ke-4 — pemantauan trombosit tiap 12 jam.",
     "urgent", 10, "ordered", {}),
    # Nilai kritis yang lingkarannya MASIH TERBUKA. Kaliumnya 2,3 mmol/L —
    # di bawah ambang kritis 2,5 — pada pasien yang memang dirawat karena
    # hipokalemia setelah diare panjang, dan resep koreksi kaliumnya menunggu
    # telaah apoteker di antrian farmasi di bawah. Satu kasus, tiga layar.
    ("wl_lab_elek_hipokalemia", "adm_ang_07", "LAB-ELEK",
     "Hipokalemia pada gastroenteritis akut — kalium ulang sebelum koreksi berikutnya.",
     "urgent", 30, "verified",
     {"NA": 133.0, "K": 2.3, "CL": 96.0}),
]

# --- radiologi ------------------------------------------------------------
# (kunci, jangkar kunjungan, tarif, indikasi klinis, menit lalu, berhenti di,
#  temuan, kesan, saran)
RAD_WORKLIST = [
    ("wl_rad_thx_pneumonia", "adm_mel_01", "RAD-THX",
     "Pneumonia komunitas hari rawat ke-3 — evaluasi infiltrat paru kanan bawah.",
     60, "scheduled", None, None, None),
    ("wl_rad_thx_geriatri", "adm_ang_06", "RAD-THX",
     "Pneumonia pada lanjut usia — evaluasi infiltrat paru kiri bawah.",
     45, "performed", None, None, None),
    ("wl_rad_thx_anak", "adm_dah_02", "RAD-THX",
     "Pneumonia anak dengan napas cepat dan retraksi subkostal — konfirmasi infiltrat.",
     35, "scheduled", None, None, None),
    ("wl_rad_usg_kolelitiasis", "adm_mel_03", "RAD-USG",
     "Nyeri perut kanan atas berulang setelah makan berlemak — curiga batu kandung empedu.",
     90, "reported",
     "Kandung empedu berdinding tidak menebal. Tampak dua bayangan hiperekoik "
     "disertai acoustic shadow berukuran 11 mm dan 8 mm di dalam lumen, mobile "
     "pada perubahan posisi. Duktus biliaris intrahepatik dan ekstrahepatik "
     "tidak melebar. Hepar, pankreas, lien, dan kedua ginjal dalam batas normal.",
     "Kolelitiasis multipel tanpa tanda kolesistitis akut.",
     "Korelasikan dengan klinis dan laboratorium; evaluasi ulang bila nyeri memberat."),
    ("wl_rad_usg_apendisitis", "adm_mel_07", "RAD-USG",
     "Nyeri perut kanan bawah dengan nyeri tekan McBurney positif — curiga apendisitis akut.",
     50, "performed", None, None, None),
    ("wl_rad_thx_nyeri_dada", "tv_igd_03", "RAD-THX",
     "Nyeri dada kiri menjalar disertai keringat dingin — menilai lapangan paru "
     "dan lebar mediastinum.",
     20, "scheduled", None, None, None),
]

# --- apotek ---------------------------------------------------------------
# (kunci, jangkar kunjungan, depo, jenis, cito, menit lalu, berhenti di, baris)
# Baris: (generik, dosis, satuan, frekuensi, rute, hari, jumlah, aturan pakai)
RX_WORKLIST = [
    ("wl_rx_febris", "tv_um_05", "DEPO-RJ", "outpatient", False, 12, "submitted", [
        ("Parasetamol", 500, "mg", "3x1", "oral", 3, 9, "3x1 tablet sesudah makan bila demam"),
    ]),
    ("wl_rx_isk_igd", "tv_igd_04", "DEPO-IGD", "emergency", True, 8, "submitted", [
        ("Ceftriakson", 1, "g", "1x1", "iv", 1, 1, "1x1 gram intravena"),
        ("Parasetamol", 500, "mg", "3x1", "oral", 1, 3, "3x1 tablet bila demam"),
    ]),
    # Obat high-alert yang menuntut verifikasi dua orang. Sengaja ditinggal di
    # antrian TANPA saksi: yang diperagakan justru pagarnya — penyerahan
    # ditolak model sampai saksi double-check diisi.
    ("wl_rx_koreksi_kalium", "adm_ang_07", "DEPO-RI", "inpatient", True, 18, "submitted", [
        ("Kalium Klorida", 25, "mEq", "1x1", "iv", 1, 1,
         "1 ampul dalam 500 mL NaCl 0,9% habis dalam 4 jam, via vena besar"),
    ]),
    ("wl_rx_insulin", "adm_mel_05", "DEPO-RI", "inpatient", False, 35, "verified", [
        ("Insulin Glargin", 14, "IU", "1x1", "sc", 7, 1, "1x14 unit subkutan malam hari"),
    ]),
    ("wl_rx_pneumonia", "adm_mel_01", "DEPO-RI", "inpatient", False, 50, "preparing", [
        ("Ceftriakson", 1, "g", "2x1", "iv", 1, 2, "2x1 gram intravena"),
        ("Ambroksol", 30, "mg", "3x1", "oral", 1, 3, "3x1 tablet sesudah makan"),
    ]),
    ("wl_rx_ppok", "adm_ang_01", "DEPO-RI", "inpatient", False, 28, "preparing", [
        ("Salbutamol", 2.5, "mg", "3x1", "inhalasi", 1, 3, "3x1 nebulisasi"),
    ]),
    ("wl_rx_pulang_chf", "adm_mel_02", "DEPO-RJ", "discharge", False, 65, "ready", [
        ("Furosemid", 40, "mg", "1x1", "oral", 7, 7, "1x1 tablet pagi hari"),
        ("Amlodipin", 10, "mg", "1x1", "oral", 7, 7, "1x1 tablet malam hari"),
    ]),
]


class HmsDemoContent(models.AbstractModel):
    _inherit = "hms.demo.content"

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    def _support_worklists(self):
        self.env["hms.demo.builder"]._assert_demo_database()
        self._repair_specimen_history()
        self._lab_worklist()
        self._rad_worklist()
        self._pharmacy_queue()
        return True

    # ------------------------------------------------------------------
    # Pintasan
    # ------------------------------------------------------------------
    def _minutes_ago(self, minutes):
        return fields.Datetime.now() - timedelta(minutes=minutes)

    def _analyst(self):
        return self._user("analis")

    def _encounter_for(self, anchor_key, worklist_key):
        """Kunjungan yang menjelaskan order ini, atau None.

        Papan hari ini boleh melewati satu slot (mis. bed sudah terisi admisi
        lain), dan order yang kehilangan jangkarnya tidak boleh dipaksa
        menempel pada pasien lain: itu justru bentuk ketidakkoherenan yang
        ingin dihindari seluruh berkas ini.
        """
        encounter = self._anchor(anchor_key)
        if not encounter or encounter._name != "hms.encounter":
            _logger.info(
                "SIMRS demo: jangkar %s tidak ada, order %s dilewati",
                anchor_key, worklist_key,
            )
            return None
        return encounter

    # ------------------------------------------------------------------
    # Spesimen: gerbang pra-analitik untuk baris lama
    # ------------------------------------------------------------------
    def _repair_specimen_history(self):
        """Pemeriksaan selesai atas spesimen yang tidak pernah diterima.

        Penyemai lama memanggil ``action_start()`` langsung dan melewati
        ``action_receive_specimen()``, jadi tiga belas baris lab berstatus
        ``done`` sementara ``specimen_state``-nya masih ``pending``. Itu bukan
        bug kode — jalurnya benar, penyemainya yang memotong — tetapi pembaca
        rumah sakit akan menangkapnya dalam sekali lihat.

        Dijalankan lewat AKSI RESMINYA, bukan tulisan langsung ke kolom.
        Aksinya aman untuk baris yang sudah ``done``: ia hanya memanggil
        ``action_start()`` bila barisnya masih ``ordered``. Hanya stempel
        waktunya yang dikoreksi sesudahnya — penerimaan spesimen yang tercatat
        "sekarang" untuk pemeriksaan yang selesai kemarin adalah urutan yang
        mustahil, dan mengganti satu ketidakkoherenan dengan yang lain.
        """
        stale = self.env["hms.order.line"].search([
            ("order_type", "=", "lab"),
            ("state", "in", ("in_progress", "done")),
            ("specimen_state", "=", "pending"),
        ])
        if not stale:
            return 0
        for line in stale:
            self._as(line, "analis").action_receive_specimen()
            line.write({
                "specimen_received_at": line.started_at or line.order_id.ordered_at,
            })
        _logger.info("SIMRS demo: %s baris lab lama ditandai spesimen diterima", len(stale))
        return len(stale)

    # ------------------------------------------------------------------
    # 1. Worklist laboratorium
    # ------------------------------------------------------------------
    def _lab_worklist(self):
        for (key, anchor, tariff_code, indication, priority, minutes,
             stop_at, values) in LAB_WORKLIST:
            if self._anchor(key):
                continue
            encounter = self._encounter_for(anchor, key)
            if not encounter:
                continue
            record = self._build_lab_work(
                encounter, tariff_code, indication, priority, minutes, stop_at, values
            )
            if record:
                self._keep(key, record)
        return True

    def _build_lab_work(self, encounter, tariff_code, indication, priority,
                        minutes, stop_at, values):
        tariff = self._tariff(tariff_code)
        if not tariff:
            _logger.warning("SIMRS demo: tarif lab %s tidak ada", tariff_code)
            return None
        doctor = encounter.practitioner_id
        ordered_at = self._minutes_ago(minutes)
        if stop_at == "verified":
            # Nilai kritis yang belum diakui: jam TBaK baru berjalan setelah
            # verifikasi, jadi baris ini memang harus tuntas sampai verified.
            # Diverifikasi 12 menit lalu terhadap ambang 30 menit, sehingga
            # layarnya menampilkan "menunggu pengakuan", bukan "terlambat".
            results = self._lab(
                encounter, doctor, tariff_code, ordered_at, values=values,
                clinical_note=indication, ack=None,
                verified_at=self._minutes_ago(12),
            )
            return results[:1].order_line_id if results else None

        order = self.env["hms.order"].create({
            "encounter_id": encounter.id, "order_type": "lab",
            "practitioner_id": doctor.id, "ordered_at": ordered_at,
            "target_unit_id": self._unit("LAB").id,
            "priority": priority,
            "clinical_note": indication,
            "line_ids": [(0, 0, {"tariff_id": tariff.id})],
        })
        order.action_submit()
        line = order.line_ids
        if stop_at == "ordered":
            # Spesimen belum diambil petugas. Tidak ada baris hasil sama
            # sekali — worklist hasil lab memang belum boleh menampilkannya;
            # yang menampilkannya adalah layar order lab, kolom "Belum Diterima".
            return line
        self._as(line, "analis").action_receive_specimen()
        line.write({"specimen_received_at": ordered_at + timedelta(minutes=6)})
        if stop_at == "pending":
            return line
        analyst = self._analyst()
        for result in line.lab_result_ids:
            code = result.parameter_id.code
            result.write({
                "value_numeric": values.get(code, self.LAB_DEFAULTS.get(code, 1.0)),
            })
            actor = result.with_user(analyst) if analyst else result
            actor.action_enter()
            if stop_at == "validated":
                actor.action_validate()
        return line

    # ------------------------------------------------------------------
    # 2. Worklist radiologi
    # ------------------------------------------------------------------
    def _rad_worklist(self):
        for (key, anchor, tariff_code, indication, minutes, stop_at,
             findings, impression, suggestion) in RAD_WORKLIST:
            if self._anchor(key):
                continue
            encounter = self._encounter_for(anchor, key)
            if not encounter:
                continue
            report = self._build_rad_work(
                encounter, tariff_code, indication, minutes, stop_at,
                findings, impression, suggestion,
            )
            if report:
                self._keep(key, report)
        return True

    def _build_rad_work(self, encounter, tariff_code, indication, minutes,
                        stop_at, findings, impression, suggestion):
        tariff = self._tariff(tariff_code)
        if not tariff:
            _logger.warning("SIMRS demo: tarif radiologi %s tidak ada", tariff_code)
            return None
        order = self.env["hms.order"].create({
            "encounter_id": encounter.id, "order_type": "radiology",
            "practitioner_id": encounter.practitioner_id.id,
            "ordered_at": self._minutes_ago(minutes),
            "target_unit_id": self._unit("RAD").id,
            "clinical_note": indication,
            "line_ids": [(0, 0, {"tariff_id": tariff.id})],
        })
        order.action_submit()
        report = order.line_ids.rad_report_ids
        if not report:
            return None
        # Modalitas dan regio TIDAK ditulis di sini: keduanya datang dari
        # katalog hms.rad.exam lewat tarifnya, sehingga permintaan "USG
        # Abdomen" tidak bisa berakhir sebagai baris ber-modalitas rontgen.
        if stop_at == "scheduled":
            return report
        actor = self._as(report, "radiolog")
        actor.action_perform()
        report.write({"performed_at": self._minutes_ago(max(minutes - 15, 3))})
        if stop_at == "performed":
            return report
        actor.write({
            "technique": "Proyeksi standar, kondisi cukup.",
            "findings": findings,
            "impression": impression,
            "suggestion": suggestion or False,
        })
        actor.action_report()
        return report

    # ------------------------------------------------------------------
    # 3. Antrian apotek
    # ------------------------------------------------------------------
    def _pharmacy_queue(self):
        for (key, anchor, depot_code, rx_type, cito, minutes,
             stop_at, lines) in RX_WORKLIST:
            if self._anchor(key):
                continue
            encounter = self._encounter_for(anchor, key)
            if not encounter:
                continue
            rx = self._build_prescription(
                encounter, depot_code, rx_type, cito, minutes, stop_at, lines
            )
            if rx:
                self._keep(key, rx)
        return True

    def _medicine(self, generic):
        """Item generik (tanpa merek) untuk satu zat aktif."""
        return self.env["hms.medicine"].search([
            ("generic_name", "=", generic), ("brand_name", "=", False),
        ], limit=1)

    def _build_prescription(self, encounter, depot_code, rx_type, cito, minutes,
                            stop_at, lines):
        depot = self.env["hms.depot"].search([("code", "=", depot_code)], limit=1)
        if not depot:
            _logger.warning("SIMRS demo: depo %s tidak ada", depot_code)
            return None
        Frequency = self.env["hms.frequency"]
        Route = self.env["hms.route"]
        line_vals = []
        for generic, dose, unit, freq_code, route_code, days, qty, sig in lines:
            medicine = self._medicine(generic)
            if not medicine:
                _logger.warning("SIMRS demo: obat %s tidak ada di katalog", generic)
                return None
            line_vals.append((0, 0, {
                "medicine_id": medicine.id,
                "dose": dose, "dose_unit": unit,
                "frequency_id": Frequency.search([("code", "=", freq_code)], limit=1).id,
                "route_id": Route.search([("code", "=", route_code)], limit=1).id,
                "duration_days": days, "qty_prescribed": qty, "sig": sig,
            }))
        rx = self.env["hms.prescription"].create({
            "encounter_id": encounter.id,
            "practitioner_id": encounter.practitioner_id.id,
            "depot_id": depot.id,
            "type": rx_type,
            "is_cito": cito,
            "prescribed_at": self._minutes_ago(minutes),
            "line_ids": line_vals,
        })
        if rx.allergy_warning:
            # Resep yang menabrak alergi pasien lalu tetap diloloskan apoteker
            # adalah demo yang memperagakan kebalikan dari fiturnya. Dicatat
            # keras supaya terlihat di log upgrade, bukan ditelan diam-diam.
            _logger.warning(
                "SIMRS demo: resep %s untuk %s memicu peringatan alergi — %s",
                rx.name, rx.patient_id.name, rx.allergy_warning.replace("\n", " | "),
            )
        rx.action_submit()
        # Urutan yang sah, bukan tulisan langsung ke kolom state: telaah
        # apoteker mendahului penyiapan, dan penyiapan mendahului "siap
        # diserahkan". Penyerahan sengaja TIDAK dijalankan — inilah pekerjaan
        # yang harus tersisa di layar.
        if stop_at == "submitted":
            return rx
        actor = self._as(rx, "apoteker")
        actor.action_verify()
        if stop_at == "verified":
            return rx
        actor.action_prepare()
        if stop_at == "preparing":
            return rx
        actor.action_ready()
        return rx


class HmsDemoBuilder(models.AbstractModel):
    _inherit = "hms.demo.builder"

    @api.model
    def seed_support_worklists(self):
        """Pintu masuk terpisah, supaya lapisan ini bisa disemai sendiri."""
        self._assert_demo_database()
        return self.env["hms.demo.content"]._support_worklists()
