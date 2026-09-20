# -*- coding: utf-8 -*-
"""Casemix — worklist klaim, panel koding, transisi state.

=============================================================================
KEPUTUSAN: CONTROLLER TIDAK PUNYA STATE MACHINE SENDIRI
=============================================================================

`POST /casemix/claims/<id>/<action>` hanya memetakan nama aksi ke method
`action_*` di `hms.claim` dan memanggilnya. Tidak ada satu pun pemeriksaan
state di berkas ini: gerbang KLPCM, tenggat enam bulan, empat-mata untuk
selisih besar — semuanya hidup di model, dan menyalinnya ke sini berarti
punya dua aturan yang akan berbeda pada perubahan pertama.

Konsekuensi yang disengaja: `UserError` dari model naik ke `hms_route` dan
keluar sebagai 400 `{"error": {"code": "business_rule", ...}}` dengan pesan
Indonesia yang memang ditulis untuk dibaca petugas. Itulah cara gerbang KLPCM
terlihat di layar sebagai kalimat, bukan sebagai 500.

Nilai yang harus terisi SEBELUM sebuah aksi bisa lolos (catatan review,
alasan pending, catatan perbaikan) diterima lewat `values` dengan daftar
kolom yang eksplisit, ditulis lebih dulu, lalu aksinya dipanggil. Bila
aksinya menolak, penulisan tadi ikut di-rollback bersama transaksinya —
justru yang diinginkan: separuh keadaan tidak pernah tersimpan.
"""
from odoo import _, fields, http
from odoo.http import request

from .base import API_ROOT, error_response, hms_route, paginate

# Aksi yang boleh dipanggil dari HTTP. Daftar putih, bukan getattr bebas:
# tanpa ini `POST /casemix/claims/1/unlink` adalah endpoint yang valid.
CLAIM_ACTIONS = (
    "start_coding", "code_done", "verify_internal", "return_to_coding",
    "finalize", "submit", "start_verification", "approve", "set_pending",
    "resubmit", "open_dispute", "reject", "mark_paid", "expire",
    "run_pregrouping", "refresh_hospital_bill",
)

# Kolom yang boleh diisi layar sebelum sebuah transisi. Semuanya kolom
# penjelasan yang memang diminta model sebagai syarat; tidak satu pun
# menyentuh `state`, nilai uang yang readonly, atau identitas petugas.
CLAIM_WRITABLE = (
    "review_note", "pending_reason", "pending_category", "correction_note",
    "rejection_reason", "dispute_level", "readmission_reason",
    "fragmentation_note", "grouped_tariff", "topup_amount",
)

# Aksi batch yang boleh dipanggil dari HTTP. Alasannya sama dengan
# CLAIM_ACTIONS: tanpa daftar putih, `POST .../unlink` adalah endpoint.
BATCH_ACTIONS = (
    "collect_claims", "add_claims", "remove_claims",
    "submit", "mark_verified", "reconcile", "close",
)

# Kolom batch yang boleh diisi layar. `reconciliation_state`, waktu dan
# identitas pengaju tidak ada di sini: itu milik state machine.
BATCH_WRITABLE = ("fpk_no", "ba_no", "ba_date", "note")

# Kunci batch — hanya boleh diberikan saat pembuatan.
BATCH_KEY_FIELDS = ("service_period", "care_type", "batch_type", "payer_id")

ADJUSTMENT_ACTIONS = ("authorize", "cancel")

ADJUSTMENT_WRITABLE = ("type", "amount", "reason")

CODE_WRITABLE = (
    "kind", "icd10_id", "icd9_id", "role", "seq", "change_reason",
    "source_diagnosis_id", "source_procedure_id", "note",
)

# Ambang "mendekati kedaluwarsa" untuk penanda layar. Bukan aturan bisnis —
# tenggatnya sendiri ada di model — hanya kapan warnanya berubah.
EXPIRING_SOON_DAYS = 30


def _label(record, field_name):
    """Label terjemahan sebuah Selection, atau None."""
    value = record[field_name]
    if not value:
        return None
    return dict(record._fields[field_name].selection).get(value)


def _icd10_title(icd10):
    """ICD-10 tidak punya kolom `name`: namanya Indonesia atau Inggris."""
    return (icd10.name_id or icd10.name_en) if icd10 else None


def _m2o(record):
    return {"id": record.id, "name": record.display_name} if record else None


def claim_brief(claim):
    now = fields.Datetime.now()
    discharge = claim.discharge_at
    return {
        "id": claim.id,
        "name": claim.name,
        "state": claim.state,
        "state_label": _label(claim, "state"),
        "kind": claim.kind,
        "kind_label": _label(claim, "kind"),
        "care_type": claim.care_type,
        "care_type_label": _label(claim, "care_type"),
        "encounter": {
            "id": claim.encounter_id.id,
            "name": claim.encounter_id.name,
            "state": claim.encounter_id.state,
        },
        "patient": {
            "id": claim.patient_id.id,
            "mrn": claim.patient_id.mrn,
            "name": claim.patient_id.name,
        },
        "payer": _m2o(claim.payer_id),
        "discharge_at": discharge,
        # Umur berkas sejak pasien pulang: angka yang dipakai kepala casemix
        # untuk melihat berapa lama klaim menganggur sebelum dikoding.
        "age_days": (now - discharge).days if discharge else None,
        "deadline_at": claim.deadline_at,
        "days_to_deadline": claim.days_to_deadline,
        "is_expired": claim.is_expired,
        "expiring_soon": bool(
            claim.deadline_at
            and not claim.is_expired
            and claim.days_to_deadline <= EXPIRING_SOON_DAYS
        ),
        "klpcm_open_count": claim.klpcm_open_count,
        "open_query_count": claim.open_query_count,
        "hospital_bill_amount": claim.hospital_bill_amount,
        "grouped_tariff": claim.grouped_tariff,
        "topup_amount": claim.topup_amount,
        "variance_amount": claim.variance_amount,
        "is_high_variance": claim.is_high_variance,
        "approved_amount": claim.approved_amount,
        "paid_amount": claim.paid_amount,
        "is_readmission": claim.is_readmission,
        "is_fragmentation": claim.is_fragmentation,
        "pending_age_days": claim.pending_age_days,
        "needs_escalation": claim.needs_escalation,
        "coder": _m2o(claim.coder_id),
        "verifier": _m2o(claim.verifier_id),
        "batch": _m2o(claim.batch_id),
    }


def adjustment_row(adjustment):
    return {
        "id": adjustment.id,
        "name": adjustment.name,
        "claim": _m2o(adjustment.claim_id),
        "type": adjustment.type,
        "type_label": _label(adjustment, "type"),
        "amount": adjustment.amount,
        "reason": adjustment.reason,
        "state": adjustment.state,
        "state_label": _label(adjustment, "state"),
        "requires_management": adjustment.requires_management,
        "authorization_limit_applied": adjustment.authorization_limit_applied,
        "proposed_by": _m2o(adjustment.proposed_by_id),
        "authorized_by": _m2o(adjustment.authorized_by_id),
        "authorized_at": adjustment.authorized_at,
    }


def batch_brief(batch):
    return {
        "id": batch.id,
        "name": batch.name,
        "service_period": batch.service_period,
        "care_type": batch.care_type,
        "care_type_label": _label(batch, "care_type"),
        "batch_type": batch.batch_type,
        "batch_type_label": _label(batch, "batch_type"),
        "payer": _m2o(batch.payer_id),
        "claim_count": batch.claim_count,
        "amount_hospital": batch.amount_hospital,
        "amount_grouped": batch.amount_grouped,
        "fpk_no": batch.fpk_no,
        "ba_no": batch.ba_no,
        "ba_date": batch.ba_date,
        "state": batch.reconciliation_state,
        "state_label": _label(batch, "reconciliation_state"),
        "submitted_at": batch.submitted_at,
        "submitted_by": _m2o(batch.submitted_by_id),
        "note": batch.note,
    }


def code_row(code):
    return {
        "id": code.id,
        "kind": code.kind,
        "kind_label": _label(code, "kind"),
        "code": code.code_display,
        "title": _icd10_title(code.icd10_id) if code.kind == "icd10" else (code.icd9_id.name or None),
        "icd10_id": code.icd10_id.id or None,
        "icd9_id": code.icd9_id.id or None,
        "role": code.role,
        "role_label": _label(code, "role"),
        "seq": code.seq,
        "changed_by_coder": code.changed_by_coder,
        "change_reason": code.change_reason,
        "source_diagnosis_id": code.source_diagnosis_id.id or None,
        "source_procedure_id": code.source_procedure_id.id or None,
        "note": code.note,
    }


class HmsCasemixController(http.Controller):

    # ------------------------------------------------------------------
    # Worklist
    # ------------------------------------------------------------------
    @http.route(f"{API_ROOT}/casemix/claims", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/casemix/claims")
    def claims(self, body=None, **kw):
        domain = []
        if kw.get("state"):
            domain.append(("state", "in", kw["state"].split(",")))
        if kw.get("kind"):
            domain.append(("kind", "=", kw["kind"]))
        if kw.get("payer_id"):
            domain.append(("payer_id", "=", int(kw["payer_id"])))
        if kw.get("care_type"):
            domain.append(("care_type", "=", kw["care_type"]))
        if kw.get("q"):
            term = kw["q"]
            domain += ["|", "|",
                       ("name", "ilike", term),
                       ("patient_id.name", "ilike", term),
                       ("patient_id.mrn", "ilike", term)]
        claims = request.env["hms.claim"].search(domain)
        page = paginate([claim_brief(c) for c in claims],
                        kw.get("page"), kw.get("page_size"))
        page["expiring_soon"] = sum(1 for row in page["items"] if row["expiring_soon"])
        return page

    # ------------------------------------------------------------------
    # Detail / panel koding
    # ------------------------------------------------------------------
    @http.route(f"{API_ROOT}/casemix/claims/<int:claim_id>", type="http", auth="public",
                methods=["GET"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/casemix/claims/<id>")
    def claim_detail(self, claim_id, body=None, **kw):
        claim = request.env["hms.claim"].browse(claim_id)
        if not claim.exists():
            return error_response("not_found", _("Klaim tidak ditemukan."), 404)
        encounter = claim.encounter_id
        summary = request.env["hms.summary"].search(
            [("encounter_id", "=", encounter.id)], order="id desc", limit=1
        )
        data = claim_brief(claim)
        data.update({
            "sep": _m2o(claim.sep_id),
            "cob_payer": _m2o(claim.cob_payer_id),
            "review_note": claim.review_note,
            "correction_note": claim.correction_note,
            "pending_reason": claim.pending_reason,
            "pending_category": claim.pending_category,
            "pending_category_label": _label(claim, "pending_category"),
            "rejection_reason": claim.rejection_reason,
            "dispute_level": claim.dispute_level,
            "readmission_reason": claim.readmission_reason,
            "readmission_source": _m2o(claim.readmission_source_id),
            "fragmentation_note": claim.fragmentation_note,
            "submission_count": claim.submission_count,
            "adjustment_total": claim.adjustment_total,
            "available_actions": [
                a for a in CLAIM_ACTIONS if a not in ("run_pregrouping", "refresh_hospital_bill")
            ],
            "codes": [code_row(c) for c in claim.code_ids],
            # Diagnosis & tindakan DOKTER, tampil berdampingan dengan kode
            # klaim. Baca saja: koding tidak pernah menulis ke hms.diagnosis.
            "clinical_diagnoses": [{
                "id": d.id,
                "icd10_id": d.icd10_id.id,
                "code": d.icd10_id.code,
                "title": _icd10_title(d.icd10_id),
                "rank": d.rank,
                "rank_label": _label(d, "rank"),
                "stage": d.stage,
                "stage_label": _label(d, "stage"),
                "practitioner": _m2o(d.practitioner_id),
                "note": d.note,
            } for d in encounter.diagnosis_ids],
            "clinical_procedures": [{
                "id": p.id,
                "icd9_id": p.icd9_id.id or None,
                "code": p.icd9_id.code or None,
                "name": p.name,
                "performed_at": p.performed_at,
                "practitioner": _m2o(p.practitioner_id),
            } for p in encounter.procedure_ids],
            "summary": {
                "id": summary.id,
                "type": summary.type,
                "state": summary.state,
                "chief_complaint": summary.chief_complaint,
                "history": summary.history,
                "physical_exam": summary.physical_exam,
                "lab_summary": summary.lab_summary,
                "procedure_summary": summary.procedure_summary,
                "treatment": summary.treatment,
                "condition_at_discharge": summary.condition_at_discharge,
            } if summary else None,
            "queries": [{
                "id": q.id,
                "name": q.name,
                "topic": q.topic,
                "topic_label": _label(q, "topic"),
                "question": q.question,
                "state": q.state,
                "state_label": _label(q, "state"),
                "answer": q.answer,
                "asked_at": q.asked_at,
                "answered_at": q.answered_at,
                "addressed_to": _m2o(q.addressed_to_id),
            } for q in claim.query_ids],
            "adjustments": [adjustment_row(a) for a in claim.adjustment_ids],
            # Riwayat state: kolom waktu yang memang disimpan model, bukan
            # log yang dikarang controller.
            "history": [row for row in (
                {"state": "internal_review", "label": _("Selesai dikoding"),
                 "at": claim.coded_at, "by": claim.coder_id.display_name or None},
                {"state": "internal_verified", "label": _("Terverifikasi internal"),
                 "at": claim.verified_at, "by": claim.verifier_id.display_name or None},
                {"state": "finalized", "label": _("Difinalkan"),
                 "at": claim.finalized_at, "by": claim.finalized_by_id.display_name or None},
                {"state": "submitted", "label": _("Diajukan"), "at": claim.submitted_at},
                {"state": "pending", "label": _("Dikembalikan penjamin"), "at": claim.pending_at},
                {"state": "dispute", "label": _("Dispute dibuka"), "at": claim.dispute_opened_at},
            ) if row.get("at")],
        })
        return {"claim": data}

    # ------------------------------------------------------------------
    # Transisi
    # ------------------------------------------------------------------
    @http.route(f"{API_ROOT}/casemix/claims/<int:claim_id>/<string:action>", type="http",
                auth="public", methods=["POST"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/casemix/claims/<id>/<action>", methods=("POST",))
    def claim_transition(self, claim_id, action, body=None, **kw):
        body = body or {}
        if action not in CLAIM_ACTIONS:
            return error_response("validation_error", _("Aksi klaim tidak dikenal."), 422)
        claim = request.env["hms.claim"].browse(claim_id)
        if not claim.exists():
            return error_response("not_found", _("Klaim tidak ditemukan."), 404)

        values = {k: v for k, v in (body.get("values") or {}).items() if k in CLAIM_WRITABLE}
        if values:
            claim.write(values)

        method = getattr(claim, f"action_{action}")
        if action in ("approve", "mark_paid") and body.get("amount") is not None:
            method(amount=float(body["amount"]))
        else:
            method()
        return {"claim": claim_brief(claim)}

    # ------------------------------------------------------------------
    # Kode klaim
    # ------------------------------------------------------------------
    @http.route(f"{API_ROOT}/casemix/claims/<int:claim_id>/codes", type="http", auth="public",
                methods=["GET"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/casemix/claims/<id>/codes")
    def claim_codes(self, claim_id, body=None, **kw):
        claim = request.env["hms.claim"].browse(claim_id)
        if not claim.exists():
            return error_response("not_found", _("Klaim tidak ditemukan."), 404)
        return {"items": [code_row(c) for c in claim.code_ids]}

    @http.route(f"{API_ROOT}/casemix/claims/<int:claim_id>/codes", type="http", auth="public",
                methods=["POST"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/casemix/claims/<id>/codes", methods=("POST",))
    def claim_codes_write(self, claim_id, body=None, **kw):
        body = body or {}
        claim = request.env["hms.claim"].browse(claim_id)
        if not claim.exists():
            return error_response("not_found", _("Klaim tidak ditemukan."), 404)
        Code = request.env["hms.claim.code"]

        remove = [int(i) for i in body.get("remove_ids") or []]
        if remove:
            # Hanya baris milik klaim ini; id lepas dari layar lain tidak
            # boleh ikut terhapus.
            Code.browse(remove).filtered(lambda c: c.claim_id == claim).unlink()

        for row in body.get("codes") or []:
            values = {k: row[k] for k in CODE_WRITABLE if k in row}
            for key in ("icd10_id", "icd9_id", "source_diagnosis_id", "source_procedure_id"):
                if key in values:
                    values[key] = int(values[key]) if values[key] else False
            if "seq" in values:
                values["seq"] = int(values["seq"] or 0)
            if row.get("id"):
                existing = Code.browse(int(row["id"]))
                if existing.claim_id != claim:
                    return error_response(
                        "validation_error", _("Kode ini bukan milik klaim tersebut."), 422
                    )
                existing.write(values)
            else:
                values["claim_id"] = claim.id
                Code.create(values)
        return {"items": [code_row(c) for c in claim.code_ids]}


class HmsClaimBatchController(http.Controller):
    """Batch pengajuan dan penyesuaian klaim.

    Sama seperti worklist klaim: tidak ada satu pun aturan bisnis di berkas
    ini. Kunci empat sumbu, syarat "semua klaim harus final", berita acara
    yang wajib sebelum rekonsiliasi, dan plafon otorisasi penyesuaian
    seluruhnya hidup di model — dan karena itu penolakannya sampai ke layar
    sebagai 400 `{"error": ...}` berisi kalimat Indonesia, bukan 500.
    """

    # ------------------------------------------------------------------
    # Daftar & detail batch
    # ------------------------------------------------------------------
    @http.route(f"{API_ROOT}/casemix/batches", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/casemix/batches")
    def batches(self, body=None, **kw):
        domain = []
        if kw.get("state"):
            domain.append(("reconciliation_state", "in", kw["state"].split(",")))
        if kw.get("care_type"):
            domain.append(("care_type", "=", kw["care_type"]))
        if kw.get("batch_type"):
            domain.append(("batch_type", "=", kw["batch_type"]))
        if kw.get("payer_id"):
            domain.append(("payer_id", "=", int(kw["payer_id"])))
        batches = request.env["hms.claim.batch"].search(domain)
        page = paginate([batch_brief(b) for b in batches],
                        kw.get("page"), kw.get("page_size"))
        page["draft_count"] = sum(1 for row in page["items"] if row["state"] == "draft")
        return page

    @http.route(f"{API_ROOT}/casemix/batches/<int:batch_id>", type="http", auth="public",
                methods=["GET"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/casemix/batches/<id>")
    def batch_detail(self, batch_id, body=None, **kw):
        batch = request.env["hms.claim.batch"].browse(batch_id)
        if not batch.exists():
            return error_response("not_found", _("Batch tidak ditemukan."), 404)
        data = batch_brief(batch)
        data.update({
            "claims": [claim_brief(c) for c in batch.claim_ids],
            "available_actions": list(BATCH_ACTIONS),
            # Klaim yang MASIH BISA masuk batch ini. Dihitung model, bukan
            # layar: syaratnya sama persis dengan yang dipakai penolakan,
            # sehingga daftar pilihan tidak pernah menawarkan sesuatu yang
            # kemudian ditolak.
            "candidates": [claim_brief(c) for c in batch.candidate_claims()],
        })
        return {"batch": data}

    @http.route(f"{API_ROOT}/casemix/batches", type="http", auth="public", methods=["POST"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/casemix/batches", methods=("POST",), idempotent=True)
    def batch_create(self, body=None, **kw):
        body = body or {}
        values = {k: body[k] for k in BATCH_KEY_FIELDS if body.get(k)}
        missing = [k for k in BATCH_KEY_FIELDS if not values.get(k)]
        if missing:
            return error_response(
                "validation_error",
                _("Kunci batch belum lengkap: %s.") % ", ".join(missing), 422,
            )
        values["payer_id"] = int(values["payer_id"])
        for key in BATCH_WRITABLE:
            if body.get(key):
                values[key] = body[key]
        batch = request.env["hms.claim.batch"].create(values)
        if body.get("collect"):
            batch.action_collect_claims()
        return {"batch": batch_brief(batch)}

    # ------------------------------------------------------------------
    # Transisi batch
    # ------------------------------------------------------------------
    @http.route(f"{API_ROOT}/casemix/batches/<int:batch_id>/<string:action>", type="http",
                auth="public", methods=["POST"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/casemix/batches/<id>/<action>", methods=("POST",))
    def batch_transition(self, batch_id, action, body=None, **kw):
        body = body or {}
        if action not in BATCH_ACTIONS:
            return error_response("validation_error", _("Aksi batch tidak dikenal."), 422)
        batch = request.env["hms.claim.batch"].browse(batch_id)
        if not batch.exists():
            return error_response("not_found", _("Batch tidak ditemukan."), 404)

        values = {k: v for k, v in (body.get("values") or {}).items() if k in BATCH_WRITABLE}
        if values:
            batch.write(values)

        method = getattr(batch, f"action_{action}")
        if action in ("add_claims", "remove_claims"):
            method([int(i) for i in body.get("claim_ids") or []])
        else:
            method()
        return {"batch": batch_brief(batch)}

    # ------------------------------------------------------------------
    # Penyesuaian klaim
    # ------------------------------------------------------------------
    @http.route(f"{API_ROOT}/casemix/adjustments", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/casemix/adjustments")
    def adjustments(self, body=None, **kw):
        domain = []
        if kw.get("state"):
            domain.append(("state", "in", kw["state"].split(",")))
        if kw.get("claim_id"):
            domain.append(("claim_id", "=", int(kw["claim_id"])))
        records = request.env["hms.claim.adjustment"].search(domain)
        return paginate([adjustment_row(a) for a in records],
                        kw.get("page"), kw.get("page_size"))

    @http.route(f"{API_ROOT}/casemix/claims/<int:claim_id>/adjustments", type="http",
                auth="public", methods=["POST"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/casemix/claims/<id>/adjustments", methods=("POST",),
               idempotent=True)
    def adjustment_create(self, claim_id, body=None, **kw):
        body = body or {}
        claim = request.env["hms.claim"].browse(claim_id)
        if not claim.exists():
            return error_response("not_found", _("Klaim tidak ditemukan."), 404)
        values = {k: body[k] for k in ADJUSTMENT_WRITABLE if body.get(k) is not None}
        if not values.get("reason"):
            return error_response(
                "validation_error",
                _("Alasan penyesuaian wajib diisi."), 422,
            )
        if values.get("amount") is not None:
            values["amount"] = float(values["amount"])
        adjustment = claim.action_issue_adjustment(values)
        return {"adjustment": adjustment_row(adjustment)}

    @http.route(f"{API_ROOT}/casemix/adjustments/<int:adjustment_id>/<string:action>",
                type="http", auth="public", methods=["POST"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/casemix/adjustments/<id>/<action>", methods=("POST",))
    def adjustment_transition(self, adjustment_id, action, body=None, **kw):
        if action not in ADJUSTMENT_ACTIONS:
            return error_response(
                "validation_error", _("Aksi penyesuaian tidak dikenal."), 422
            )
        adjustment = request.env["hms.claim.adjustment"].browse(adjustment_id)
        if not adjustment.exists():
            return error_response("not_found", _("Penyesuaian tidak ditemukan."), 404)
        getattr(adjustment, f"action_{action}")()
        return {"adjustment": adjustment_row(adjustment)}


class HmsCasemixReportController(http.Controller):

    @http.route(f"{API_ROOT}/reports/casemix-summary", type="http", auth="public",
                methods=["GET"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/reports/casemix-summary")
    def casemix_summary(self, body=None, **kw):
        claims = request.env["hms.claim"].search([])
        states = dict(request.env["hms.claim"]._fields["state"].selection)
        by_state = {}
        for claim in claims:
            row = by_state.setdefault(claim.state, {
                "state": claim.state,
                "label": states.get(claim.state),
                "count": 0,
                "hospital_bill_amount": 0.0,
                "approved_amount": 0.0,
            })
            row["count"] += 1
            row["hospital_bill_amount"] += claim.hospital_bill_amount
            row["approved_amount"] += claim.approved_amount

        # Piutang klaim: sudah keluar dari rumah sakit, belum ada uang masuk.
        outstanding = claims.filtered(lambda c: c.state in (
            "submitted", "bpjs_verifying", "approved", "pending", "resubmitted", "dispute",
        ))
        expiring = claims.filtered(
            lambda c: c.deadline_at and not c.is_expired
            and c.days_to_deadline <= EXPIRING_SOON_DAYS
            and c.state not in ("paid", "rejected", "expired")
        )
        expired = claims.filtered(lambda c: c.state == "expired")
        escalate = claims.filtered(lambda c: c.needs_escalation)
        return {
            "total": len(claims),
            "by_state": sorted(by_state.values(), key=lambda r: -r["count"]),
            "receivable": {
                "count": len(outstanding),
                "hospital_bill_amount": sum(outstanding.mapped("hospital_bill_amount")),
                "approved_amount": sum(outstanding.mapped("approved_amount")),
            },
            "expiring_soon": {
                "days": EXPIRING_SOON_DAYS,
                "count": len(expiring),
                "items": [{
                    "id": c.id, "name": c.name, "state": c.state,
                    "state_label": states.get(c.state),
                    "patient": c.patient_id.name,
                    "deadline_at": c.deadline_at,
                    "days_to_deadline": c.days_to_deadline,
                } for c in expiring[:20]],
            },
            "expired": {
                "count": len(expired),
                "hospital_bill_amount": sum(expired.mapped("hospital_bill_amount")),
            },
            "pending_escalation": len(escalate),
            "paid_amount": sum(claims.mapped("paid_amount")),
        }
