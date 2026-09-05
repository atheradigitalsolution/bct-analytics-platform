# -*- coding: utf-8 -*-
"""Public intake landing zone.

Raw submissions land here first. A BA/CSM reviews them and clicks
"Promote to Journey" to materialize an ``onboarding.journey`` record.

DUA REPRESENTASI, SENGAJA. ``raw_payload_json`` adalah catatan apa adanya dari apa
yang dikirim — ia bukti, dan bukti tidak boleh diedit menjadi lebih rapi. Kolom
terpilih di sebelahnya adalah proyeksi yang boleh dibaca mesin lain: hub-portal
membacanya lewat sebuah view, dan view itu tidak pernah menyentuh payload mentah.
Memisahkan keduanya berarti daftar-putih dijaga di tempat penulisan, satu kali,
bukan diulang di setiap pembaca.
"""

from __future__ import annotations

import json
import logging
import secrets

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class OnboardingPublicSubmission(models.Model):
    _name = "onboarding.public.submission"
    _description = "Public Onboarding Submission (raw inbox)"
    _order = "submitted_at desc"

    name = fields.Char(
        compute="_compute_name",
        store=True,
    )
    raw_payload_json = fields.Text(required=True)
    public_token = fields.Char(
        required=True,
        copy=False,
        index=True,
        default=lambda self: secrets.token_urlsafe(24),
    )
    source_ip_hash = fields.Char(
        help="SHA-256 of the source IP (no raw IP stored, PDP-friendly).",
        index=True,
    )
    submitted_at = fields.Datetime(
        required=True,
        default=fields.Datetime.now,
        index=True,
    )
    status = fields.Selection(
        [
            ("submitted", "Submitted"),
            ("promoted", "Promoted"),
            ("rejected", "Rejected"),
        ],
        default="submitted",
        required=True,
        index=True,
    )
    journey_id = fields.Many2one(
        "onboarding.journey",
        ondelete="set null",
        copy=False,
    )
    rejection_reason = fields.Text()

    # ------------------------------------------------------------------ proyeksi
    # Kolom terpilih, diisi saat create dari payload yang sudah dibersihkan.
    # Yang TIDAK ada di sini juga merupakan keputusan: `npwp`, `bank_name`, dan
    # `bank_account` tidak pernah diangkat, sehingga view untuk hub-portal secara
    # struktural tidak bisa membocorkannya walau seseorang menambah kolom di sana.
    company_name = fields.Char(readonly=True, index=True)
    partner_name = fields.Char(readonly=True)
    contact_email = fields.Char(readonly=True)
    contact_phone = fields.Char(readonly=True)
    vertical_target_hint = fields.Char(
        readonly=True,
        help="Vertikal yang disebut pengirim. Char bebas, bukan relasi: ini klaim "
             "pengunjung, belum data yang sudah divalidasi siapa pun.",
    )
    company_size = fields.Char(readonly=True)
    interest = fields.Char(readonly=True)
    current_system = fields.Char(readonly=True)
    message = fields.Text(readonly=True)
    source = fields.Char(readonly=True, index=True)
    consent_given = fields.Boolean(readonly=True)
    payload_bytes = fields.Integer(
        readonly=True,
        help="Ukuran payload tersimpan. Dicatat karena kolom ini ditulis oleh "
             "pihak anonim dan pertumbuhannya harus bisa dilihat, bukan ditebak.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._fill_projection(vals)
        return super().create(vals_list)

    @api.model
    def _fill_projection(self, vals):
        """Isi kolom terpilih dari payload. Dipanggil untuk SETIAP jalur create —
        controller publik, orchestrator, wizard internal, dan impor data — supaya
        tidak ada pintu yang menghasilkan baris tanpa proyeksi."""
        # Tidak ada jalan pintas "kalau company_name sudah ada, berhenti": pemanggil
        # yang mengisi satu kolom akan meninggalkan sisanya kosong selamanya.
        # `setdefault` di bawah sudah menjaga nilai yang dipasok pemanggil.
        try:
            data = json.loads(vals.get("raw_payload_json") or "{}")
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}

        def take(key, limit):
            value = data.get(key)
            if value is None or isinstance(value, (dict, list)):
                return False
            text = str(value).strip()
            return text[:limit] if text else False

        vals.setdefault("company_name", take("company_name", 200))
        vals.setdefault("partner_name", take("partner_name", 120))
        vals.setdefault("contact_email", take("contact_email", 200) or take("partner_email", 200))
        vals.setdefault("contact_phone", take("contact_phone", 40))
        vals.setdefault("vertical_target_hint", take("vertical_target", 100))
        vals.setdefault("company_size", take("company_size", 60))
        vals.setdefault("interest", take("interest", 120))
        vals.setdefault("current_system", take("current_system", 200))
        vals.setdefault("message", take("message", 4000))
        vals.setdefault("source", take("source", 120))
        vals.setdefault("consent_given", bool(data.get("consent_given")))
        vals.setdefault("payload_bytes", len((vals.get("raw_payload_json") or "").encode("utf-8")))

    _public_token_uniq = models.Constraint(
        "unique(public_token)",
        "Submission token must be unique.",
    )

    # ------------------------------------------------------------------ view untuk hub-portal
    #: Role hak-minimal yang dipakai hub-portal. Kalau belum ada (instalasi tanpa
    #: control plane), grant dilewati dan itu bukan kegagalan.
    _READER_ROLE = "tenant_orchestrator"

    def init(self):
        """Terbitkan `onboarding.public_submission_overview` untuk hub-portal.

        KENAPA VIEW DAN BUKAN GRANT LANGSUNG — sama persis dengan alasan
        `billing.subscription_overview`: hub-portal tersambung sebagai role
        hak-minimal, dan memberinya SELECT pada tabel Odoo berarti melebarkan role
        itu ke seluruh basis data kontrol.

        KENAPA `raw_payload_json` TIDAK ADA DI SINI. Payload mentah adalah bukti,
        dan bukti tidak dikirim ke antarmuka. Ia juga satu-satunya kolom yang
        bentuknya ditentukan pengirim; mengekspornya berarti setiap kolom baru yang
        suatu hari diterima intake ikut terbit ke portal tanpa ada yang memutuskan.
        Kolom di bawah adalah proyeksi yang sudah disaring saat penulisan.

        KENAPA `init()` DAN BUKAN `post_init_hook`. Hook hanya berjalan saat INSTALL;
        `init()` berjalan pada setiap upgrade modul, jadi definisi di berkas ini
        selalu yang berlaku.
        """
        super().init()
        cr = self.env.cr
        cr.execute("CREATE SCHEMA IF NOT EXISTS onboarding")
        cr.execute(
            """
            CREATE OR REPLACE VIEW onboarding.public_submission_overview AS (
                SELECT
                    s.id,
                    s.submitted_at,
                    s.status,
                    s.company_name,
                    s.partner_name,
                    s.contact_email,
                    s.contact_phone,
                    s.vertical_target_hint,
                    s.company_size,
                    s.interest,
                    s.current_system,
                    s.message,
                    s.source,
                    s.consent_given,
                    s.payload_bytes,
                    s.journey_id,
                    j.stage       AS journey_stage,
                    s.rejection_reason
                FROM onboarding_public_submission s
                LEFT JOIN onboarding_journey j ON j.id = s.journey_id
            )
            """
        )
        cr.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (self._READER_ROLE,))
        if not cr.fetchone():
            _logger.warning(
                "role %s tidak ada; onboarding.public_submission_overview dibuat tanpa grant",
                self._READER_ROLE,
            )
            return
        # Nama role tidak bisa diparameterkan di GRANT, jadi ia konstanta modul dan
        # bukan masukan dari luar.
        cr.execute("GRANT USAGE ON SCHEMA onboarding TO %s" % self._READER_ROLE)
        cr.execute(
            "GRANT SELECT ON onboarding.public_submission_overview TO %s" % self._READER_ROLE
        )
        _logger.info(
            "onboarding.public_submission_overview siap; SELECT diberikan ke %s",
            self._READER_ROLE,
        )

    # ------------------------------------------------------------------ API
    @api.model
    def create_from_payload(self, payload):
        """Create a submission from a JSON payload (called by orchestrator /v1/intake).

        Returns ``{token, status_url, id}`` so the public landing can
        immediately show the customer a status link.
        """
        import hashlib

        if not isinstance(payload, dict):
            raise UserError(_("payload must be a dict"))
        if not payload.get("company_name"):
            raise UserError(_("company_name is required"))
        source_ip = payload.pop("source_ip", None)
        ip_hash = hashlib.sha256(source_ip.encode("utf-8")).hexdigest()[:32] if source_ip else False
        rec = self.sudo().create(
            {
                "raw_payload_json": json.dumps(payload),
                "source_ip_hash": ip_hash,
            }
        )
        return {
            "id": rec.id,
            "token": rec.public_token,
            "status_url": f"/onboarding/public/status/{rec.public_token}",
        }

    @api.depends("raw_payload_json", "submitted_at")
    def _compute_name(self):
        for rec in self:
            label = "Submission"
            try:
                data = json.loads(rec.raw_payload_json or "{}")
                label = data.get("partner_name") or data.get("company_name") or label
            except Exception:
                pass
            rec.name = f"{label} @ {rec.submitted_at or ''}"

    # ------------------------------------------------------------------ actions
    def action_promote_to_journey(self):
        self.ensure_one()
        if self.status == "promoted" and self.journey_id:
            return self._open_journey()
        try:
            data = json.loads(self.raw_payload_json or "{}")
        except Exception as exc:
            raise UserError(_("Cannot parse submission payload: %s") % exc) from exc

        partner_name = data.get("partner_name") or data.get("company_name") or _("Unknown")
        partner_email = data.get("partner_email") or data.get("contact_email")
        partner_phone = data.get("contact_phone")
        Partner = self.env["res.partner"].sudo()  # nosemgrep: bct-odoo-sudo-on-tenant-scoped-model  # public intake has no logged-in user; partner search/create needs sudo; tenancy is per-database (dbfilter), not per-row
        partner = False
        if partner_email:
            partner = Partner.search([("email", "=", partner_email)], limit=1)
        if not partner:
            partner_vals = {"name": partner_name, "is_company": True}
            if partner_email:
                partner_vals["email"] = partner_email
            if partner_phone:
                partner_vals["phone"] = partner_phone
            partner = Partner.create(partner_vals)

        # Best-effort initial stage based on what the intake provided.
        has_brd = bool(data.get("brd_file_base64s"))
        initial_stage = "brd_uploaded" if has_brd else "intake"

        journey_vals = {
            "name": _("Onboarding - %s") % partner_name,
            "partner_id": partner.id,
            "stage": initial_stage,
            "company_profile_json": self.raw_payload_json,
        }
        if "vertical_target" in self.env["onboarding.journey"]._fields and data.get("vertical_target"):
            journey_vals["vertical_target"] = data["vertical_target"]

        journey = self.env["onboarding.journey"].sudo().create(journey_vals)

        # Extract any uploaded BRD files into ir.attachment + brd.document so
        # the AI analyzer has something to chew on.
        brd_files = data.get("brd_file_base64s") or []
        brd_filenames = data.get("brd_filenames") or []
        BrdDocument = self.env["brd.document"].sudo()
        Attachment = self.env["ir.attachment"].sudo()
        for idx, b64 in enumerate(brd_files):
            if not b64:
                continue
            try:
                # b64 might be a data URL ("data:application/...;base64,XXX")
                if isinstance(b64, str) and "," in b64 and b64.startswith("data:"):
                    b64 = b64.split(",", 1)[1]
                fname = (
                    brd_filenames[idx] if idx < len(brd_filenames) else None
                ) or f"BRD-{partner_name}-{idx + 1}.docx"
                att = Attachment.create(
                    {
                        "name": fname,
                        "datas": b64,
                        "res_model": "brd.document",
                        "res_id": 0,
                    }
                )
                doc_vals = {
                    "name": fname.rsplit(".", 1)[0],
                    "document_attachment_id": att.id,
                    "document_filename": fname,
                    "vertical_target_id": False,
                    "state": "draft",
                }
                if "journey_id" in BrdDocument._fields:
                    doc_vals["journey_id"] = journey.id
                if data.get("vertical_target") and "vertical_target" in BrdDocument._fields:
                    doc_vals["vertical_target"] = data["vertical_target"]
                if "company_profile_json" in BrdDocument._fields:
                    doc_vals["company_profile_json"] = json.dumps(
                        {
                            k: data.get(k)
                            for k in (
                                "company_name",
                                "contact_email",
                                "contact_phone",
                                "npwp",
                                "bank_name",
                                "bank_account",
                            )
                        }
                    )
                doc = BrdDocument.create(doc_vals)
                # Re-point attachment to the created BRD record so the Documents app picks it up.
                att.write({"res_id": doc.id})
            except Exception as e:
                _logger.warning("Failed to materialize BRD attachment #%d from submission %s: %s", idx, self.id, e)

        self.write({"status": "promoted", "journey_id": journey.id})
        return self._open_journey()

    def action_reject(self):
        for rec in self:
            rec.status = "rejected"
        return True

    def _open_journey(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "onboarding.journey",
            "res_id": self.journey_id.id,
            "view_mode": "form",
        }
