# -*- coding: utf-8 -*-
"""Endpoints the mobile screens post to.

Thin on purpose. Every rule these touch -- the approval gate, the portion arithmetic,
the over-estimate escalation -- lives in the models, because a mobile path that
reimplements business rules is a second set of rules to drift apart from the first.

Authentication rides on custom_core's ``secure_endpoint``, the same HMAC gate
``custom_hht_bridge`` uses for enrolled devices, so a workshop tablet authenticates as
a device rather than by someone typing a password with gloves on.
"""

from __future__ import annotations

import logging

from odoo import _, http
from odoo.http import request

from odoo.addons.custom_core.controllers.secure_endpoint import secure_endpoint

_logger = logging.getLogger(__name__)


def _ok(payload=None):
    return request.make_json_response({"ok": True, **(payload or {})})


def _fail(code, message, status=400):
    return request.make_json_response(
        {"ok": False, "error_code": code, "message": message}, status=status)


class SpkShopfloorController(http.Controller):

    @http.route("/api/spk/shopfloor/round", type="http", auth="none",
                methods=["POST"], csrf=False, save_session=False)
    @secure_endpoint("hht")
    def open_round(self, **_kw):
        """Open or resume the round for a date and shift.

        Idempotent by design: a device that retries after a dropped connection must not
        create a second round, because two rounds for one walk would split the
        supervisor's work in half and look like two incomplete ones.
        """
        data = request.get_json_data()
        date = data.get("date")
        shift_code = data.get("shift_code")
        if not date or not shift_code:
            return _fail("MISSING_FIELDS", "date and shift_code are required")
        shift = request.env["custom.spk.shift"].sudo().search(
            [("code", "=", shift_code)], limit=1)
        if not shift:
            return _fail("UNKNOWN_SHIFT", "no shift with code %s" % shift_code)
        rnd = request.env["custom.spk.shopfloor.round"].sudo().get_or_open(date, shift.id)
        return _ok({"round_id": rnd.id, "name": rnd.name, "state": rnd.state})

    @http.route("/api/spk/shopfloor/attendance", type="http", auth="none",
                methods=["POST"], csrf=False, save_session=False)
    @secure_endpoint("hht")
    def post_attendance(self, **_kw):
        """A whole round's attendance in one call.

        One call, not one per worker: the screen is a checklist and the network is bad.
        Sending twenty requests over a weak signal is twenty chances to fail halfway.
        """
        data = request.get_json_data()
        round_id = data.get("round_id")
        entries = data.get("entries") or []
        if not round_id or not entries:
            return _fail("MISSING_FIELDS", "round_id and entries are required")
        rnd = request.env["custom.spk.shopfloor.round"].sudo().browse(round_id)
        if not rnd.exists():
            return _fail("UNKNOWN_ROUND", "round %s does not exist" % round_id)

        Attendance = request.env["custom.spk.attendance"].sudo()
        created, skipped = [], []
        for entry in entries:
            employee_id = entry.get("employee_id")
            if not employee_id:
                continue
            # Idempotent per worker: the unique constraint already forbids a duplicate,
            # but reporting it as skipped is friendlier than a 500 on a retry.
            existing = Attendance.search([
                ("employee_id", "=", employee_id),
                ("date", "=", rnd.date),
                ("shift_id", "=", rnd.shift_id.id),
            ], limit=1)
            if existing:
                existing.shopfloor_round_id = rnd.id
                skipped.append(employee_id)
                continue
            created.append(Attendance.create({
                "employee_id": employee_id,
                "date": rnd.date,
                "shift_id": rnd.shift_id.id,
                "attendance_status": entry.get("status") or "hadir",
                "overtime_hours": entry.get("overtime_hours") or 0.0,
                "supervisor_id": rnd.supervisor_id.id,
                "shopfloor_round_id": rnd.id,
            }).id)
        return _ok({"created": created, "already_present": skipped,
                    "unmapped": rnd.unmapped_count})

    @http.route("/api/spk/shopfloor/worklog", type="http", auth="none",
                methods=["POST"], csrf=False, save_session=False)
    @secure_endpoint("hht")
    def post_worklog(self, **_kw):
        """Map a shift onto jobs. Replaces any previous mapping for that attendance.

        Replace rather than append, because a supervisor correcting a split expects the
        new numbers to be the answer, not to be added to the old ones.
        """
        data = request.get_json_data()
        attendance_id = data.get("attendance_id")
        allocations = data.get("allocations") or []
        if not attendance_id or not allocations:
            return _fail("MISSING_FIELDS", "attendance_id and allocations are required")
        attendance = request.env["custom.spk.attendance"].sudo().browse(attendance_id)
        if not attendance.exists():
            return _fail("UNKNOWN_ATTENDANCE", "attendance %s does not exist" % attendance_id)

        WorkLog = request.env["custom.spk.work.log"].sudo()
        attendance.work_log_ids.unlink()
        try:
            for alloc in allocations:
                WorkLog.create({
                    "attendance_id": attendance.id,
                    "target": alloc.get("target") or "spk",
                    "spk_id": alloc.get("spk_id") or False,
                    "shift_portion": alloc.get("portion") or 1.0,
                })
        except Exception as exc:  # noqa: BLE001 - surfaced to the device, not swallowed
            _logger.warning("shopfloor worklog rejected: %s", exc)
            return _fail("REJECTED", str(exc))
        return _ok({"portion_total": attendance.portion_total})

    @http.route("/api/spk/shopfloor/progress", type="http", auth="none",
                methods=["POST"], csrf=False, save_session=False)
    @secure_endpoint("hht")
    def post_progress(self, **_kw):
        """Progress on a job, with an optional photo link.

        The link is accepted, never the bytes. Photographs live outside the filestore
        here, and the upload URL is pre-signed at flush time by the device -- requesting
        it at enqueue time would hand the queue a URL that expires before the signal
        returns.
        """
        data = request.get_json_data()
        spk_id = data.get("spk_id")
        progress = data.get("progress")
        if not spk_id or progress is None:
            return _fail("MISSING_FIELDS", "spk_id and progress are required")
        spk = request.env["custom.spk"].sudo().browse(spk_id)
        if not spk.exists():
            return _fail("UNKNOWN_SPK", "SPK %s does not exist" % spk_id)
        try:
            progress = float(progress)
        except (TypeError, ValueError):
            return _fail("BAD_PROGRESS", "progress must be a number")
        if not 0.0 <= progress <= 100.0:
            return _fail("BAD_PROGRESS", "progress must be between 0 and 100")
        spk.progress = progress
        photo_url = data.get("photo_url")
        if photo_url:
            spk.message_post(body=_("Foto progres: %(url)s", url=photo_url))
        return _ok({"progress": spk.progress, "risk_level": spk.risk_level})

    @http.route("/api/spk/shopfloor/material", type="http", auth="none",
                methods=["POST"], csrf=False, save_session=False)
    @secure_endpoint("hht")
    def post_material_request(self, **_kw):
        """Raise a material request from the floor.

        Submitted, never approved: approval is the supervisor's act and the escalation
        rule lives in the model. An endpoint that approved its own request would be a
        way around the control that keeps overrun visible.
        """
        data = request.get_json_data()
        spk_id = data.get("spk_id")
        employee_id = data.get("employee_id")
        lines = data.get("lines") or []
        if not (spk_id and employee_id and lines):
            return _fail("MISSING_FIELDS", "spk_id, employee_id and lines are required")
        MR = request.env["custom.spk.material.request"].sudo()
        try:
            req = MR.create({
                "spk_id": spk_id,
                "requested_by": employee_id,
                "work_item": data.get("work_item") or "",
                "line_ids": [
                    (0, 0, {
                        "product_id": line.get("product_id"),
                        "qty_requested": line.get("qty") or 1.0,
                    }) for line in lines if line.get("product_id")
                ],
            })
            req.action_submit()
        except Exception as exc:  # noqa: BLE001
            _logger.warning("shopfloor material request rejected: %s", exc)
            return _fail("REJECTED", str(exc))
        return _ok({"request_id": req.id, "name": req.name,
                    "over_estimate": req.over_estimate})
