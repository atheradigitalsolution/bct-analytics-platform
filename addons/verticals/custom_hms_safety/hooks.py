# -*- coding: utf-8 -*-
"""Penyemaian contoh untuk layar demo — dan hanya untuk demo.

Modul ini sengaja TIDAK memakai kunci ``demo`` pada manifest: seluruh basis
data SIMRS di lingkungan ini dipasang dengan ``--without-demo=all``, sehingga
berkas demo XML tidak akan pernah dimuat dan layar keselamatan pasien akan
kosong justru saat dipakai presentasi.

Berbeda dari ``custom_hms_demo`` yang **gagal keras** di luar database
``*_demo`` (pasien demo membakar nomor rekam medis yang tidak bisa diterbitkan
ulang), penyemaian di sini **dilewati dengan tenang**. Laporan insiden contoh
tidak membakar sumber daya apa pun; yang salah bukan memasang modulnya di
produksi — itu justru tujuannya — melainkan menaruh data contoh di sana.
"""
import logging
from datetime import timedelta

from odoo import fields

_logger = logging.getLogger(__name__)

# Keanggotaan tim KP di database demo.
#
# `group_hms_patient_safety` sengaja tidak disiratkan oleh grup mana pun,
# termasuk administrator SIMRS: matriks hak akses menulis "Lihat insiden |
# grup tim KP saja". Tanpa satu pun anggota, layar demo IKP tidak bisa
# diperagakan sama sekali. Jadi keanggotaannya ditetapkan di sini secara
# eksplisit untuk database demo — sebuah keputusan manusia yang ditulis, bukan
# pewarisan hak yang diam-diam berlaku di setiap pemasangan.
DEMO_SAFETY_TEAM_LOGINS = ["manajer@simrs-demo.invalid"]


def post_init_hook(env):
    if not env.cr.dbname.endswith("_demo"):
        _logger.info(
            "SIMRS: %s bukan database demo, contoh insiden/komplain dilewati.",
            env.cr.dbname,
        )
        return
    _grant_demo_safety_team(env)
    _seed_incidents(env)
    _seed_complaints(env)


def _grant_demo_safety_team(env):
    group = env.ref("custom_hms_safety.group_hms_patient_safety", raise_if_not_found=False)
    if not group:
        return
    logins = list(DEMO_SAFETY_TEAM_LOGINS)
    users = env["res.users"].sudo().search([("login", "in", logins)])
    admin = env.ref("base.user_admin", raise_if_not_found=False)
    if admin:
        users |= admin
    for user in users:
        if group not in user.all_group_ids:
            user.write({"group_ids": [(4, group.id)]})
            _logger.info("SIMRS demo: %s masuk tim keselamatan pasien", user.login)


def _units(env):
    """Unit apa pun yang ada; tanpa unit tidak ada insiden yang bisa dibuat."""
    return env["hms.unit"].search([], limit=4)


def _seed_incidents(env):
    Incident = env["hms.incident.report"]
    if Incident.search_count([]):
        return
    units = _units(env)
    if not units:
        _logger.info("SIMRS demo: belum ada hms.unit, contoh insiden dilewati.")
        return
    patient = env["hms.patient"].search([], limit=1)
    now = fields.Datetime.now()
    samples = [
        {
            "occurred_at": now - timedelta(hours=6),
            "unit_id": units[0].id,
            "location_detail": "Koridor depan nurse station",
            "incident_type": "ktc",
            "category": "fall",
            "patient_id": patient.id if patient else False,
            "chronology": "Pasien turun dari tempat tidur tanpa pendampingan saat "
                          "hendak ke kamar mandi dan terpeleset di lantai yang basah. "
                          "Pasien ditemukan duduk di lantai, sadar penuh.",
            "immediate_action": "Pasien dibantu kembali ke tempat tidur, dilakukan "
                                "pemeriksaan tanda vital dan penilaian cedera: tidak "
                                "ditemukan cedera. Lantai segera dikeringkan.",
            "patient_harmed": False,
            "is_anonymous": False,
        },
        {
            "occurred_at": now - timedelta(days=1, hours=3),
            "unit_id": units[min(1, len(units) - 1)].id,
            "location_detail": "Ruang penyiapan obat",
            "incident_type": "knc",
            "category": "medication",
            "chronology": "Dua obat dengan kemasan mirip (LASA) hampir tertukar saat "
                          "penyiapan. Kesalahan tertangkap pada pengecekan petugas "
                          "kedua sebelum obat keluar dari depo.",
            "immediate_action": "Obat dikembalikan ke rak yang benar; label LASA "
                                "ditambahkan pada kedua kemasan.",
            # Dilaporkan anonim: pelapor menyoroti pekerjaan rekan satu shift,
            # kasus yang persis dituju PMK 11/2017 saat menyebut budaya tanpa
            # menyalahkan.
            "is_anonymous": True,
        },
        {
            "occurred_at": now - timedelta(days=4),
            "unit_id": units[min(2, len(units) - 1)].id,
            "location_detail": "Gudang farmasi",
            "incident_type": "kpc",
            "category": "equipment",
            "chronology": "Kulkas penyimpanan vaksin menunjukkan suhu di luar rentang "
                          "2-8 derajat selama pemantauan pagi. Belum ada vaksin yang "
                          "terpakai dari kulkas tersebut.",
            "immediate_action": "Vaksin dipindahkan ke kulkas cadangan, teknisi "
                                "dipanggil, pemantauan suhu diperketat per dua jam.",
            "is_anonymous": False,
        },
    ]
    incidents = Incident.create(samples)
    incidents.action_report()

    # Satu berkas yang sudah selesai dibahas supaya layar investigasi tidak
    # kosong saat diperagakan.
    closed = incidents[1]
    closed.action_start_investigation()
    closed.write({
        "grade": "green",
        "root_cause": "Rak penyimpanan tidak memisahkan obat LASA, dan penerangan "
                      "di ruang penyiapan kurang pada shift malam.",
        "recommendation": "Terapkan pemisahan fisik dan penandaan LASA di seluruh "
                          "depo; ajukan penambahan lampu ruang penyiapan.",
    })
    closed.action_grade()
    closed.write({"closure_note": "Rekomendasi diserahkan ke Komite Farmasi dan Terapi."})
    closed.action_close()
    _logger.info("SIMRS demo: %s contoh insiden dibuat", len(incidents))


def _seed_complaints(env):
    Complaint = env["hms.complaint"]
    if Complaint.search_count([]):
        return
    units = _units(env)
    patient = env["hms.patient"].search([], limit=1)
    now = fields.Datetime.now()
    samples = [
        {
            "received_at": now - timedelta(hours=20),
            "complainant_name": "Keluarga pasien (Ny. S)",
            "complainant_relation": "family",
            "contact": "0812-0000-0001",
            "patient_id": patient.id if patient else False,
            "channel": "verbal",
            "category": "waiting_time",
            "unit_id": units[0].id if units else False,
            "grade": "yellow",
            "subject": "Menunggu lebih dari dua jam di poliklinik tanpa informasi",
            "detail": "Keluarga menyampaikan tidak ada pemberitahuan ketika jadwal "
                      "dokter mundur, sehingga pasien lansia menunggu berdiri.",
        },
        {
            "received_at": now - timedelta(days=2),
            "complainant_name": "Bpk. R",
            "complainant_relation": "patient",
            "contact": "0812-0000-0002",
            "channel": "suggestion_box",
            "category": "facility",
            "unit_id": units[min(1, len(units) - 1)].id if units else False,
            "grade": "green",
            "subject": "Kamar mandi ruang tunggu tidak bersih",
            "detail": "Kamar mandi ruang tunggu lantai dua tidak dibersihkan sejak pagi.",
        },
    ]
    complaints = Complaint.create(samples)
    complaints.action_receive()
    handled = complaints[1]
    handled.action_start()
    handled.write({
        "response": "Kami menyampaikan permohonan maaf. Jadwal pembersihan kamar "
                    "mandi ruang tunggu ditambah menjadi tiga kali sehari.",
        "corrective_action": "Jadwal housekeeping direvisi dan ceklis kebersihan "
                             "dipasang di pintu.",
        "outcome": "resolved",
    })
    handled.action_respond()
    handled.action_close()
    _logger.info("SIMRS demo: %s contoh komplain dibuat", len(complaints))
