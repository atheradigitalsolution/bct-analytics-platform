# -*- coding: utf-8 -*-
"""Satu hari kerja loket kasir: shift yang sudah ditutup dan shift yang berjalan.

KENAPA BERKAS INI ADA
---------------------
Layar kasir tidak membaca tabel ``hms_cashier_session``. Ia membaca
``cashier_session_id`` pada muatan ``/auth/me`` — yaitu shift yang berstatus
``open``/``closing`` **milik akun yang sedang login**. Selama akun ``kasir``
tidak memegang satu pun shift aktif, layarnya menampilkan "Belum ada shift
terbuka" beserta formulir pembukaan, tidak peduli berapa banyak shift yang
tersimpan atas nama orang lain. Keterangan slide "Kas ditutup dengan angka,
bukan dugaan" karena itu ditemani gambar yang membantahnya sendiri.

Yang disemai di sini karenanya bukan "beberapa shift", melainkan satu hari
kerja yang utuh dan bisa dijumlahkan ulang pembacanya:

* dua shift pagi yang **sudah ditutup** — satu pas, satu kurang Rp25.000
  dengan keterangan — supaya layar penutupan dan kolom Selisih benar-benar
  pernah memperlihatkan pekerjaannya. Shift yang semuanya nol membuat kolom
  Selisih tidak pernah terlihat berguna;
* satu shift siang yang **masih berjalan**, berisi beberapa metode
  pembayaran sekaligus, supaya rekap per metode punya baris.

Penutupannya melewati urutan yang sah — ``action_start_closing()`` lalu
``action_close()`` — dengan ``counted_amount`` diisi seperti kasir mengisi
berita acara hitung fisik. Tidak ada kolom ``state``, ``difference``, atau
``expected_cash`` yang ditulis langsung: ketiganya turunan, dan menulisnya
menghasilkan angka yang tidak bisa dijumlahkan ulang siapa pun.

Yang DITULIS langsung hanyalah jam: ``closed_at`` dibekukan model ke "sekarang"
pada detik penutupan, persis seperti ``hms.klpcm.due_at`` di
``_realign_klpcm()``, sehingga shift pagi akan tercatat ditutup tengah malam.
Nilainya dikembalikan ke jam yang memang dinyatakan spesifikasi shift, bukan
dilonggarkan aturannya.
"""
import logging
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# (kunci jangkar, kode loket, modal awal, menit buka UTC, menit tutup UTC atau
#  None bila masih berjalan, metode pembayaran berurutan, selisih kas fisik)
#
# Menitnya UTC sejak tengah malam, mengikuti papan kunjungan hari ini: 0 =
# 07:00 WIB, 300 = 12:00 WIB. Shift siang sengaja memakai loket yang sama
# dengan shift pagi yang sudah ditutup — indeks unik `_one_open_per_user`
# hanya berlaku pada shift yang BELUM tertutup, jadi itulah pergantian shift
# yang sebenarnya terjadi di loket sungguhan.
CASHIER_SHIFTS = [
    ("cashier_shift_pagi_1", "KAS-1", 500000.0, 0, 300,
     ("cash", "transfer", "cash", "qris"), 0.0),
    ("cashier_shift_pagi_2", "KAS-2", 300000.0, 30, 330,
     ("cash", "cash", "edc_debit"), -25000.0),
    ("cashier_shift_siang", "KAS-1", 1000000.0, 300, None,
     ("cash", "qris", "edc_credit", "transfer"), 0.0),
]

SHORTAGE_NOTE = ("Kurang Rp25.000: satu kembalian terlanjur dibayar lebih dan "
                 "sudah dicatat di buku loket, menunggu penggantian kasir.")


class HmsDemoContent(models.AbstractModel):
    _inherit = "hms.demo.content"

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    def _cashier_day(self):
        self.env["hms.demo.builder"]._assert_demo_database()
        cashier = self._user("kasir")
        if not cashier:
            _logger.warning(
                "SIMRS demo: akun kasir tidak ada, shift kasir dilewati"
            )
            return False
        plan = self._cashier_shift_plan()
        if not plan:
            return False
        for spec, bills in plan:
            self._cashier_shift(cashier, spec, bills)
        return True

    # ------------------------------------------------------------------
    # Pembagian tagihan
    # ------------------------------------------------------------------
    def _settleable_bills(self):
        """Tagihan yang memang bisa dibayar di loket, urut waktu selesainya.

        Disaring dari DATA, bukan dari daftar id: tagihan penjamin dengan
        sisa nol tidak pernah singgah di kasir, dan tagihan tanpa kunjungan
        yang sudah ditutup akan menghasilkan kwitansi yang jamnya mendahului
        pelayanannya sendiri.
        """
        bills = self.env["hms.bill"].search([
            ("state", "=", "open"), ("amount_due", ">", 0.0),
        ])
        bills = bills.filtered(lambda b: b.encounter_id.closed_at)
        return bills.sorted(lambda b: (b.encounter_id.closed_at, b.id))

    def _cashier_shift_plan(self):
        """Pasangkan setiap shift dengan tagihan yang jamnya masuk akal.

        Satu tagihan sengaja disisakan belum terbayar: layar kasir yang
        daftar tagihan berjalannya kosong memperagakan loket yang tidak punya
        pekerjaan, bukan loket yang rapi.
        """
        todo = [spec for spec in CASHIER_SHIFTS if not self._anchor(spec[0])]
        if not todo:
            return []
        candidates = list(self._settleable_bills())[:-1]
        needed = sum(len(spec[5]) for spec in todo)
        if len(candidates) < needed:
            _logger.warning(
                "SIMRS demo: hanya %s tagihan siap bayar untuk %s pembayaran "
                "shift kasir — sebagian shift akan lebih tipis dari rencana",
                len(candidates), needed,
            )
        plan, cursor = [], 0
        for spec in todo:
            take = candidates[cursor:cursor + len(spec[5])]
            cursor += len(take)
            plan.append((spec, take))
        return plan

    # ------------------------------------------------------------------
    # Satu shift
    # ------------------------------------------------------------------
    def _cashier_shift(self, cashier, spec, bills):
        key, counter_code, opening, open_min, close_min, methods, shortage = spec
        counter = self.env["hms.cashier.counter"].search(
            [("code", "=", counter_code)], limit=1
        )
        if not counter or not bills:
            _logger.warning(
                "SIMRS demo: shift %s dilewati (loket %s, %s tagihan)",
                key, counter_code, len(bills),
            )
            return self.env["hms.cashier.session"]
        now = fields.Datetime.now()
        opened_at, closed_at = self._cashier_shift_clock(now, open_min, close_min)
        # Batas atas jam kwitansi: shift berjalan tidak boleh memuat
        # pembayaran dari masa depan, dan shift tertutup tidak boleh memuat
        # pembayaran setelah lacinya dihitung.
        limit = (closed_at - timedelta(minutes=10)) if closed_at else (now - timedelta(minutes=10))
        limit = max(limit, opened_at + timedelta(minutes=10))

        # Indeks unik `_one_open_per_user` berlaku pada shift yang BELUM
        # tertutup, dan Postgres memeriksanya saat INSERT — bukan saat commit.
        # Penutupan shift sebelumnya masih mengendap di cache ORM, sehingga
        # shift berikutnya di loket yang sama ditolak sebagai "shift terbuka
        # kedua" padahal yang pertama sudah ditutup beberapa baris di atas.
        # Gejalanya UniqueViolation mentah di tengah `-u`, bukan UserError.
        self.env.flush_all()
        Session = self.env["hms.cashier.session"].with_user(cashier)
        session = Session.create({
            "counter_id": counter.id,
            "opening_cash": opening,
            "opened_at": opened_at,
        })
        self._keep(key, session)

        Payment = self.env["hms.payment"].with_user(cashier)
        gave_change = False
        for index, (method, bill) in enumerate(zip(methods, bills)):
            paid_at = max(
                bill.encounter_id.closed_at + timedelta(minutes=20),
                opened_at + timedelta(minutes=20 * (index + 1)),
            )
            paid_at = max(opened_at + timedelta(minutes=5), min(paid_at, limit))
            amount = bill.amount_due
            # Satu kembalian yang benar-benar dibayarkan, dan hanya di shift
            # yang sudah ditutup: kembalian mengurangi kas seharusnya, dan
            # menaruhnya di shift berjalan membuat "modal awal + tunai masuk"
            # tidak lagi terbaca langsung dari layar.
            tendered = amount
            if method == "cash" and closed_at and not gave_change:
                tendered = 50000.0 * (int(amount // 50000) + 1)
                gave_change = True
            Payment.create({
                "bill_id": bill.id,
                "session_id": session.id,
                "method": method,
                "amount": amount,
                "tendered": tendered,
                "paid_at": paid_at,
                "reference": self._payment_reference(method, index),
            })
        if close_min is None:
            return session
        return self._close_cashier_shift(session, closed_at, shortage)

    def _cashier_shift_clock(self, now, open_min, close_min):
        """Jam buka dan tutup shift, tanpa pernah melewati "sekarang".

        Menitnya mutlak terhadap tengah malam supaya garis waktu loket
        sejajar dengan papan kunjungan hari ini. Tetapi penyemaian bisa saja
        dijalankan pukul delapan pagi, dan shift siang yang dinyatakan buka
        pukul dua belas akan melahirkan kwitansi dari masa depan. Bila itu
        terjadi, garis waktunya dimampatkan ke belakang — rapat, tapi tetap
        berurutan — bukan dibiarkan mendahului jam dinding.
        """
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        opened_at = midnight + timedelta(minutes=open_min)
        closed_at = midnight + timedelta(minutes=close_min) if close_min is not None else None
        horizon = now - timedelta(minutes=15)
        if closed_at and closed_at > horizon:
            span = closed_at - opened_at
            closed_at = horizon
            opened_at = min(opened_at, closed_at - span)
        opened_at = min(opened_at, horizon - timedelta(minutes=30))
        return opened_at, closed_at

    def _payment_reference(self, method, index):
        if method in ("edc_debit", "edc_credit"):
            return "APPR-%06d" % (481200 + index * 37)
        if method == "qris":
            return "QR-%08d" % (10450000 + index * 911)
        if method == "transfer":
            return "TRF-%08d" % (73100000 + index * 517)
        return False

    def _close_cashier_shift(self, session, closed_at, shortage):
        """Tutup lewat urutan yang sah, lalu kembalikan jamnya.

        ``counted_amount`` diisi baris per baris seperti berita acara hitung
        fisik. Selisih yang bukan nol WAJIB berketerangan — gerbangnya ada di
        ``action_close()`` dan memang harus dipenuhi, bukan dihindari.
        """
        session.action_start_closing()
        for line in session.line_ids:
            values = {"counted_amount": line.expected_amount}
            if shortage and line.method == "cash":
                values["counted_amount"] = line.expected_amount + shortage
                values["note"] = SHORTAGE_NOTE
            line.write(values)
        session.action_close()
        # Jam penutupan dibekukan model ke "sekarang"; dikembalikan ke jam
        # yang dinyatakan spesifikasi shift, sama seperti _realign_klpcm().
        session.write({"closed_at": closed_at})
        _logger.info("SIMRS demo: shift kasir %s ditutup, selisih %s",
                     session.name, session.difference)
        return session


class HmsDemoBuilder(models.AbstractModel):
    """Titik masuk penyemaian ulang hari kerja kasir tanpa ``-u`` penuh."""
    _inherit = "hms.demo.builder"

    @api.model
    def seed_cashier_day(self):
        self._assert_demo_database()
        return self.env["hms.demo.content"]._cashier_day()
