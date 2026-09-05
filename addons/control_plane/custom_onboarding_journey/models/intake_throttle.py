# -*- coding: utf-8 -*-
"""Batas laju kiriman publik — dibagi antar worker, bertahan melewati restart.

KENAPA POSTGRES DAN BUKAN DICT PROSES. Versi sebelumnya menyimpan penghitungnya di
sebuah `dict` modul. Odoo di sini berjalan dengan `ODOO_WORKERS=2`, jadi setiap
worker memegang penghitungnya sendiri dan batas "5 per jam per IP" sesungguhnya
adalah 10 — dan nol lagi setiap kali container di-restart. Sebuah batas yang
besarnya bergantung pada jumlah worker dan hilang saat deploy bukanlah batas.

KENAPA BUKAN REDIS. Redis berjalan di stack ini dan terjangkau dari container Odoo,
tetapi image Odoo tidak memuat pustaka `redis` (`ModuleNotFoundError`). Menambah
dependensi dan me-rebuild image demi satu penghitung adalah harga yang tidak sepadan
ketika Odoo sudah memegang koneksi basis data yang transaksional.

KENAPA ADVISORY LOCK. Tanpa serialisasi, dua worker bisa sama-sama membaca "sudah 4"
di detik yang sama dan sama-sama meloloskan kiriman ke-5 dan ke-6. Kuncinya diambil
per-IP, bukan global, sehingga pengunjung yang berbeda tidak saling menunggu; ia
dilepas otomatis saat transaksi berakhir.

TABEL INI DITULIS OLEH ORANG ANONIM, jadi ia dipangkas di dalam pemeriksaan yang
sama. Tidak ada tabel yang boleh tumbuh tanpa batas atas perintah pengunjung.
"""

from __future__ import annotations

import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

#: Lebar jendela dalam detik. Sengaja konstanta: parameter yang bisa diubah operator
#: adalah BANYAKNYA kiriman, bukan definisi "per jam" yang dijanjikan ke pengunjung.
WINDOW_SECONDS = 3600


class OnboardingIntakeThrottle(models.AbstractModel):
    """Penghitung kiriman per hash-IP. Bukan `models.Model`: tidak ada UI, tidak ada
    ACL, tidak ada yang perlu membacanya lewat ORM. Tabelnya dikelola langsung."""

    _name = "onboarding.intake.throttle"
    _description = "Penghitung batas laju intake publik (internal)"

    _TABLE = "onboarding_intake_throttle"

    @api.model
    def _ensure_table(self):
        self.env.cr.execute(
            """
            CREATE TABLE IF NOT EXISTS %s (
                id         serial PRIMARY KEY,
                ip_hash    varchar NOT NULL,
                hit_at     timestamp NOT NULL DEFAULT (now() AT TIME ZONE 'UTC')
            )
            """
            % self._TABLE
        )
        self.env.cr.execute(
            "CREATE INDEX IF NOT EXISTS %s_ip_hash_hit_at_idx ON %s (ip_hash, hit_at)"
            % (self._TABLE, self._TABLE)
        )

    @api.model
    def check_and_count(self, ip_hash: str, per_hour: int) -> bool:
        """True kalau kiriman ini HARUS DITOLAK.

        Menghitung lebih dulu, mencatat belakangan: pemanggil yang ditolak tidak
        menambah jejak, sehingga penyerang tidak bisa memperpanjang hukumannya
        sendiri tanpa batas dengan terus mencoba.
        """
        if per_hour <= 0:
            return False
        if not ip_hash:
            # Tanpa alamat tidak ada yang bisa dibatasi. Ini hanya terjadi kalau
            # header proxy hilang; dicatat karena ia berarti batas per-IP sedang
            # tidak menjaga apa pun.
            _logger.warning("intake: kiriman tanpa alamat asal; batas per-IP dilewati")
            return False

        cr = self.env.cr
        self._ensure_table()

        # Serialisasi per-IP. `hashtext` mengembalikan int4; advisory lock transaksi
        # dilepas sendiri saat commit maupun rollback.
        cr.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (ip_hash,))

        # Pangkas dulu, supaya hitungan di bawah tidak perlu memfilter dua kali dan
        # tabelnya tidak pernah menyimpan lebih dari satu jendela.
        cr.execute(
            "DELETE FROM %s WHERE hit_at < (now() AT TIME ZONE 'UTC') - interval '%s seconds'"
            % (self._TABLE, WINDOW_SECONDS)
        )

        cr.execute(
            "SELECT count(*) FROM %s WHERE ip_hash = %%s" % self._TABLE,
            (ip_hash,),
        )
        used = cr.fetchone()[0]
        if used >= per_hour:
            return True

        cr.execute(
            "INSERT INTO %s (ip_hash) VALUES (%%s)" % self._TABLE,
            (ip_hash,),
        )
        return False
