# -*- coding: utf-8 -*-
"""Append-only access log for medical records."""
from odoo import _, api, fields, models
from odoo.exceptions import AccessError


class HmsAccessLog(models.Model):
    _name = "hms.access.log"
    _description = "Log Akses Rekam Medis"
    # `id desc`, not `create_date desc`: _log_access = False removes the
    # create_date column entirely, so ordering by it makes every search on this
    # model raise. Unit tests miss this because TransactionCase runs as
    # superuser and the mixin deliberately skips superuser access.
    _order = "id desc"
    _log_access = False

    user_id = fields.Many2one("res.users", "Pengguna", required=True, index=True, ondelete="restrict")
    patient_id = fields.Many2one("hms.patient", "Pasien", index=True, ondelete="restrict")
    # `encounter_id` is added by custom_hms_registration, which is the module
    # that introduces hms.encounter. hms_audit sits below it in the graph and
    # must stay installable on its own.
    model_name = fields.Char("Model", required=True, index=True)
    res_id = fields.Integer("ID Record")
    action = fields.Selection(
        [("read", "Baca"), ("write", "Ubah"), ("create", "Buat"), ("unlink", "Hapus"),
         ("print", "Cetak"), ("export", "Ekspor")],
        required=True, index=True,
    )
    access_date = fields.Date("Tanggal", required=True, index=True,
                              default=lambda s: fields.Date.context_today(s))
    hit_count = fields.Integer("Jumlah Akses", default=1)
    first_at = fields.Datetime("Pertama", default=fields.Datetime.now)
    last_at = fields.Datetime("Terakhir", default=fields.Datetime.now)
    ip_address = fields.Char("Alamat IP")
    user_agent = fields.Char("Perangkat")
    was_in_care_team = fields.Boolean(
        "Bagian dari tim perawatan",
        help="False berarti akses dilakukan lewat hak akses penuh, bukan karena "
             "pengguna merawat pasien ini. Baris seperti ini yang ditinjau lebih dulu "
             "saat ada dugaan penyalahgunaan.",
    )

    _access_key = models.Index("(user_id, patient_id, model_name, action, access_date)")

    def write(self, vals):
        raise AccessError(_("Log akses rekam medis tidak dapat diubah."))

    def unlink(self):
        # The retention cron calls _gc_expired(), which bypasses this guard on
        # purpose. Everything else — including an administrator at a shell —
        # is refused, because a deletable audit trail is not an audit trail.
        if not self.env.context.get("hms_audit_gc"):
            raise AccessError(_("Log akses rekam medis tidak dapat dihapus."))
        return super().unlink()

    @api.model
    def _gc_expired(self, retention_days=1825):
        """Delete entries older than the retention window (default five years)."""
        cutoff = fields.Date.subtract(fields.Date.context_today(self), days=retention_days)
        expired = self.sudo().search([("access_date", "<", cutoff)])
        count = len(expired)
        expired.with_context(hms_audit_gc=True).unlink()
        return count
