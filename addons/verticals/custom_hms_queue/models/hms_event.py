# -*- coding: utf-8 -*-
"""Transactional outbox for realtime screens."""
import json
import logging
import os

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..tools.resp import RedisError, RespClient

_logger = logging.getLogger(__name__)


class HmsEvent(models.Model):
    _name = "hms.event"
    _description = "Event Keluar (Outbox)"
    _order = "id desc"

    topic = fields.Char(required=True, index=True)
    payload = fields.Text(required=True, default="{}")
    published = fields.Boolean(default=False, index=True)
    published_at = fields.Datetime("Dikirim Pada")
    attempts = fields.Integer(default=0)
    last_error = fields.Char("Galat Terakhir")

    _pending_idx = models.Index("(published, id) WHERE published IS NOT TRUE")

    # --- configuration ----------------------------------------------------
    @api.model
    def _redis_settings(self):
        """Read connection settings from the environment.

        Secrets never live in the database on this platform, so the password
        comes from the process environment. Host and port fall back to the
        compose service name, which is what every other service here uses.
        """
        return {
            "host": os.environ.get("HMS_REDIS_HOST", "redis"),
            "port": os.environ.get("HMS_REDIS_PORT", "6379"),
            "password": os.environ.get("HMS_REDIS_PASSWORD") or None,
            "db": os.environ.get("HMS_REDIS_DB", "3"),
        }

    @api.model
    def _channel(self, topic):
        """Namespace channels by database so tenants never cross-talk.

        The Next.js layer subscribes with the same prefix; changing this
        without changing the subscriber silently produces dead screens that
        look connected.
        """
        return "hms:%s:%s" % (self.env.cr.dbname, topic)

    # --- emitting ---------------------------------------------------------
    @api.model
    def emit(self, topic, payload):
        """Write an event and schedule its publication after commit.

        Called inside the business transaction. If that transaction rolls
        back, the row disappears with it and nothing is published — which is
        the entire reason the outbox exists.
        """
        if not isinstance(payload, str):
            payload = json.dumps(payload, default=str)
        event = self.sudo().create({"topic": topic, "payload": payload})
        self.env.cr.postcommit.add(lambda: event._publish_after_commit())
        return event

    def _publish_after_commit(self):
        """Publish in a fresh cursor; the original one is already committed."""
        with self.pool.cursor() as cr:
            env = self.env(cr=cr)
            env["hms.event"].browse(self.ids)._publish_batch()

    def _publish_batch(self):
        """Push every unpublished event in `self` to Redis.

        Failures are recorded, not raised: a dead Redis must not take down
        patient registration. The retry cron picks the rows up again.
        """
        pending = self.filtered(lambda e: not e.published)
        if not pending:
            return 0
        settings = self._redis_settings()
        sent = 0
        try:
            with RespClient(**settings) as client:
                for event in pending:
                    try:
                        client.publish(self._channel(event.topic), event.payload)
                    except RedisError as exc:
                        event.sudo().write({
                            "attempts": event.attempts + 1, "last_error": str(exc)[:200],
                        })
                        continue
                    event.sudo().write({
                        "published": True,
                        "published_at": fields.Datetime.now(),
                        "attempts": event.attempts + 1,
                        "last_error": False,
                    })
                    sent += 1
        except (OSError, RedisError) as exc:
            _logger.warning("Outbox SIMRS tidak dapat menghubungi Redis: %s", exc)
            pending.sudo().write({
                "attempts": 0, "last_error": str(exc)[:200],
            })
            # attempts is deliberately not incremented for a connection-level
            # failure: the events were never offered to Redis, so counting them
            # as attempts would retire healthy events during an outage.
            return 0
        return sent

    @api.model
    def _cron_publish_pending(self, limit=500):
        """Safety net for events the post-commit hook could not deliver."""
        pending = self.sudo().search([("published", "=", False)], order="id", limit=limit)
        if not pending:
            return 0
        sent = pending._publish_batch()
        self.env["ir.config_parameter"].sudo().set_param(
            "hms.outbox.last_run", fields.Datetime.to_string(fields.Datetime.now())
        )
        return sent

    @api.model
    def _cron_gc(self, keep_days=7):
        """Published events are a debugging aid, not a record; expire them."""
        cutoff = fields.Datetime.subtract(fields.Datetime.now(), days=keep_days)
        old = self.sudo().search([("published", "=", True), ("published_at", "<", cutoff)])
        count = len(old)
        old.unlink()
        return count

    def action_retry(self):
        """Manual retry from the list view."""
        self.sudo().write({"published": False})
        sent = self._publish_batch()
        if not sent:
            raise UserError(_("Tidak ada event yang berhasil dikirim. Periksa koneksi Redis."))
        return True

    @api.model
    def action_test_connection(self):
        settings = self._redis_settings()
        try:
            with RespClient(**settings) as client:
                client.ping()
        except (OSError, RedisError) as exc:
            raise UserError(
                _("Gagal menghubungi Redis di %(host)s:%(port)s — %(err)s")
                % {"host": settings["host"], "port": settings["port"], "err": exc}
            ) from exc
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Redis terhubung"),
                "message": _("PING dijawab oleh %(host)s:%(port)s (db %(db)s).") % settings,
                "type": "success",
            },
        }
