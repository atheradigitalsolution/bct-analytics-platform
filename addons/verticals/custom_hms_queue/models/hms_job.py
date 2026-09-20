# -*- coding: utf-8 -*-
"""Asynchronous job queue for outbound integrations."""
import json
import logging
import traceback

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Backoff ladder in minutes. Short enough that a transient BPJS hiccup clears
# within a patient's visit; long enough that a genuine outage is not hammered.
BACKOFF_MINUTES = (1, 5, 15, 60, 360)


class HmsJob(models.Model):
    _name = "hms.job"
    _description = "Job Integrasi"
    _order = "priority, next_run, id"

    name = fields.Char("Handler", required=True, index=True,
                       help="Nama handler terdaftar, mis. bpjs.sep.create.")
    model_name = fields.Char("Model Sumber")
    res_id = fields.Integer("ID Sumber")
    payload = fields.Text(default="{}")
    result = fields.Text("Hasil", readonly=True)
    state = fields.Selection(
        [("pending", "Menunggu"), ("running", "Berjalan"), ("done", "Selesai"),
         ("failed", "Gagal (akan diulang)"), ("dead", "Berhenti"), ("cancelled", "Dibatalkan")],
        default="pending", required=True, index=True,
    )
    attempts = fields.Integer(default=0)
    max_attempts = fields.Integer(default=5)
    next_run = fields.Datetime(default=fields.Datetime.now, index=True)
    last_error = fields.Text("Galat Terakhir", readonly=True)
    priority = fields.Integer(default=10, help="Angka kecil dikerjakan lebih dulu.")
    started_at = fields.Datetime(readonly=True)
    finished_at = fields.Datetime(readonly=True)
    duration_ms = fields.Integer("Durasi (ms)", readonly=True)
    log_ids = fields.One2many("hms.bridging.log", "job_id", "Log Panggilan")

    _runnable_idx = models.Index("(state, next_run) WHERE state IN ('pending', 'failed')")

    # --- handler registry -------------------------------------------------
    # Handlers register themselves by defining `_hms_job_handlers` on any
    # model. A dict rather than decorators so the mapping is inspectable at
    # runtime: an operator can ask which handler a job name resolves to.
    @api.model
    def _registry_map(self):
        mapping = {}
        for model_name in self.env.registry.models:
            model = self.env.get(model_name)
            if model is None:
                continue
            handlers = getattr(model, "_hms_job_handlers", None)
            if handlers:
                for job_name, method in handlers.items():
                    mapping[job_name] = (model_name, method)
        return mapping

    @api.model
    def enqueue(self, name, payload=None, model_name=None, res_id=None,
                priority=10, max_attempts=5, delay_minutes=0):
        """Queue a job. Never call an external API from a request thread."""
        run_at = fields.Datetime.now()
        if delay_minutes:
            run_at = fields.Datetime.add(run_at, minutes=delay_minutes)
        return self.sudo().create({
            "name": name,
            "payload": json.dumps(payload or {}, default=str),
            "model_name": model_name,
            "res_id": res_id,
            "priority": priority,
            "max_attempts": max_attempts,
            "next_run": run_at,
        })

    # --- execution --------------------------------------------------------
    @api.model
    def _claim(self, limit=20):
        """Take ownership of runnable jobs.

        `FOR UPDATE SKIP LOCKED` is what makes more than one worker safe: a row
        already locked by another worker is passed over instead of blocking.
        Without it, two workers would serialise behind the same job and a slow
        BPJS call would stall the whole queue.
        """
        self.env.cr.execute(
            """
            SELECT id FROM hms_job
             WHERE state IN ('pending', 'failed')
               AND next_run <= now() AT TIME ZONE 'UTC'
             ORDER BY priority, next_run, id
             LIMIT %s
               FOR UPDATE SKIP LOCKED
            """,
            (limit,),
        )
        ids = [row[0] for row in self.env.cr.fetchall()]
        if not ids:
            return self.browse()
        jobs = self.browse(ids)
        jobs.write({"state": "running", "started_at": fields.Datetime.now()})
        return jobs

    def _run_one(self):
        """Execute a single job in its own savepoint."""
        self.ensure_one()
        mapping = self._registry_map()
        entry = mapping.get(self.name)
        if not entry:
            self.write({
                "state": "dead",
                "last_error": _("Tidak ada handler terdaftar untuk '%s'.") % self.name,
                "finished_at": fields.Datetime.now(),
            })
            return False
        model_name, method_name = entry
        started = fields.Datetime.now()
        try:
            with self.env.cr.savepoint():
                handler = getattr(self.env[model_name].sudo(), method_name)
                result = handler(self, json.loads(self.payload or "{}"))
        except Exception as exc:  # noqa: BLE001 — every failure mode is retryable here
            _logger.warning("Job SIMRS %s (#%s) gagal: %s", self.name, self.id, exc)
            self._record_failure(exc)
            return False
        finished = fields.Datetime.now()
        self.write({
            "state": "done",
            "result": json.dumps(result, default=str) if result is not None else False,
            "finished_at": finished,
            "attempts": self.attempts + 1,
            "duration_ms": int((finished - started).total_seconds() * 1000),
            "last_error": False,
        })
        return True

    def _record_failure(self, exc):
        self.ensure_one()
        attempts = self.attempts + 1
        error = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        if attempts >= self.max_attempts:
            self.write({
                "state": "dead", "attempts": attempts, "last_error": error,
                "finished_at": fields.Datetime.now(),
            })
            self.env["hms.event"].sudo().emit("bridging.dead", {
                "job_id": self.id, "name": self.name, "error": error[:200],
            })
            return
        delay = BACKOFF_MINUTES[min(attempts - 1, len(BACKOFF_MINUTES) - 1)]
        self.write({
            "state": "failed",
            "attempts": attempts,
            "last_error": error,
            "next_run": fields.Datetime.add(fields.Datetime.now(), minutes=delay),
        })

    @api.model
    def _cron_run(self, limit=20):
        """Worker entry point. One cursor per job so one failure is contained."""
        jobs = self._claim(limit=limit)
        if not jobs:
            return 0
        self.env.cr.commit()  # release the claim locks before doing slow I/O
        done = 0
        for job in jobs:
            if job._run_one():
                done += 1
            self.env.cr.commit()
        self.env["ir.config_parameter"].sudo().set_param(
            "hms.jobs.last_run", fields.Datetime.to_string(fields.Datetime.now())
        )
        return done

    # --- manual operations ------------------------------------------------
    def action_retry(self):
        for job in self:
            if job.state not in ("failed", "dead", "cancelled"):
                raise UserError(
                    _("Job #%s sedang %s; hanya job gagal/berhenti yang dapat diulang.")
                    % (job.id, job.state)
                )
            job.write({"state": "pending", "next_run": fields.Datetime.now(), "last_error": False})
        return True

    def action_reset_attempts(self):
        self.write({"attempts": 0, "state": "pending", "next_run": fields.Datetime.now()})
        return True

    def action_cancel(self):
        for job in self:
            if job.state == "done":
                raise UserError(_("Job yang sudah selesai tidak dapat dibatalkan."))
            job.write({"state": "cancelled", "finished_at": fields.Datetime.now()})
        return True

    @api.model
    def _cron_unstick(self, minutes=30):
        """Return jobs stuck in `running` after a worker crash.

        A container killed mid-job leaves the row claimed forever. Nothing else
        notices, so the SEP simply never arrives and the desk blames BPJS.
        """
        cutoff = fields.Datetime.subtract(fields.Datetime.now(), minutes=minutes)
        stuck = self.sudo().search([("state", "=", "running"), ("started_at", "<", cutoff)])
        for job in stuck:
            job._record_failure(RuntimeError(
                _("Worker berhenti saat job berjalan; job dikembalikan ke antrian.")
            ))
        return len(stuck)
