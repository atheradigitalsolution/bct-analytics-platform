# -*- coding: utf-8 -*-
"""Angka yang dibaca layar penjualan, bukan angka yang dijanjikan penyemai.

KENAPA BERKAS INI ADA
---------------------
Tiga layar pertama yang dilihat calon klien — dasbor, papan bed, dan layar
antrian — semuanya membaca keadaan HARI INI, dan keadaan hari ini adalah
satu-satunya bagian data demo yang bisa kosong tanpa ada satu pun tes yang
merah. Nol kunjungan hari ini bukan kegagalan bagi sistem; ia hanya
kegagalan bagi orang yang sedang memperagakannya.

Batasnya sengaja longgar dan bersumber dari kebutuhan layar, bukan dari
jumlah baris yang kebetulan dihasilkan penyemai hari ini: menegakkan angka
persis akan membuat tes ini merah setiap kali seseorang menambah satu
kunjungan, dan tes yang merah karena alasan yang benar-benar wajar
mengajarkan orang bahwa merah itu normal.
"""
from odoo import fields
from odoo.tests import TransactionCase, tagged
from odoo.tools import float_is_zero


@tagged("post_install", "-at_install", "hms")
class DemoTodayBoardCase(TransactionCase):

    def setUp(self):
        super().setUp()
        self.today = fields.Date.context_today(self.env["hms.encounter"])

    def _today_encounters(self):
        return self.env["hms.encounter"].search([
            ("arrival_at", ">=", "%s 00:00:00" % self.today),
            ("arrival_at", "<=", "%s 23:59:59" % self.today),
        ])

    # --- dasbor -------------------------------------------------------
    def test_the_dashboard_has_visits_to_count_today(self):
        self.assertGreaterEqual(
            len(self._today_encounters()), 10,
            "Dasbor akan menampilkan 'Kunjungan hari ini' yang hampir kosong.",
        )

    def test_the_dashboard_has_emergency_visits_to_count_today(self):
        emergency = self._today_encounters().filtered(lambda e: e.type == "emergency")
        self.assertGreaterEqual(
            len(emergency), 3,
            "'Kunjungan IGD hari ini' tidak akan menunjukkan angka hidup.",
        )

    def test_no_visit_arrives_from_the_future(self):
        """Baris yang mustahil lebih mencolok daripada baris yang tidak ada."""
        now = fields.Datetime.now()
        ahead = self._today_encounters().filtered(lambda e: e.arrival_at > now)
        self.assertFalse(ahead.mapped("name"))

    def test_arrivals_are_heavier_in_the_morning_than_the_afternoon(self):
        """Kedatangan yang tersebar rata adalah tanda pertama data karangan."""
        hours = [e.arrival_at.hour for e in self._today_encounters()]
        morning = len([h for h in hours if h < 4])       # 07:00–11:00 WIB
        afternoon = len([h for h in hours if h >= 6])    # sejak 13:00 WIB
        self.assertGreater(
            morning, afternoon,
            "Poliklinik pagi harus lebih padat daripada sore: %s vs %s"
            % (morning, afternoon),
        )

    def test_today_shows_both_open_and_closed_visits(self):
        """Semua selesai = rumah sakit yang sudah tutup; semua terbuka = macet."""
        states = set(self._today_encounters().mapped("state"))
        self.assertTrue({"registered", "in_progress"} & states)
        self.assertIn("finished", states)

    # --- papan bed ----------------------------------------------------
    def test_bed_occupancy_lands_in_the_band_a_working_hospital_shows(self):
        beds = self.env["hms.bed"].search([("active", "=", True)])
        occupied = beds.filtered(lambda b: b.state == "occupied")
        bor = 100.0 * len(occupied) / len(beds)
        self.assertTrue(
            60.0 <= bor <= 75.0,
            "BOR %.1f%% (%s dari %s bed) di luar pita 60–75%%."
            % (bor, len(occupied), len(beds)),
        )

    def test_the_bed_board_has_movement_later_today(self):
        self.assertTrue(
            self.env["hms.admission"].search_count([
                ("state", "=", "discharge_planned"),
            ]),
            "Tidak ada rencana pulang: papan bed tidak akan bergerak seharian.",
        )

    def test_occupancy_is_spread_over_more_than_one_ward(self):
        wards = self.env["hms.admission"].search([
            ("state", "in", ("admitted", "discharge_planned")),
        ]).mapped("ward_id")
        self.assertGreaterEqual(len(wards), 3)

    def test_every_admission_states_a_patient_a_class_and_a_ward(self):
        incomplete = self.env["hms.admission"].search([
            ("state", "in", ("admitted", "discharge_planned")),
        ]).filtered(lambda a: not (a.patient_id and a.class_id and a.ward_id
                                   and a.entitled_class_id and a.bed_id))
        self.assertFalse(incomplete.mapped("name"))

    def test_no_admission_puts_a_patient_below_the_class_they_are_entitled_to(self):
        """Naik kelas terjadi dan ditagihkan; turun kelas terbaca sebagai bed salah."""
        rank = ["VVIP", "VIP", "I", "II", "III"]
        wrong = []
        for adm in self.env["hms.admission"].search([
            ("state", "in", ("admitted", "discharge_planned")),
        ]):
            if not (adm.class_id and adm.entitled_class_id):
                continue
            if rank.index(adm.class_id.code) > rank.index(adm.entitled_class_id.code):
                wrong.append("%s: bed %s, hak %s"
                             % (adm.name, adm.class_id.code, adm.entitled_class_id.code))
        self.assertFalse(wrong, "\n".join(wrong))

    def test_children_are_in_the_paediatric_ward_and_adults_are_not(self):
        """Pasien 54 tahun di bangsal anak adalah baris yang langsung terbaca salah."""
        misplaced = []
        for adm in self.env["hms.admission"].search([
            ("state", "in", ("admitted", "discharge_planned")),
        ]):
            birth = adm.patient_id.birth_date
            if not birth or not adm.ward_id:
                continue
            age = (self.today - birth).days // 365
            paediatric_ward = adm.ward_id.type == "pediatric"
            if paediatric_ward != (age <= 17):
                misplaced.append("%s: umur %s di bangsal %s (%s)"
                                 % (adm.name, age, adm.ward_id.name, adm.ward_id.type))
        self.assertFalse(misplaced, "\n".join(misplaced))

    # --- layar antrian ------------------------------------------------
    def _tickets_today(self):
        return self.env["hms.qms.ticket"].search([("date", "=", self.today)])

    def test_the_queue_screen_shows_people_already_served_today(self):
        finished = self._tickets_today().filtered(lambda t: t.state == "finished")
        self.assertGreaterEqual(
            len(finished), 20,
            "'Dilayani hari ini' hampir nol sementara antrian panjang — "
            "itu memperagakan loket yang tidak bekerja.",
        )

    def test_the_waiting_queue_is_a_plausible_length_not_a_backlog(self):
        waiting = self._tickets_today().filtered(lambda t: t.state == "waiting")
        self.assertTrue(
            0 < len(waiting) <= 30,
            "%s orang menunggu: antrian kosong tidak memperagakan apa pun, "
            "antrian sepanjang ini memperagakan sistem yang macet." % len(waiting),
        )

    def test_someone_is_being_served_right_now(self):
        self.assertTrue(
            self._tickets_today().filtered(lambda t: t.state in ("called", "serving")),
            "Layar 'Sedang Dipanggil' akan kosong.",
        )

    def test_the_served_tickets_are_spread_over_several_counters(self):
        counters = self._tickets_today().filtered(
            lambda t: t.state == "finished"
        ).mapped("counter_id")
        self.assertGreaterEqual(len(counters), 4)

    def test_waiting_time_is_measured_not_left_at_zero(self):
        """Semua tiket diselesaikan dalam satu detik = KPI lama tunggu nol."""
        finished = self._tickets_today().filtered(lambda t: t.state == "finished")
        self.assertTrue(finished)
        self.assertFalse(
            finished.filtered(lambda t: t.wait_seconds <= 0),
            "Ada tiket selesai dengan lama tunggu nol.",
        )

    def test_yesterdays_numbers_are_not_still_waiting(self):
        left_over = self.env["hms.qms.ticket"].search([
            ("date", "<", self.today),
            ("state", "in", ("waiting", "called", "serving")),
        ])
        self.assertFalse(left_over.mapped("name"))

    def test_no_queue_service_is_listed_twice_under_the_same_name(self):
        """Dua layanan berjudul 'Poli Umum' terbaca sebagai data yang belum dirapikan."""
        names = self.env["hms.qms.service"].search([("active", "=", True)]).mapped("name")
        self.assertEqual(len(names), len(set(names)), sorted(names))

    def test_the_dashboard_has_no_dead_bridging_jobs_to_show_in_red(self):
        """Angka merah di samping angka yang justru ingin diperagakan."""
        self.assertFalse(
            self.env["hms.job"].search_count([("state", "=", "dead")]),
            "Dasbor akan menampilkan pekerjaan mati; bridging memang belum "
            "tersambung di lingkungan ini, jadi antriannya harus dibatalkan.",
        )

    # --- register pasien ----------------------------------------------
    def test_no_two_patients_carry_the_same_name(self):
        """Dua baris bernama sama pada papan bed terbaca sebagai data bangkitan."""
        names = self.env["hms.patient"].search([]).mapped("name")
        duplicates = sorted({n for n in names if names.count(n) > 1})
        self.assertFalse(duplicates, ", ".join(duplicates))

    # --- klaim --------------------------------------------------------
    def test_more_than_one_claim_sits_in_the_red_band(self):
        claims = self.env["hms.claim"].search([("state", "not in", ("paid", "rejected"))])
        near = claims.filtered(lambda c: 0 < c.days_to_deadline <= 30)
        self.assertGreaterEqual(
            len(near), 2,
            "Satu baris saja terbaca sebagai kasus tunggal yang kebetulan; "
            "penanda kedaluwarsa perlu terlihat sedang memperingatkan.",
        )

    def test_claim_deadlines_are_derived_from_discharge_not_written_by_hand(self):
        """Kalau deadline_at pernah ditulis langsung, ia akan lepas dari sumbernya."""
        from dateutil.relativedelta import relativedelta
        drifted = []
        for claim in self.env["hms.claim"].search([("deadline_at", "!=", False)]):
            months = claim.expiry_months_applied or 0
            if not (claim.discharge_at and months):
                continue
            expected = claim.discharge_at + relativedelta(months=months)
            if claim.deadline_at != expected:
                drifted.append("%s: %s bukan %s"
                               % (claim.name, claim.deadline_at, expected))
        self.assertFalse(drifted, "\n".join(drifted[:10]))

    # --- idempotensi --------------------------------------------------
    def test_seeding_the_board_twice_changes_nothing(self):
        """Dibuktikan pada model yang justru dibuat papan hari ini."""
        models = ("hms.encounter", "hms.admission", "hms.bed.assignment",
                  "hms.qms.ticket", "hms.observation", "hms.clinical.note",
                  "hms.diagnosis", "hms.bill", "hms.bill.line", "hms.patient",
                  # Shift kasir dan uang yang masuk ke dalamnya: sebuah
                  # penyemai yang membuka shift tanpa jangkar akan menambah
                  # satu shift setiap `-u`, dan layar kasir baru akan
                  # menolak pembayaran karena indeks unik shift terbuka.
                  "hms.cashier.session", "hms.cashier.session.line",
                  "hms.payment")
        before = {m: self.env[m].search_count([]) for m in models}
        before["occupied"] = self.env["hms.bed"].search_count([("state", "=", "occupied")])
        before["waiting"] = self.env["hms.qms.ticket"].search_count([
            ("date", "=", self.today), ("state", "=", "waiting"),
        ])
        before["finished"] = self.env["hms.qms.ticket"].search_count([
            ("date", "=", self.today), ("state", "=", "finished"),
        ])
        self.env["hms.demo.builder"].seed_all()
        after = {m: self.env[m].search_count([]) for m in models}
        after["occupied"] = self.env["hms.bed"].search_count([("state", "=", "occupied")])
        after["waiting"] = self.env["hms.qms.ticket"].search_count([
            ("date", "=", self.today), ("state", "=", "waiting"),
        ])
        after["finished"] = self.env["hms.qms.ticket"].search_count([
            ("date", "=", self.today), ("state", "=", "finished"),
        ])
        self.assertEqual(before, after)


@tagged("post_install", "-at_install", "hms")
class DemoCashierScreenCase(TransactionCase):
    """Layar kasir, diukur seperti orang rumah sakit membacanya.

    Keterangan slide berbunyi "Kas ditutup dengan angka, bukan dugaan".
    Layarnya membaca ``cashier_session_id`` dari akun yang sedang login —
    bukan jumlah baris tabel ``hms_cashier_session`` — sehingga satu shift
    milik akun lain tetap menghasilkan "Belum ada shift terbuka" dan
    formulir pembukaan, yaitu gambar yang membantah keterangannya sendiri.

    Kontrol positifnya ada di
    ``test_the_closed_shifts_do_not_leak_into_the_cashiers_active_shift``:
    penyemai yang menandai SEMUA shift ``open`` lolos "ada shift terbuka"
    dengan gemilang sambil membuat layar penutupan bohong.
    """

    def setUp(self):
        super().setUp()
        self.cashier = self.env["hms.demo.builder"].demo_user("kasir")
        self.Session = self.env["hms.cashier.session"]

    def _sessions_of_the_cashier(self):
        return self.Session.search([("user_id", "=", self.cashier.id)])

    def _running(self):
        """Persis pencarian yang dipakai ``_user_payload`` di API auth."""
        return self.Session.search([
            ("user_id", "=", self.cashier.id), ("state", "in", ("open", "closing")),
        ])

    # --- shift yang sedang berjalan -----------------------------------
    def test_the_cashier_screen_opens_on_a_shift_that_is_already_running(self):
        self.assertTrue(self.cashier, "Akun demo kasir tidak ada.")
        running = self._running()
        self.assertEqual(
            len(running), 1,
            "Layar kasir menampilkan 'Belum ada shift terbuka' kecuali akun "
            "kasir punya tepat satu shift aktif; ditemukan %s." % len(running),
        )
        self.assertEqual(
            running.opened_at.date(), fields.Datetime.now().date(),
            "Shift aktif dibuka %s, bukan hari ini." % running.opened_at,
        )

    def test_the_running_shift_mixes_at_least_three_ways_of_paying(self):
        """Rekonsiliasi per metode dengan satu metode adalah tabel kosong."""
        running = self._running()
        self.assertTrue(running)
        methods = set(
            running.payment_ids.filtered(lambda p: p.state == "done").mapped("method")
        )
        self.assertGreaterEqual(
            len(methods), 3,
            "Shift berjalan hanya memuat metode %s." % (sorted(methods) or "—"),
        )

    def test_the_running_shift_actually_took_cash_and_not_only_a_float(self):
        running = self._running()
        self.assertTrue(running)
        cash = running.payment_ids.filtered(
            lambda p: p.state == "done" and p.method == "cash"
        )
        self.assertTrue(cash, "Tidak ada penerimaan tunai di shift berjalan.")
        self.assertAlmostEqual(
            running.expected_cash,
            running.opening_cash + sum(cash.mapped("amount")) - sum(cash.mapped("change")),
            places=2,
            msg="Kas seharusnya tidak sama dengan modal awal + tunai masuk − kembalian.",
        )
        self.assertGreater(running.expected_cash, running.opening_cash)

    # --- shift yang sudah ditutup -------------------------------------
    def test_at_least_one_shift_was_closed_and_balanced_to_zero(self):
        closed = self.Session.search([("state", "=", "closed")])
        self.assertTrue(closed, "Tidak ada shift tertutup: layar penutupan kosong.")
        balanced = closed.filtered(
            lambda s: float_is_zero(s.difference, precision_digits=2)
        )
        self.assertTrue(
            balanced,
            "Tidak ada satu pun shift yang tutup dengan selisih nol: %s"
            % ", ".join("%s=%s" % (s.name, s.difference) for s in closed),
        )

    def test_the_closed_shifts_do_not_leak_into_the_cashiers_active_shift(self):
        """Kontrol positif: shift tertutup tidak boleh terbaca sebagai aktif."""
        every = self._sessions_of_the_cashier()
        self.assertGreater(
            len(every), 1,
            "Kasir hanya punya satu shift, jadi kontrol ini tidak bisa merah.",
        )
        active = every.filtered(lambda s: s.state in ("open", "closing"))
        self.assertEqual(len(active), 1, ", ".join(active.mapped("name")))
        self.assertTrue(
            every - active,
            "Semua shift kasir berstatus terbuka — layar penutupan berbohong.",
        )

    def test_every_closed_shift_was_counted_method_by_method(self):
        closed = self.Session.search([("state", "=", "closed")])
        self.assertTrue(closed)
        for session in closed:
            collected = set(
                session.payment_ids.filtered(lambda p: p.state == "done").mapped("method")
            ) | {"cash"}
            counted = set(session.line_ids.mapped("method"))
            self.assertFalse(
                collected - counted,
                "Shift %s menerima %s tetapi tidak menghitungnya."
                % (session.name, sorted(collected - counted)),
            )

    def test_the_difference_column_has_something_to_show(self):
        """Layar yang hanya pernah menampilkan nol tidak memperlihatkan gunanya."""
        closed = self.Session.search([("state", "=", "closed")])
        off = closed.filtered(
            lambda s: not float_is_zero(s.difference, precision_digits=2)
        )
        self.assertTrue(
            off,
            "Semua shift tutup dengan selisih nol; kolom Selisih tidak pernah "
            "terlihat mengerjakan apa pun.",
        )
        for session in off:
            unexplained = session.line_ids.filtered(
                lambda l: not float_is_zero(l.difference, precision_digits=2) and not l.note
            )
            self.assertFalse(
                unexplained.mapped("method"),
                "Selisih tanpa keterangan pada %s." % session.name,
            )

    # --- uang yang bisa dijumlahkan ulang pembaca ---------------------
    def test_no_payment_floats_free_of_a_bill_or_a_shift(self):
        payments = self.env["hms.payment"].search([])
        self.assertTrue(payments, "Tidak ada satu pun pembayaran tercatat.")
        orphan = payments.filtered(
            lambda p: not p.bill_id
            or (p.method not in ("deposit", "receivable") and not p.session_id)
        )
        self.assertFalse(orphan.mapped("name"))

    def test_the_total_collected_is_the_sum_of_the_receipts(self):
        for session in self.Session.search([]):
            done = session.payment_ids.filtered(lambda p: p.state == "done")
            self.assertAlmostEqual(
                session.total_collected, sum(done.mapped("amount")), places=2,
                msg="Total diterima shift %s tidak bisa dijumlahkan ulang." % session.name,
            )

    def test_every_shift_is_counted_in_rupiah(self):
        wrong = self.Session.search([]).filtered(lambda s: s.currency_id.name != "IDR")
        self.assertFalse(
            wrong.mapped("name"),
            "Shift kasir lahir dengan mata uang selain IDR.",
        )


@tagged("post_install", "-at_install", "hms")
class DemoCodingCase(TransactionCase):
    """Cacat yang tidak terlihat sebagai angka salah, dan pembacanya dokter."""

    def test_no_dental_visit_is_coded_as_a_stomach_complaint(self):
        gastric = self.env["hms.diagnosis"].search([("icd10_id.code", "=", "K29.7")])
        self.assertTrue(
            gastric,
            "Tidak ada K29.7 sama sekali di data demo, jadi tes ini tidak bisa merah.",
        )
        dental = gastric.filtered(
            lambda d: "gigi" in (d.encounter_id.unit_id.name or "").lower()
        )
        self.assertFalse(
            ["%s (%s)" % (d.encounter_id.name, d.encounter_id.unit_id.name) for d in dental],
            "Kunjungan Poli Gigi dikode gastritis.",
        )

    def test_every_dental_visit_carries_a_dental_code(self):
        dental_units = self.env["hms.unit"].search([("name", "ilike", "gigi")])
        self.assertTrue(dental_units, "Tidak ada Poli Gigi di data demo.")
        diagnoses = self.env["hms.diagnosis"].search([
            ("encounter_id.unit_id", "in", dental_units.ids),
        ])
        self.assertTrue(diagnoses, "Poli Gigi tidak punya satu pun diagnosis.")
        wrong = diagnoses.filtered(lambda d: not d.icd10_id.code.startswith("K0"))
        self.assertFalse(
            ["%s: %s" % (d.encounter_id.name, d.icd10_id.code) for d in wrong],
            "Diagnosis Poli Gigi di luar blok K00–K09 (penyakit gigi dan jaringan penyangga).",
        )
