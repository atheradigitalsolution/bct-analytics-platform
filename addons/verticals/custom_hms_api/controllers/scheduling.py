# -*- coding: utf-8 -*-
"""Rencana kontrol dan papan tindakan — sisi rumah sakit dari penjadwalan.

KENAPA DUA ENTITAS INI DILAYANI SATU BERKAS
-------------------------------------------
Keduanya milik ``custom_hms_scheduling`` dan keduanya menjawab pertanyaan
yang sama bentuknya: "apa yang seharusnya terjadi, kapan, dan apa yang
sebenarnya terjadi". Memisahkannya jadi dua berkas hanya akan menduplikasi
penyaring tanggal/state yang identik.

APA YANG TIDAK ADA DI SINI, DAN KENAPA
--------------------------------------
* **Tidak ada POST untuk MEMBUAT rencana kontrol.** Rencana lahir dari
  ``hms.summary.action_finalize()``; membuat jalur kedua lewat REST berarti
  rencana yang tidak punya resume sumber dan karena itu tidak pernah muncul
  di analisis KLPCM. Pembuatan langsung tetap mungkin di backend Odoo untuk
  kasus meja pendaftaran, sesuai desain modelnya.
* **Tidak ada POST untuk MEMBUAT jadwal tindakan.** Jadwal lahir dari
  ``hms.order.line.action_order()`` ketika dokter mengisi ``scheduled_at``.
  Papan operasi yang bisa diisi tanpa order adalah papan yang tidak tersambung
  ke tagihan maupun ke kewenangan klinis.
* **``bpjs_control_no`` tidak pernah diisi dari sini.** Ia diterbitkan VClaim
  BPJS. Yang dikirim ke layar adalah ``bpjs_control_status`` supaya kolom
  kosong itu terbaca sebagai "menunggu integrasi", bukan sebagai data yang
  lupa diisi petugas.

Penjaga bisnis tidak diulang di sini: ``action_postpone`` menolak penundaan
tanpa alasan, dan ``@api.constrains`` menolaknya sekali lagi pada jalur
``write``. ``UserError``/``ValidationError`` yang naik dari model diubah
``hms_route`` menjadi 400/422 beramplop ``{"error": {...}}``, jadi menangkap
ulang di sini hanya akan menyembunyikan pesannya.
"""
from odoo import _, http
from odoo.http import request

from .base import API_ROOT, error_response, hms_route, paginate

# Aksi yang dipetakan eksplisit, bukan getattr(f"action_{action}"): nama
# metode model dan kata kerja HTTP memang berbeda (``missed`` ->
# ``action_mark_missed``), dan pemetaan bebas membuat setiap metode yang
# kebetulan berawalan ``action_`` bisa dipanggil dari jaringan.
FOLLOWUP_ACTIONS = ("schedule", "fulfill", "missed", "cancel")
PROCEDURE_ACTIONS = ("confirm", "start", "done", "postpone", "cancel")


def _label(record, field_name):
    value = record[field_name]
    if not value:
        return None
    return dict(record._fields[field_name].selection).get(value)


def _m2o(record):
    return {"id": record.id, "name": record.display_name} if record else None


def _patient(patient):
    if not patient:
        return None
    return {"id": patient.id, "name": patient.name, "mrn": patient.mrn}


def followup_row(plan):
    return {
        "id": plan.id,
        "patient": _patient(plan.patient_id),
        "encounter": {
            "id": plan.encounter_id.id,
            "name": plan.encounter_id.name,
            "type": plan.encounter_id.type,
        },
        "summary_id": plan.summary_id.id or None,
        "practitioner": _m2o(plan.practitioner_id),
        "unit": _m2o(plan.unit_id),
        "planned_date": plan.planned_date,
        "kind": plan.kind,
        "kind_label": _label(plan, "kind"),
        "instruction": plan.instruction or None,
        "state": plan.state,
        "state_label": _label(plan, "state"),
        "slot_id": plan.slot_id.id or None,
        "fulfilled_encounter_id": plan.fulfilled_encounter_id.id or None,
        "fulfilled_at": plan.fulfilled_at or None,
        "days_late": plan.days_late,
        "cancel_reason": plan.cancel_reason or None,
        "bpjs_control_no": plan.bpjs_control_no or None,
        # Kolom kosong tanpa penjelasan terbaca sebagai kelalaian petugas.
        # Statusnya dikirim supaya layar bisa mengatakan yang sebenarnya.
        "bpjs_control_status": (
            "terbit" if plan.bpjs_control_no else "menunggu integrasi VClaim"
        ),
    }


def procedure_row(schedule):
    return {
        "id": schedule.id,
        "name": schedule.name,
        "patient": _patient(schedule.patient_id),
        "encounter": {
            "id": schedule.encounter_id.id,
            "name": schedule.encounter_id.name,
            "type": schedule.encounter_id.type,
        },
        "order_line_id": schedule.order_line_id.id,
        "order_name": schedule.order_id.name,
        "practitioner": _m2o(schedule.practitioner_id),
        "unit": _m2o(schedule.unit_id),
        "room": _m2o(schedule.room_id),
        "planned_start": schedule.planned_start or None,
        "planned_end": schedule.planned_end or None,
        "original_planned_start": schedule.original_planned_start or None,
        "actual_start": schedule.actual_start or None,
        "actual_end": schedule.actual_end or None,
        "duration_minutes": schedule.duration_minutes,
        "is_elective": schedule.is_elective,
        "state": schedule.state,
        "state_label": _label(schedule, "state"),
        "postpone_reason": schedule.postpone_reason,
        "postpone_reason_label": _label(schedule, "postpone_reason"),
        "postpone_note": schedule.postpone_note or None,
        "postpone_count": schedule.postpone_count,
        "postponed_at": schedule.postponed_at or None,
        "cancel_reason": schedule.cancel_reason or None,
        "team_count": len(schedule.team_ids),
        "note": schedule.note or None,
    }


# --- alias nama pada arah tulis ---------------------------------------------
# Respons GET memaparkan `postpone_reason`, `postpone_note` dan `cancel_reason`;
# aksi POST dulu hanya membaca `reason` dan `note`. Mengirim kembali nama yang
# baru saja dibaca karena itu **berhasil dengan 400** — "alasan penundaan wajib
# diisi" — seolah petugasnya yang tidak mengisi. Kekeliruan itu tidak pernah
# menghasilkan galat yang menunjuk penyebabnya, hanya penundaan yang tidak
# tercatat, dan penundaan yang tidak tercatat membuat indikator mutu selalu
# terlihat sempurna.
#
# Ini ALIAS, bukan perubahan kontrak: ejaan lama tetap menang bila keduanya
# dikirim, sehingga klien yang sudah beredar tidak berubah perilakunya.
def _alias(body, *names):
    for name in names:
        value = body.get(name)
        if value:
            return value
    return None


def _postpone_reasons(env):
    field = env["hms.procedure.schedule"]._fields["postpone_reason"]
    return [{"value": value, "label": label} for value, label in field.selection]


class HmsSchedulingController(http.Controller):

    # --- rencana kontrol ---------------------------------------------------
    @http.route(f"{API_ROOT}/followup-plans", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/followup-plans")
    def followup_plans(self, body=None, **kw):
        domain = []
        # `state` kosong = semua. Daftar kerja rencana kontrol harus bisa
        # memperlihatkan yang TIDAK DATANG juga — itulah barisnya yang
        # menuntut tindakan, dan menyembunyikannya di balik filter default
        # membuat daftar ini kehilangan gunanya.
        if kw.get("state") and kw["state"] != "all":
            domain.append(("state", "in", kw["state"].split(",")))
        if kw.get("patient_id"):
            domain.append(("patient_id", "=", int(kw["patient_id"])))
        if kw.get("encounter_id"):
            domain.append(("encounter_id", "=", int(kw["encounter_id"])))
        if kw.get("unit_id"):
            domain.append(("unit_id", "=", int(kw["unit_id"])))
        if kw.get("practitioner_id"):
            domain.append(("practitioner_id", "=", int(kw["practitioner_id"])))
        if kw.get("kind"):
            domain.append(("kind", "=", kw["kind"]))
        if kw.get("date_from"):
            domain.append(("planned_date", ">=", kw["date_from"]))
        if kw.get("date_to"):
            domain.append(("planned_date", "<=", kw["date_to"]))
        if kw.get("q"):
            term = kw["q"]
            domain += ["|", "|",
                       ("patient_id.name", "ilike", term),
                       ("patient_id.mrn", "ilike", term),
                       ("encounter_id.name", "ilike", term)]
        plans = request.env["hms.followup.plan"].search(domain)
        page = paginate([followup_row(p) for p in plans],
                        kw.get("page"), kw.get("page_size"))
        page["counts"] = {
            state: sum(1 for p in plans if p.state == state)
            for state, _dummy in request.env["hms.followup.plan"]
            ._fields["state"].selection
        }
        return page

    @http.route(f"{API_ROOT}/encounters/<int:encounter_id>/followup-plans", type="http",
                auth="public", methods=["GET"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/encounters/<id>/followup-plans")
    def encounter_followup_plans(self, encounter_id, body=None, **kw):
        encounter = request.env["hms.encounter"].browse(encounter_id)
        if not encounter.exists():
            return error_response("not_found", _("Kunjungan tidak ditemukan."), 404)
        encounter.check_access("read")
        plans = request.env["hms.followup.plan"].search([
            ("encounter_id", "=", encounter.id),
        ])
        return {"items": [followup_row(p) for p in plans]}

    @http.route(f"{API_ROOT}/followup-plans/<int:plan_id>/<string:action>", type="http",
                auth="public", methods=["POST"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/followup-plans/<id>/<action>", methods=("POST",))
    def followup_transition(self, plan_id, action, body=None, **kw):
        body = body or {}
        if action not in FOLLOWUP_ACTIONS:
            return error_response("validation_error",
                                  _("Aksi rencana kontrol tidak dikenal."), 422)
        plan = request.env["hms.followup.plan"].browse(plan_id)
        if not plan.exists():
            return error_response("not_found", _("Rencana kontrol tidak ditemukan."), 404)
        if action == "schedule":
            slot = None
            if body.get("slot_id"):
                slot = request.env["hms.schedule.slot"].browse(int(body["slot_id"]))
                if not slot.exists():
                    return error_response("not_found", _("Slot jadwal tidak ditemukan."), 404)
            plan.action_schedule(slot=slot)
        elif action == "fulfill":
            if not body.get("encounter_id"):
                return error_response(
                    "validation_error",
                    _("Kunjungan pemenuhan wajib disebutkan."), 422,
                    {"encounter_id": _("wajib")},
                )
            encounter = request.env["hms.encounter"].browse(int(body["encounter_id"]))
            if not encounter.exists():
                return error_response("not_found", _("Kunjungan tidak ditemukan."), 404)
            plan.action_fulfill(encounter)
        elif action == "missed":
            plan.action_mark_missed()
        else:
            plan.action_cancel(reason=_alias(body, "reason", "cancel_reason"))
        return {"plan": followup_row(plan)}

    # --- papan tindakan ----------------------------------------------------
    @http.route(f"{API_ROOT}/procedure-schedules", type="http", auth="public",
                methods=["GET"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/procedure-schedules")
    def procedure_schedules(self, body=None, **kw):
        domain = []
        if kw.get("state") and kw["state"] != "all":
            domain.append(("state", "in", kw["state"].split(",")))
        if kw.get("unit_id"):
            domain.append(("unit_id", "=", int(kw["unit_id"])))
        if kw.get("room_id"):
            domain.append(("room_id", "=", int(kw["room_id"])))
        if kw.get("patient_id"):
            domain.append(("patient_id", "=", int(kw["patient_id"])))
        if kw.get("encounter_id"):
            domain.append(("encounter_id", "=", int(kw["encounter_id"])))
        if kw.get("elective") in ("1", "true", "yes"):
            domain.append(("is_elective", "=", True))
        if kw.get("date_from"):
            domain.append(("planned_start", ">=", kw["date_from"]))
        if kw.get("date_to"):
            domain.append(("planned_start", "<=", kw["date_to"]))
        if kw.get("q"):
            term = kw["q"]
            domain += ["|", "|",
                       ("name", "ilike", term),
                       ("patient_id.name", "ilike", term),
                       ("patient_id.mrn", "ilike", term)]
        schedules = request.env["hms.procedure.schedule"].search(domain)
        page = paginate([procedure_row(s) for s in schedules],
                        kw.get("page"), kw.get("page_size"))
        page["counts"] = {
            state: sum(1 for s in schedules if s.state == state)
            for state, _dummy in request.env["hms.procedure.schedule"]
            ._fields["state"].selection
        }
        # Alasan penundaan dikirim bersama daftarnya supaya layar tidak
        # mengetik ulang daftar Selection-nya. Daftar yang disalin ke JSX
        # akan menyimpang diam-diam begitu modelnya bertambah kategori, dan
        # penundaan yang tak terkelompokkan adalah tepat yang dicegah model.
        page["postpone_reasons"] = _postpone_reasons(request.env)
        return page

    @http.route(f"{API_ROOT}/procedure-schedules/<int:schedule_id>", type="http",
                auth="public", methods=["GET"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/procedure-schedules/<id>")
    def procedure_detail(self, schedule_id, body=None, **kw):
        schedule = request.env["hms.procedure.schedule"].browse(schedule_id)
        if not schedule.exists():
            return error_response("not_found", _("Jadwal tindakan tidak ditemukan."), 404)
        schedule.check_access("read")
        return {"schedule": procedure_row(schedule),
                "postpone_reasons": _postpone_reasons(request.env)}

    @http.route(f"{API_ROOT}/procedure-schedules/<int:schedule_id>/<string:action>",
                type="http", auth="public", methods=["POST"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/procedure-schedules/<id>/<action>", methods=("POST",))
    def procedure_transition(self, schedule_id, action, body=None, **kw):
        body = body or {}
        if action not in PROCEDURE_ACTIONS:
            return error_response("validation_error",
                                  _("Aksi jadwal tindakan tidak dikenal."), 422)
        schedule = request.env["hms.procedure.schedule"].browse(schedule_id)
        if not schedule.exists():
            return error_response("not_found", _("Jadwal tindakan tidak ditemukan."), 404)
        if action == "postpone":
            # Alasan TIDAK divalidasi di sini. Penjaganya ada di model dan
            # berlaku untuk semua jalur; menyalinnya ke controller berarti
            # dua kebenaran tentang apa yang wajib, dan yang di controller
            # akan ketinggalan.
            schedule.action_postpone(
                reason=_alias(body, "reason", "postpone_reason"),
                note=_alias(body, "note", "postpone_note"),
                new_start=body.get("new_start") or None,
            )
        elif action == "cancel":
            schedule.action_cancel(reason=_alias(body, "reason", "cancel_reason"))
        elif action == "confirm":
            schedule.action_confirm()
        elif action == "start":
            schedule.action_start()
        else:
            schedule.action_done()
        return {"schedule": procedure_row(schedule)}
