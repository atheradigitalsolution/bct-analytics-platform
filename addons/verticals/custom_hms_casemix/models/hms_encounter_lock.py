# -*- coding: utf-8 -*-
"""Penguncian kunjungan saat klaimnya difinalisasi — dan pintu keluarnya.

=============================================================================
KEPUTUSAN: YANG DIKUNCI ADALAH EMPAT DOKUMEN YANG MENJADI ISI KLAIM
=============================================================================

Begitu ``hms.claim`` mencapai ``finalized``, rumah sakit sudah menyatakan
"inilah berkas yang kami ajukan". Kalau dokumentasi klinis di belakangnya
masih bisa berubah diam-diam sesudah itu, dua hal rusak sekaligus: berkas
yang diaudit penjamin tidak lagi sama dengan berkas yang ada di rumah sakit,
dan tidak ada satu pun baris yang menjelaskan sejak kapan.

Sebuah boolean ``is_locked`` yang hanya menyalakan ikon gembok tidak
menyelesaikan apa pun. Karena itu penguncian di berkas ini benar-benar
**menolak tulis**, dan menolaknya di lapisan model — bukan di layar, bukan di
controller — supaya jalur API, impor, dan skrip ikut tertahan.

**Cakupan yang dipilih, dan mengapa persis ini:**

``hms.clinical.note``, ``hms.diagnosis``, ``hms.procedure`` dan
``hms.summary``. Keempatnya adalah dokumen yang isinya **menentukan apa yang
ditagihkan**: kode klaim disalin darinya (``hms.claim.code.source_diagnosis_id``
/ ``source_procedure_id``), dan resume medis adalah dokumen yang dibaca
verifikator penjamin. Mengubah salah satunya setelah klaim keluar berarti
mengubah dasar tagihan tanpa jejak — itulah bentuk upcoding yang paling sulit
dibuktikan.

Yang sengaja **TIDAK** dikunci, supaya cakupannya tidak melebar menjadi
gangguan:

* ``hms.klpcm`` — analisis kelengkapan justru harus tetap bisa menutup
  temuannya sesudah klaim jalan; ia mengaudit berkas, bukan mengubah isinya.
* seluruh model casemix (``hms.claim``, ``hms.claim.code``,
  ``hms.coding.query``, ``hms.claim.batch``, ``hms.claim.adjustment``) —
  pekerjaan yang mengunci tidak boleh ikut terkunci.
* hasil penunjang, observasi, tugas keperawatan, dan catatan gizi — hasil lab
  yang terbit terlambat adalah kenyataan sehari-hari, dan menahan penulisannya
  tidak melindungi tagihan apa pun: ia tidak pernah menjadi baris klaim dengan
  sendirinya. Kalau hasil itu memang mengubah diagnosis, yang berubah adalah
  ``hms.diagnosis`` — dan pintunya ada di bawah ini.
* baris identitas eksternal (``ihs_*``) — SATUSEHAT menuliskan balik id
  resource setelah pengiriman berhasil; itu pembukuan integrasi, bukan
  perubahan isi rekam medis.

=============================================================================
KEPUTUSAN: KUNCI INI PUNYA PINTU, DAN PINTUNYA `hms.correction.request`
=============================================================================

Koreksi setelah klaim final adalah kenyataan, bukan penyimpangan: salah sisi
tubuh, salah dosis yang tercatat, diagnosis yang keliru ketik. Kunci tanpa
jalan keluar akan dimatikan orang pada demo pertama, dan sesudah itu tidak ada
kunci sama sekali.

Pintunya **tidak dibuat baru**. ``custom_hms_medrec`` sudah punya
``hms.correction.request`` — model yang justru dibangun untuk PMK 24/2022
Ps. 30 ayat (7): koreksi di luar masa tenggang butuh persetujuan PMIK atau
pimpinan, mencatat siapa mengizinkan apa, dan menuntut referensi adendum.
Persyaratannya sama persis dengan yang dibutuhkan di sini, jadi menambah alur
otorisasi kedua hanya akan membuat dua antrian persetujuan yang berbeda untuk
pekerjaan yang sama.

Aturannya: sebuah permintaan koreksi ber-state ``approved`` yang menunjuk
kunjungan ini dan model sasaran ini membuka penguncian **untuk record yang
ditunjuknya saja**, dan untuk penambahan adendum pada model yang sama.
Sesudah adendumnya jadi, ``action_mark_applied`` menutup pintunya kembali
(state berubah menjadi ``applied``, tidak lagi ``approved``).

=============================================================================
KEPUTUSAN: KEBERADAAN IZIN DIBACA DENGAN `sudo()`, PENULISANNYA TIDAK
=============================================================================

Pencarian permintaan koreksi memakai ``sudo()``. Itu **bukan** elevasi untuk
menulis: yang dielevasi hanya pertanyaan "apakah izinnya ada", dan jawabannya
hanya bisa membuka atau tidak membuka penolakan. Penulisan yang menyusul tetap
berjalan dengan hak akses pengguna itu sendiri — perawat yang tidak berhak
menulis ``hms.diagnosis`` tetap ditolak ``AccessError``, izin atau tidak.

Alasannya sudah dibuktikan mahal di modul ini pada gerbang KLPCM (lihat
``tests/test_casemix_access.py``): gerbang yang membaca dengan hak akses
pemanggil akan **diam-diam salah**. ``ir.rule`` pada
``hms.correction.request`` membatasi staf biasa pada permintaan yang ia ajukan
sendiri, jadi seorang perawat yang menerapkan koreksi yang diminta dokter akan
melihat pintunya tertutup tanpa sebab yang bisa dibaca. Sebuah gerbang harus
melihat kebenaran seluruhnya, bukan irisan pemanggilnya.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Kolom yang tetap boleh ditulis pada dokumen kunjungan terkunci. Semuanya
# pembukuan teknis; tidak satu pun mengubah isi klinis yang ditagihkan.
LOCK_EXEMPT_FIELDS = frozenset({
    "message_follower_ids", "message_ids", "message_main_attachment_id",
    "activity_ids", "write_date", "write_uid",
    # Backfill id resource dari SATUSEHAT setelah pengiriman berhasil.
    "ihs_condition_id", "ihs_observation_id", "ihs_procedure_id",
})


class HmsEncounter(models.Model):
    """Aditif ke ``hms.encounter``; ``custom_hms_registration`` tidak disentuh.

    ``is_locked`` sendiri **sudah ada** di modul pendaftaran (beserta penjaga
    ``write`` pada kunjungan itu sendiri), tetapi tidak ada satu pun alur yang
    pernah menyalakannya dan tidak ada satu pun dokumen klinis yang ikut
    tertahan olehnya. Yang ditambahkan di sini adalah keterangan siapa dan
    kapan, penyalaannya dari finalisasi klaim, dan penolakan yang sebenarnya.
    """
    _inherit = "hms.encounter"

    locked_at = fields.Datetime("Waktu Penguncian", readonly=True, copy=False)
    locked_by_id = fields.Many2one("res.users", "Dikunci Oleh", readonly=True, copy=False)
    lock_reason = fields.Char(
        "Alasan Penguncian", readonly=True, copy=False,
        help="Diisi otomatis saat klaim kunjungan ini difinalisasi. Kunci "
             "tanpa alasan yang tercatat tidak bisa dipertanggungjawabkan "
             "kepada dokter yang catatannya tertahan.",
    )
    locking_claim_id = fields.Many2one(
        "hms.claim", "Klaim yang Mengunci", readonly=True, copy=False,
        ondelete="set null",
    )

    def _casemix_lock(self, claim):
        """Kunci kunjungan atas nama sebuah klaim yang baru difinalisasi.

        ``sudo()`` di sini adalah pembukuan, bukan keputusan (DECISIONS #6):
        yang memutuskan adalah koder/verifikator yang memang berhak
        memfinalkan klaim, sementara ``hms.encounter`` hanya bisa ditulis
        pendaftaran dan admin. Memberi koder hak tulis penuh atas kunjungan —
        penjamin, DPJP, kelas rawat — demi menyalakan satu boolean adalah
        hibah yang jauh lebih besar daripada pekerjaannya.
        """
        self.ensure_one()
        if self.is_locked:
            return False
        self.sudo().write({
            "is_locked": True,
            "locked_at": fields.Datetime.now(),
            "locked_by_id": self.env.uid,
            "locking_claim_id": claim.id,
            "lock_reason": _("Klaim %s difinalisasi.") % claim.name,
        })
        _logger.info("SIMRS: kunjungan %s dikunci oleh klaim %s", self.name, claim.name)
        return True

    def _correction_approved_for(self, model_name, res_id=None):
        """True bila ada izin koreksi yang masih berlaku untuk sasaran ini.

        ``res_id`` kosong berarti pertanyaannya tentang **penambahan** entri
        baru (adendum): izin atas salah satu record model tersebut sudah cukup,
        karena adendumnya memang belum punya id ketika izin diminta.
        """
        self.ensure_one()
        domain = [
            ("encounter_id", "=", self.id),
            ("target_model", "=", model_name),
            ("state", "=", "approved"),
        ]
        if res_id:
            domain.append(("target_res_id", "=", res_id))
        return bool(self.env["hms.correction.request"].sudo().search_count(domain))


def _refuse(encounter, model_description, what):
    raise UserError(_(
        "Kunjungan %(enc)s terkunci sejak klaimnya difinalisasi (%(why)s), "
        "sehingga %(doc)s tidak dapat %(what)s. Koreksi setelah klaim "
        "diajukan tetap mungkin, tetapi harus lewat permintaan koreksi rekam "
        "medis yang disetujui PMIK/pimpinan (PMK 24/2022 Ps. 30) — buat "
        "permintaan koreksi untuk kunjungan ini, dan setelah disetujui "
        "perbaikannya ditulis sebagai adendum."
    ) % {
        "enc": encounter.name,
        "why": encounter.lock_reason or _("klaim final"),
        "doc": model_description,
        "what": what,
    })


def _check_locked_write(records, vals, label):
    touched = set(vals) - LOCK_EXEMPT_FIELDS
    if not touched:
        return
    for record in records:
        encounter = record.encounter_id
        if not encounter or not encounter.is_locked:
            continue
        if encounter._correction_approved_for(record._name, record.id):
            continue
        _refuse(encounter, label, _("diubah"))


def _check_locked_unlink(records, label):
    for record in records:
        encounter = record.encounter_id
        if not encounter or not encounter.is_locked:
            continue
        if encounter._correction_approved_for(record._name, record.id):
            continue
        _refuse(encounter, label, _("dihapus"))


def _check_locked_create(model, vals_list, label):
    """Izin untuk menambah entri dinilai per kunjungan, bukan per baris.

    Adendum belum punya id ketika izinnya diminta, jadi yang ditanyakan di
    sini adalah "apakah kunjungan ini sedang dibuka untuk koreksi pada model
    ini" — bukan "apakah record ini disebut namanya".
    """
    Encounter = model.env["hms.encounter"]
    verdict = {}
    for vals in vals_list:
        encounter_id = vals.get("encounter_id")
        if not encounter_id:
            continue
        if encounter_id not in verdict:
            encounter = Encounter.browse(encounter_id)
            verdict[encounter_id] = (
                not encounter.is_locked
                or encounter._correction_approved_for(model._name)
            )
        if not verdict[encounter_id]:
            _refuse(Encounter.browse(encounter_id), label, _("ditambahkan"))


# Kelas-kelas di bawah ini sengaja mengulang tiga baris yang sama alih-alih
# mewarisi sebuah mixin bersama. Odoo 19 menyusun ulang ``__bases__`` setiap
# model saat registry dibangun, dan sebuah kelas Python biasa di dalam daftar
# basis membuat langkah itu gagal dengan ``TypeError: __bases__ assignment:
# object layout differs`` — kegagalan yang muncul saat memuat modul, bukan
# saat menulis kodenya. Pengulangan tiga barisnya lebih murah daripada
# abstraksi yang tidak boleh ada di sini.
class HmsClinicalNote(models.Model):
    _inherit = "hms.clinical.note"

    @api.model_create_multi
    def create(self, vals_list):
        _check_locked_create(self, vals_list, _("catatan klinis"))
        return super().create(vals_list)

    def write(self, vals):
        _check_locked_write(self, vals, _("catatan klinis"))
        return super().write(vals)

    def unlink(self):
        _check_locked_unlink(self, _("catatan klinis"))
        return super().unlink()


class HmsDiagnosis(models.Model):
    _inherit = "hms.diagnosis"

    @api.model_create_multi
    def create(self, vals_list):
        _check_locked_create(self, vals_list, _("diagnosis"))
        return super().create(vals_list)

    def write(self, vals):
        _check_locked_write(self, vals, _("diagnosis"))
        return super().write(vals)

    def unlink(self):
        _check_locked_unlink(self, _("diagnosis"))
        return super().unlink()


class HmsProcedure(models.Model):
    _inherit = "hms.procedure"

    @api.model_create_multi
    def create(self, vals_list):
        _check_locked_create(self, vals_list, _("tindakan"))
        return super().create(vals_list)

    def write(self, vals):
        _check_locked_write(self, vals, _("tindakan"))
        return super().write(vals)

    def unlink(self):
        _check_locked_unlink(self, _("tindakan"))
        return super().unlink()


class HmsSummary(models.Model):
    _inherit = "hms.summary"

    @api.model_create_multi
    def create(self, vals_list):
        _check_locked_create(self, vals_list, _("resume medis"))
        return super().create(vals_list)

    def write(self, vals):
        _check_locked_write(self, vals, _("resume medis"))
        return super().write(vals)

    def unlink(self):
        _check_locked_unlink(self, _("resume medis"))
        return super().unlink()
