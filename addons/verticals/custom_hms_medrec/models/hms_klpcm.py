# -*- coding: utf-8 -*-
"""KLPCM — Kelengkapan Pengisian Catatan Medis.

=============================================================================
KEPUTUSAN: KLPCM ADALAH GERBANG, BUKAN LAPORAN
=============================================================================

Di kebanyakan SIMRS, analisis kelengkapan berkas berakhir sebagai satu angka
persen di rapat mutu bulanan. Angka itu tidak pernah mengubah apa pun, karena
saat rapat digelar berkasnya sudah terlanjur dikoding, diklaim, dan (bila
kurang lengkap) dikembalikan BPJS.

Di sini urutannya dibalik. Selama masih ada baris KLPCM ``open`` pada sebuah
kunjungan, ``hms.claim.action_start_coding`` menolak kunjungan itu. Biaya
menahan berkas satu hari di meja PMIK jauh lebih kecil daripada biaya klaim
*pending* yang baru ketahuan enam bulan kemudian — penyebab pending riil yang
paling sering justru administratif: resume tanpa tanda tangan DPJP, laporan
operasi tidak ada, jam masuk/keluar kosong.

=============================================================================
KEPUTUSAN: TIDAK ADA TOMBOL "TANDAI LENGKAP"
=============================================================================

Satu-satunya cara menutup baris KLPCM adalah **melengkapi dokumennya**, lalu
analisis ulang menutupnya sendiri (``_analyze_encounter``). Tidak disediakan
aksi manual "tandai sudah lengkap", karena tombol seperti itu selalu berakhir
dipakai untuk mengosongkan antrian menjelang tutup bulan, dan begitu itu
terjadi seluruh gerbang di atas berubah menjadi formalitas.

Konsekuensi yang diterima: komponen yang memang tidak relevan untuk sebuah
kunjungan tidak boleh "di-waive", ia harus tidak pernah dianggap wajib sejak
awal. Karena itu ``_required_components`` menghitung kewajiban per jenis
kunjungan, bukan memakai satu daftar untuk semua.

=============================================================================
KEPUTUSAN: ANALISIS MENULIS DENGAN ``sudo()`` — DAN KENAPA ITU BUKAN BYPASS
=============================================================================

Analisis dipicu oleh orang yang menutup kunjungan: dokter, perawat, atau
petugas pendaftaran. Tidak satu pun dari mereka adalah PMIK, dan memberi
mereka hak tulis pada ``hms.klpcm`` berarti setiap staf klinis bisa membuat
baris KLPCM palsu — yang, karena KLPCM adalah gerbang koding, berarti setiap
staf klinis bisa memblokir klaim.

Jadi **keputusannya tidak dielevasi, pembukuannya yang dielevasi**: apa yang
kurang dihitung dari dokumen yang ada (fakta, bukan wewenang), penulisan
barisnya dilakukan atas nama sistem. Ini pola yang sama dengan
``hms.access.log`` dan ``hms.event`` di repo ini, dan alasan yang sama dengan
keputusan 6 di ``/opt/simrs/docs/DECISIONS.md``.

Sebaliknya, **gerbangnya sendiri tidak pernah memakai ``sudo()``**: koder
membaca ``hms.klpcm`` dengan haknya sendiri. Karena itu hak **baca** diberikan
selebar mungkin (seluruh ``group_hms_staff``) — sebuah gerbang yang lolos
karena pembacanya tidak berhak membaca adalah gerbang yang gagal senyap, dan
kegagalan senyap persis yang tidak boleh terjadi pada penjaga klaim.
"""
import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Tiga area analisis kuantitatif yang lazim dipakai PMIK — identifikasi,
# laporan penting, autentikasi — dipecah menjadi komponen yang masing-masing
# punya satu sumber data yang bisa diperiksa. Komponen tanpa sumber data yang
# jelas sengaja tidak dibuat: ia hanya akan menjadi baris yang selalu terbuka.
KLPCM_COMPONENTS = [
    ("identity", "Identifikasi — identitas pasien lengkap"),
    ("initial_medical", "Laporan penting — asesmen awal medis"),
    ("initial_nursing", "Laporan penting — asesmen awal keperawatan"),
    ("cppt", "Laporan penting — CPPT / catatan perkembangan"),
    ("summary", "Laporan penting — resume medis / ringkasan pulang final"),
    ("consent", "Laporan penting — persetujuan pasien"),
    ("diagnostic", "Laporan penting — hasil penunjang"),
    ("authentication", "Autentikasi — nama & tanda tangan pada catatan"),
]
COMPONENT_LABELS = dict(KLPCM_COMPONENTS)


class HmsKlpcm(models.Model):
    _name = "hms.klpcm"
    _description = "Ketidaklengkapan Berkas Rekam Medis (KLPCM)"
    _order = "due_at, id"

    encounter_id = fields.Many2one(
        "hms.encounter", "Kunjungan", required=True, ondelete="cascade", index=True,
    )
    patient_id = fields.Many2one(related="encounter_id.patient_id", store=True, index=True)
    unit_id = fields.Many2one(related="encounter_id.unit_id", store=True, index=True)
    component = fields.Selection(KLPCM_COMPONENTS, "Komponen", required=True, index=True)
    kind = fields.Selection(
        [("quantitative", "Kuantitatif"), ("qualitative", "Kualitatif")],
        string="Jenis Analisis", required=True, default="quantitative", index=True,
        help="Kuantitatif: ada atau tidak ada dokumennya, diperiksa mesin. "
             "Kualitatif: isinya konsisten atau tidak, diperiksa manusia.",
    )
    detail = fields.Char(
        "Rincian Temuan",
        help="Apa persisnya yang kurang, mis. '2 catatan belum ditandatangani'.",
    )
    responsible_id = fields.Many2one(
        "hms.practitioner", "Penanggung Jawab", index=True,
        help="PPA yang harus melengkapi. Untuk komponen medis diisi DPJP "
             "kunjungan; komponen yang tidak punya penanggung jawab jelas "
             "dibiarkan kosong dan menjadi tugas PMIK.",
    )
    analyzed_at = fields.Datetime("Waktu Analisis", readonly=True, default=fields.Datetime.now)
    due_at = fields.Datetime(
        "Tenggat", readonly=True, index=True,
        help="Waktu kunjungan selesai + hms.settings.klpcm_due_hours. Dibekukan "
             "saat baris dibuat: tenggat sebuah berkas adalah kebijakan yang "
             "berlaku ketika berkas itu ditutup, bukan kebijakan hari ini.",
    )
    due_hours_applied = fields.Integer("Tenggat Terpakai (jam)", readonly=True)
    state = fields.Selection(
        [("open", "Terbuka"), ("completed", "Lengkap")],
        default="open", required=True, index=True,
    )
    closed_at = fields.Datetime("Waktu Terlengkapi", readonly=True, copy=False)
    auto_detected = fields.Boolean(
        "Terdeteksi Otomatis", default=True, readonly=True,
        help="False berarti baris ini ditambahkan manual oleh petugas analisis "
             "kualitatif; baris seperti itu juga hanya tertutup oleh analisis "
             "ulang bila komponennya kuantitatif.",
    )
    is_overdue = fields.Boolean("Lewat Tenggat", compute="_compute_is_overdue", search="_search_is_overdue")
    company_id = fields.Many2one("res.company", default=lambda s: s.env.company, required=True)

    # Satu komponen hanya boleh punya satu baris terbuka per kunjungan.
    # Partial unique index, bukan constraint biasa: baris yang sudah
    # `completed` justru harus boleh berdampingan dengan temuan baru pada
    # komponen yang sama bila berkasnya sempat lengkap lalu dibuka lagi.
    _one_open_per_component = models.UniqueIndex(
        "(encounter_id, component) WHERE state = 'open'",
    )

    @api.depends("state", "due_at")
    def _compute_is_overdue(self):
        now = fields.Datetime.now()
        for rec in self:
            rec.is_overdue = bool(rec.state == "open" and rec.due_at and rec.due_at < now)

    def _search_is_overdue(self, operator, value):
        if operator not in ("=", "!="):
            raise UserError(_("Filter 'lewat tenggat' hanya menerima = atau !=."))
        overdue = [("state", "=", "open"), ("due_at", "<", fields.Datetime.now())]
        wants_overdue = bool(value) == (operator == "=")
        if wants_overdue:
            return overdue
        return ["!", "&"] + overdue

    @api.depends("component", "encounter_id", "state")
    def _compute_display_name(self):
        for rec in self:
            label = COMPONENT_LABELS.get(rec.component, rec.component or "")
            rec.display_name = f"{rec.encounter_id.name or ''} — {label}".strip(" —")

    def unlink(self):
        """Temuan yang bisa dihapus bukan temuan.

        Sama alasannya dengan laporan insiden: begitu baris KLPCM bisa
        dihapus, cara tercepat melewati gerbang koding adalah menghapus
        penjaganya. Baris yang keliru ditutup oleh analisis ulang, tidak
        dihapus.
        """
        raise UserError(_(
            "Baris KLPCM tidak dapat dihapus. Lengkapi dokumennya — analisis "
            "ulang akan menutupnya sendiri."
        ))

    # ------------------------------------------------------------------
    # Analisis kuantitatif
    # ------------------------------------------------------------------
    @api.model
    def _klpcm_due_hours(self):
        hours = self.env["hms.settings"].get_settings().klpcm_due_hours
        # Nol/negatif berarti parameter belum diisi. Jatuh ke 2x24 jam
        # (standar akreditasi rekam medis) daripada menerbitkan tenggat yang
        # sudah lewat pada detik baris itu dibuat.
        return hours if hours and hours > 0 else 48

    @api.model
    def _required_components(self, encounter):
        """Komponen yang wajib ada untuk satu jenis kunjungan.

        Dihitung, bukan didaftar sekali untuk semua: menuntut asesmen awal
        keperawatan pada kunjungan poli membuat setiap berkas rawat jalan
        abadi tidak lengkap, dan antrian yang selalu penuh adalah antrian yang
        tidak pernah dibaca.
        """
        required = {"identity", "cppt", "summary", "authentication"}
        if encounter.type in ("inpatient", "daycare"):
            required |= {"initial_medical", "initial_nursing", "consent"}
        elif encounter.type == "emergency":
            required |= {"initial_nursing", "consent"}
        # Penunjang hanya wajib bila memang ada order penunjang di kunjungan
        # ini. Kunjungan tanpa order tidak punya hasil yang bisa kurang.
        if self.env["hms.order"].sudo().search_count([("encounter_id", "=", encounter.id)]):
            required.add("diagnostic")
        return required

    @api.model
    def _missing_components(self, encounter):
        """Komponen yang kurang beserta rinciannya, dari dokumen yang ada.

        Mengembalikan ``{component: detail}``. Setiap pemeriksaan membaca
        dengan ``sudo()`` karena ini analisis mesin, bukan seseorang membuka
        rekam medis: mencatatnya di ``hms.access.log`` sebagai pembacaan
        manusia justru mengaburkan jejak akses yang sesungguhnya.
        """
        env = self.env
        missing = {}
        required = self._required_components(encounter)

        if "identity" in required:
            gaps = []
            if encounter.identity_pending:
                gaps.append(_("identitas pasien masih berstatus belum lengkap"))
            if not encounter.patient_id.nik:
                gaps.append(_("NIK belum diisi"))
            if gaps:
                missing["identity"] = ", ".join(gaps)

        notes = env["hms.clinical.note"].sudo().search([
            ("encounter_id", "=", encounter.id), ("is_current", "=", True),
        ])
        if "initial_medical" in required and not notes.filtered(
            lambda n: n.note_type == "medical_initial"
        ):
            missing["initial_medical"] = _("asesmen awal medis belum dibuat")

        if "cppt" in required and not notes:
            missing["cppt"] = _("belum ada satu pun catatan klinis pada kunjungan ini")

        if "authentication" in required:
            unsigned = notes.filtered(lambda n: not n.signed)
            if unsigned:
                missing["authentication"] = _(
                    "%s catatan klinis belum ditandatangani"
                ) % len(unsigned)

        if "initial_nursing" in required:
            has_initial = env["hms.nursing.assessment"].sudo().search_count([
                ("encounter_id", "=", encounter.id), ("type", "=", "initial"),
            ])
            if not has_initial:
                missing["initial_nursing"] = _("asesmen awal keperawatan belum dibuat")

        if "summary" in required:
            summary_type = "discharge" if encounter.type == "inpatient" else "outpatient"
            final = env["hms.summary"].sudo().search_count([
                ("encounter_id", "=", encounter.id),
                ("type", "=", summary_type),
                ("state", "=", "final"),
            ])
            if not final:
                missing["summary"] = _("resume/ringkasan pulang belum difinalkan")

        if "consent" in required:
            signed = env["hms.consent"].sudo().search_count([
                ("encounter_id", "=", encounter.id), ("state", "=", "signed"),
            ])
            if not signed:
                missing["consent"] = _("belum ada persetujuan yang ditandatangani")

        if "diagnostic" in required:
            open_orders = env["hms.order"].sudo().search_count([
                ("encounter_id", "=", encounter.id),
                ("state", "not in", ("done", "cancelled")),
            ])
            if open_orders:
                missing["diagnostic"] = _(
                    "%s order penunjang belum selesai/dibatalkan"
                ) % open_orders

        return missing

    @api.model
    def _responsible_for(self, encounter, component):
        """Siapa yang harus melengkapi komponen ini.

        Komponen keperawatan tidak punya satu penanggung jawab yang bisa
        ditebak dari kunjungan (perawatnya berganti tiap shift), jadi
        dibiarkan kosong — itu jujur, dan barisnya tetap muncul di daftar
        kerja PMIK dan kepala ruang.
        """
        if component in ("initial_medical", "cppt", "summary", "consent", "authentication"):
            return encounter.practitioner_id
        return encounter.practitioner_id.browse()

    @api.model
    def analyze_encounter(self, encounter):
        """Jalankan (ulang) analisis kuantitatif untuk satu kunjungan.

        Idempoten dua arah: komponen yang masih kurang dibuatkan barisnya bila
        belum ada, komponen yang sudah terisi menutup baris terbukanya. Boleh
        dipanggil berkali-kali; itu memang cara baris KLPCM tertutup.
        """
        Klpcm = self.sudo()
        analyzed = Klpcm.browse()
        for enc in encounter:
            if enc.state in ("cancelled", "registered", "in_progress"):
                # Berkas yang pelayanannya belum selesai belum bisa dinilai
                # lengkap atau tidak; menilainya sekarang hanya menghasilkan
                # antrian palsu.
                continue
            missing = self._missing_components(enc)
            existing = Klpcm.search([
                ("encounter_id", "=", enc.id), ("kind", "=", "quantitative"),
            ])
            open_by_component = {
                rec.component: rec for rec in existing if rec.state == "open"
            }

            # Tutup yang sudah terisi.
            now = fields.Datetime.now()
            resolved = Klpcm.browse()
            for component, rec in open_by_component.items():
                if component not in missing:
                    resolved |= rec
            if resolved:
                resolved.write({"state": "completed", "closed_at": now})
                for rec in resolved:
                    rec.env["hms.event"].emit("klpcm.completed", {
                        "encounter_id": enc.id,
                        "component": rec.component,
                    })

            # Buka yang masih kurang.
            hours = self._klpcm_due_hours()
            anchor = enc.closed_at or fields.Datetime.now()
            to_create = []
            for component, detail in missing.items():
                if component in open_by_component:
                    # Rinciannya bisa berubah (mis. dari 3 catatan menjadi 1);
                    # barisnya tetap sama supaya umur temuan tidak ter-reset.
                    open_by_component[component].write({
                        "detail": detail, "analyzed_at": now,
                    })
                    continue
                to_create.append({
                    "encounter_id": enc.id,
                    "component": component,
                    "kind": "quantitative",
                    "detail": detail,
                    "responsible_id": self._responsible_for(enc, component).id or False,
                    "due_hours_applied": hours,
                    "due_at": anchor + timedelta(hours=hours),
                    "auto_detected": True,
                    "analyzed_at": now,
                })
            if to_create:
                created = Klpcm.create(to_create)
                analyzed |= created
                enc.env["hms.event"].emit("klpcm.opened", {
                    "encounter_id": enc.id,
                    "components": [v["component"] for v in to_create],
                })
        return analyzed

    @api.model
    def _cron_reanalyze_open(self):
        """Analisis ulang kunjungan yang masih punya KLPCM terbuka.

        PPA melengkapi berkas lewat entri baru di modul lain; modul-modul itu
        tidak tahu apa-apa tentang KLPCM dan tidak seharusnya tahu. Cron ini
        yang menutup lingkarannya, sehingga menutup baris KLPCM tidak pernah
        bergantung pada satu modul mengingat memanggil modul lain.
        """
        encounters = self.sudo().search([("state", "=", "open")]).mapped("encounter_id")
        if encounters:
            self.analyze_encounter(encounters)
        return len(encounters)
