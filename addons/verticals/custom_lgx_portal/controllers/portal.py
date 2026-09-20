# -*- coding: utf-8 -*-
"""Endpoint portal dan pelacakan publik.

DUA LAPIS PENYARINGAN, BUKAN SATU
---------------------------------
Controller menyaring milestone dan dokumen ke yang `is_customer_visible`, DAN
record rule menyaringnya lagi di ORM. Template QWeb adalah tempat orang
menambahkan `t-foreach` baru tanpa memikirkan siapa yang membacanya; lapis kedua
membuat satu baris ceroboh di sana tidak cukup untuk membocorkan milestone
internal ke layar pelanggan.
"""
import logging

from odoo import _, http
from odoo.exceptions import AccessError, MissingError
from odoo.http import request

from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager

_logger = logging.getLogger(__name__)


class LgxCustomerPortal(CustomerPortal):

    # --- ringkasan di beranda portal ---------------------------------------
    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if "lgx_job_count" in counters:
            values["lgx_job_count"] = request.env["lgx.job"].search_count(
                self._lgx_job_domain())
        return values

    def _lgx_job_domain(self):
        """Domain job milik pemanggil.

        Memakai `commercial_partner_id`: kontak cabang dan kontak pribadi di
        bawah satu perusahaan harus melihat job perusahaannya, bukan hanya job
        yang kebetulan mencantumkan dirinya.
        """
        partner = request.env.user.partner_id.commercial_partner_id
        return [("customer_id", "=", partner.id), ("state", "!=", "cancelled")]

    # --- daftar job --------------------------------------------------------
    @http.route(["/my/logistik", "/my/logistik/page/<int:page>"],
                type="http", auth="user", website=True)
    def lgx_portal_jobs(self, page=1, sortby="date", **kwargs):
        Job = request.env["lgx.job"]
        domain = self._lgx_job_domain()
        sortings = {
            "date": {"label": _("ETD terbaru"), "order": "etd desc, id desc"},
            "name": {"label": _("Nomor job"), "order": "name desc"},
            "state": {"label": _("Status"), "order": "state, etd desc"},
        }
        order = sortings.get(sortby, sortings["date"])["order"]
        total = Job.search_count(domain)
        pager = portal_pager(
            url="/my/logistik", total=total, page=page, step=self._items_per_page,
            url_args={"sortby": sortby},
        )
        jobs = Job.search(domain, order=order, limit=self._items_per_page,
                          offset=pager["offset"])
        return request.render("custom_lgx_portal.portal_my_jobs", {
            "jobs": jobs,
            "page_name": "lgx_job",
            "pager": pager,
            "sortby": sortby,
            "searchbar_sortings": sortings,
            "default_url": "/my/logistik",
        })

    # --- detail job --------------------------------------------------------
    @http.route(["/my/logistik/job/<int:job_id>"], type="http", auth="public", website=True)
    def lgx_portal_job_detail(self, job_id, access_token=None, **kwargs):
        try:
            job = self._document_check_access("lgx.job", job_id, access_token)
        except (AccessError, MissingError):
            return request.redirect("/my")
        return request.render("custom_lgx_portal.portal_job_detail",
                              self._lgx_job_values(job, access_token))

    def _lgx_job_values(self, job, access_token=None, public=False):
        """Nilai template. Penyaringan terjadi DI SINI, bukan di template."""
        return {
            "job": job,
            "milestones": job.sudo().milestone_ids.filtered(
                lambda m: m.is_customer_visible and m.actual_date
            ).sorted("actual_date"),
            "pending_milestones": job.sudo().milestone_ids.filtered(
                lambda m: m.is_customer_visible and not m.actual_date
            ).sorted(lambda m: (m.sequence, m.id)),
            "documents": job.sudo().document_ids.filtered("is_customer_visible"),
            "containers": job.sudo().container_ids if "container_ids" in job._fields else [],
            "shipments": job.sudo().shipment_ids if "shipment_ids" in job._fields else [],
            "access_token": access_token,
            "public": public,
            "page_name": "lgx_job",
        }

    # --- unduh dokumen, TERCATAT -------------------------------------------
    @http.route(["/my/logistik/dokumen/<int:document_id>"], type="http", auth="public", website=True)
    def lgx_portal_document_download(self, document_id, access_token=None, **kwargs):
        document = request.env["lgx.document"].sudo().browse(document_id).exists()
        if not document or not document.is_customer_visible:
            # Dokumen internal dijawab sama dengan dokumen yang tidak ada.
            # Membedakannya berarti memberi tahu bahwa dokumen itu memang ada.
            return request.not_found()
        job = document.job_id
        if not job:
            return request.not_found()
        allowed = False
        if access_token:
            allowed = bool(request.env["lgx.job"].lgx_resolve_track_token(job.id, access_token))
            source = "public_link"
        if not allowed and not request.env.user._is_public():
            partner = request.env.user.partner_id.commercial_partner_id
            allowed = job.customer_id == partner
            source = "portal"
        if not allowed:
            return request.not_found()

        attachment = document.attachment_ids[:1]
        if not attachment:
            return request.not_found()
        document.lgx_log_download(
            partner=request.env.user.partner_id,
            source=source,
            remote_addr=request.httprequest.headers.get(
                "X-Forwarded-For", request.httprequest.remote_addr),
        )
        return request.env["ir.binary"]._get_stream_from(
            attachment.sudo(), "datas", filename=attachment.name,
        ).get_response(as_attachment=True)

    # --- pelacakan publik ---------------------------------------------------
    @http.route(["/lgx/lacak"], type="http", auth="public", website=True, methods=["GET", "POST"],
                csrf=True)
    def lgx_public_track_form(self, reference=None, **kwargs):
        """Pencarian publik dengan nomor referensi.

        Menerima nomor job, B/L, kontainer, atau referensi pelanggan. Yang
        ditampilkan HANYA ringkasan — tanpa dokumen, tanpa nilai. Nomor B/L
        beredar luas di rantai pasok; ia tidak boleh menjadi kunci ke dokumen.
        """
        result = None
        error = None
        if reference:
            job = self._lgx_find_by_reference(reference.strip())
            if job:
                result = self._lgx_job_values(job, public=True)
            else:
                error = _("Referensi '%s' tidak ditemukan.", reference)
        return request.render("custom_lgx_portal.public_track_page", {
            "reference": reference, "result": result, "error": error,
            "page_name": "lgx_track",
        })

    @http.route(["/lgx/lacak/<int:job_id>/<string:token>"], type="http", auth="public", website=True)
    def lgx_public_track_link(self, job_id, token, **kwargs):
        """Tautan bertanda tangan yang kedaluwarsa. Ini yang membuka DOKUMEN."""
        job = request.env["lgx.job"].lgx_resolve_track_token(job_id, token)
        if not job:
            return request.render("custom_lgx_portal.public_track_expired", {
                "page_name": "lgx_track",
            })
        values = self._lgx_job_values(job, access_token=token, public=True)
        return request.render("custom_lgx_portal.portal_job_detail", values)

    def _lgx_find_by_reference(self, reference):
        Job = request.env["lgx.job"].sudo()
        job = Job.search([("name", "=", reference)], limit=1)
        if not job:
            job = Job.search([("customer_reference", "=", reference)], limit=1)
        if not job:
            shipment = request.env["lgx.shipment"].sudo().search([
                "|", ("master_doc_no", "=", reference), ("house_doc_no", "=", reference),
            ], limit=1)
            job = shipment.job_id
        if not job:
            container = request.env["lgx.container"].sudo().search(
                [("container_no", "=", reference.upper())], limit=1)
            job = container.job_id
        return job

    # --- booking ------------------------------------------------------------
    @http.route(["/my/logistik/booking"], type="http", auth="user", website=True,
                methods=["GET", "POST"], csrf=True)
    def lgx_portal_booking(self, **post):
        Location = request.env["lgx.location"].sudo()
        if request.httprequest.method == "POST":
            partner = request.env.user.partner_id
            job = request.env["lgx.job"].lgx_create_portal_booking(partner, {
                "job_type": post.get("job_type"),
                "transport_mode": post.get("transport_mode"),
                "origin_id": int(post["origin_id"]) if post.get("origin_id") else False,
                "destination_id": int(post["destination_id"]) if post.get("destination_id") else False,
                "etd": post.get("etd") or False,
                "customer_reference": post.get("customer_reference"),
                "note": post.get("note"),
            })
            return request.render("custom_lgx_portal.portal_booking_done", {
                "job": job, "page_name": "lgx_booking",
            })
        return request.render("custom_lgx_portal.portal_booking_form", {
            "locations": Location.search([], order="country_id, code"),
            "page_name": "lgx_booking",
        })
