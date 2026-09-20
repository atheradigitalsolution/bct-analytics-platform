# -*- coding: utf-8 -*-
"""Pagar tulis kolom-terbatas untuk closed-loop nilai kritis.

Odoo tidak punya ACL per-kolom di ``ir.model.access``: ``perm_write`` adalah
satu sakelar untuk seluruh model. Sementara itu, klinisi **harus** bisa
menutup lingkaran nilai kritis (``action_acknowledge``) — fitur yang tidak
bisa dipakai peran yang dituju itu rusak, bukan aman — tapi tidak boleh ikut
mengubah angka hasil, status pelepasan, atau apa pun yang menjadi wewenang
petugas penunjang.

Susunan penjaganya tiga lapis, dan ketiganya harus ada:

1. ``perm_write=1`` untuk ``group_hms_emr_clinician`` di ``ir.model.access``
   — membuka pintunya sama sekali;
2. ``write()`` di mixin ini — mempersempit pintu itu ke daftar putih kolom;
3. ``ir.rule`` (bercakupan ``perm_write`` saja) di masing-masing modul —
   mempersempitnya lagi ke pasien yang benar-benar ditangani pengguna.

Tidak ada ``sudo()`` di jalur ini. Yang mengakui nilai kritis harus benar-benar
berhak menyentuh barisnya; meng-elevate hak justru menghapus makna buktinya.
"""
from odoo import _, models
from odoo.exceptions import AccessError

# SATU sumber kebenaran untuk kedua model (hms.lab.result dan hms.rad.report).
# Sengaja konstanta level-modul dan bukan disalin ke masing-masing model:
# dua salinan akan menyimpang diam-diam, dan yang menyimpang di sini adalah
# batas wewenang.
CRITICAL_ACK_WRITABLE_FIELDS = frozenset({
    "notified_at",
    "notified_by_id",
    "notified_to_id",
    "notify_channel",
    "acknowledged_at",
    "acknowledged_by_id",
    "ack_readback",
    "ack_minutes",
    "ack_state",
})


class HmsCriticalAck(models.AbstractModel):
    _name = "hms.critical.ack"
    _description = "Pagar Tulis Kolom Pengakuan Nilai Kritis"

    def _critical_ack_write_is_limited(self):
        """True bila pengguna saat ini hanya boleh menyentuh kolom ``ack_*``.

        Yang dibatasi adalah klinisi *murni* — dokter dan perawat yang menulis
        rekam medis. Petugas penunjang (lab/radiologi), dokter penanggung
        jawab penunjang, dan administrator SIMRS menjalankan alur hasilnya
        sendiri dan tetap menulis kolom apa pun seperti sebelumnya.

        ``env.su`` dilewati lebih dulu: cron ``_cron_refresh_ack_state``
        berjalan sebagai ``__system__`` dan pemulihan computed-stored tidak
        boleh gagal karena pagar yang ditujukan untuk manusia.
        """
        if self.env.su:
            return False
        user = self.env.user
        if not user.has_group("custom_hms_base.group_hms_emr_clinician"):
            return False
        # group_hms_admin sudah menyiratkan group_hms_diagnostic_user lewat
        # group_hms_diagnostic_verifier; disebut eksplisit supaya aturannya
        # tetap terbaca kalau rantai implikasi itu berubah.
        if user.has_group("custom_hms_base.group_hms_diagnostic_user"):
            return False
        if user.has_group("custom_hms_base.group_hms_admin"):
            return False
        return True

    def write(self, vals):
        if vals and self._critical_ack_write_is_limited():
            forbidden = sorted(set(vals) - CRITICAL_ACK_WRITABLE_FIELDS)
            if forbidden:
                raise AccessError(_(
                    "Sebagai klinisi Anda hanya boleh mengisi kolom pengakuan "
                    "nilai kritis pada %(model)s. Kolom berikut di luar "
                    "wewenang Anda: %(fields)s.",
                    model=self._description,
                    fields=", ".join(forbidden),
                ))
        return super().write(vals)
