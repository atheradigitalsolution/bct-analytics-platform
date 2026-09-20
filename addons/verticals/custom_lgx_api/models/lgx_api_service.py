# -*- coding: utf-8 -*-
"""Fasad API: satu method per operasi lengkap, bukan model mentah.

KENAPA FASAD DAN BUKAN MODEL MENTAH
-----------------------------------
Setiap panggilan ``/json/2`` berjalan dalam transaksi SQL sendiri. Operasi yang
butuh empat panggilan berurutan — buat POD, unggah foto, isi nama penerima,
ubah status trip — akan meninggalkan data separuh jadi begitu panggilan ketiga
gagal karena sinyal putus. Aplikasi pengemudi bekerja di tempat sinyal memang
putus, jadi itu bukan kemungkinan teoretis.

Karena itu setiap method di sini menyelesaikan SATU operasi utuh, dan aman
diulang: mengirim POD yang sama dua kali menghasilkan keadaan yang sama, bukan
dua POD.

BENTUK RESPONS
--------------
Mengikuti konvensi ``custom_hms_api``: sukses mengembalikan data polos, galat
mengembalikan ``{"error": {"code", "message", "fields"}}``. Konvensi kedua di
repo yang sama berarti setiap frontend harus tahu sedang bicara dengan yang mana.
"""
import base64
import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

_logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1"


class LgxApiService(models.AbstractModel):
    _name = "lgx.api.service"
    _description = "Fasad API Logistik"

    # --- util --------------------------------------------------------------
    @api.model
    def _error(self, code, message, fields_=None):
        return {"error": {"code": code, "message": message, "fields": fields_ or {}}}

    @api.model
    def _ok(self, data):
        payload = {"schema": SCHEMA_VERSION}
        payload.update(data)
        return payload

    @api.model
    def _current_driver(self):
        driver = self.env["lgx.driver"].sudo().search(
            [("user_id", "=", self.env.uid)], limit=1)
        return driver

    # --- pelacakan pelanggan (LGX-G01) -------------------------------------
    @api.model
    def track_shipment(self, reference=None, **kwargs):
        """Lacak dengan nomor job, B/L, kontainer, atau referensi pelanggan.

        Hanya milestone ``is_customer_visible`` yang dikembalikan. Milestone
        internal — biaya vendor diterima, kontainer kena detensi — bukan urusan
        pelanggan dan tidak boleh bocor lewat endpoint yang dibuka ke publik.
        """
        reference = (reference or "").strip()
        if not reference:
            return self._error("missing_reference", _("Nomor referensi wajib diisi."))
        Job = self.env["lgx.job"].sudo()
        job = Job.search([("name", "=", reference)], limit=1)
        if not job:
            job = Job.search([("customer_reference", "=", reference)], limit=1)
        if not job:
            shipment = self.env["lgx.shipment"].sudo().search([
                "|", ("master_doc_no", "=", reference), ("house_doc_no", "=", reference),
            ], limit=1)
            job = shipment.job_id
        if not job:
            container = self.env["lgx.container"].sudo().search(
                [("container_no", "=", reference.upper())], limit=1)
            job = container.job_id
        if not job:
            return self._error("not_found", _("Referensi '%s' tidak ditemukan.", reference))

        milestones = job.milestone_ids.filtered(
            lambda m: m.is_customer_visible and m.actual_date
        ).sorted("actual_date")
        last_update = max(job.milestone_ids.mapped("write_date") or [job.write_date])
        return self._ok({
            "reference": job.name,
            "customer_reference": job.customer_reference or None,
            "status": job.state,
            "job_type": job.job_type,
            "origin": job.origin_location_id.display_name or None,
            "destination": job.destination_location_id.display_name or None,
            "etd": job.etd and str(job.etd) or None,
            "eta": job.eta and str(job.eta) or None,
            "ata": job.ata and str(job.ata) or None,
            "last_update": str(last_update),
            "milestones": [{
                "code": m.milestone_type_id.code,
                "name": m.milestone_type_id.name,
                "date": str(m.actual_date),
                "location": m.location_id.display_name or None,
                "source": m.source,
            } for m in milestones],
            "containers": [{
                "number": c.container_no,
                "type": c.container_type_id.code,
                "returned": c.is_returned,
            } for c in job.container_ids] if "container_ids" in job._fields else [],
        })

    @api.model
    def list_jobs(self, filters=None, limit=80, offset=0, **kwargs):
        """Daftar job yang boleh dilihat pemanggil.

        TIDAK memakai sudo: record rule yang menentukan apa yang terlihat, dan
        itu memang seharusnya. Endpoint yang mem-bypass rule adalah endpoint yang
        membocorkan data lintas cabang begitu ada satu pemanggil salah kunci.
        """
        filters = filters or {}
        domain = []
        if filters.get("state"):
            domain.append(("state", "in", filters["state"] if isinstance(filters["state"], list)
                           else [filters["state"]]))
        if filters.get("customer_id"):
            domain.append(("customer_id", "=", int(filters["customer_id"])))
        if filters.get("job_type"):
            domain.append(("job_type", "=", filters["job_type"]))
        if filters.get("date_from"):
            domain.append(("etd", ">=", filters["date_from"]))
        if filters.get("date_to"):
            domain.append(("etd", "<=", filters["date_to"]))
        jobs = self.env["lgx.job"].search(domain, limit=min(int(limit or 80), 200),
                                          offset=int(offset or 0), order="etd desc, id desc")
        return self._ok({
            "count": len(jobs),
            "jobs": [{
                "id": j.id,
                "name": j.name,
                "job_type": j.job_type,
                "customer": j.customer_id.display_name,
                "origin": j.origin_location_id.display_name or None,
                "destination": j.destination_location_id.display_name or None,
                "etd": j.etd and str(j.etd) or None,
                "eta": j.eta and str(j.eta) or None,
                "state": j.state,
                "margin_pct": round(j.margin_pct, 2),
            } for j in jobs],
        })

    # --- aplikasi pengemudi (LGX-D04) --------------------------------------
    @api.model
    def driver_trip_list(self, driver_id=None, **kwargs):
        """Trip milik pengemudi yang sedang login.

        ``driver_id`` dari klien DIABAIKAN bila pemanggil adalah pengemudi.
        Menerima id dari perangkat lapangan berarti perangkat yang hilang dapat
        membaca jadwal seluruh armada.
        """
        driver = self._current_driver()
        if not driver and driver_id and self.env.user.has_group(
                "custom_lgx_base.group_lgx_trucking_dispatcher"):
            driver = self.env["lgx.driver"].browse(int(driver_id))
        if not driver:
            return self._error("no_driver", _("Pengguna ini tidak terhubung ke data pengemudi."))
        trips = self.env["lgx.trip"].search([
            ("driver_id", "=", driver.id),
            ("state", "in", ("assigned", "dispatched", "in_transit")),
        ], order="planned_start")
        return self._ok({
            "driver": {"id": driver.id, "name": driver.name},
            "trips": [{
                "id": t.id,
                "name": t.name,
                "trip_type": t.trip_type,
                "vehicle": t.vehicle_id.display_name or None,
                "planned_start": t.planned_start and str(t.planned_start) or None,
                "state": t.state,
                "stops": [{
                    "id": s.id,
                    "type": s.stop_type,
                    "partner": s.partner_id.display_name or None,
                    "address": s.address or None,
                    "planned_arrival": s.planned_arrival and str(s.planned_arrival) or None,
                    "qty_planned": s.qty_planned,
                    "has_pod": s.has_pod,
                } for s in t.stop_ids.sorted("sequence")],
            } for t in trips],
        })

    @api.model
    def submit_pod(self, stop_id=None, signature=None, photos=None, received_by=None,
                   qty_delivered=None, qty_rejected=None, rejection_reason=None, **kwargs):
        """Kirim bukti terima untuk satu stop. Satu operasi, aman diulang.

        Unggahan yang gagal karena sinyal buruk dapat diulang tanpa kehilangan
        data: memanggil ulang dengan isi yang sama menghasilkan keadaan yang
        sama, bukan POD kedua.
        """
        if not stop_id:
            return self._error("missing_stop", _("stop_id wajib diisi."))
        stop = self.env["lgx.trip.stop"].browse(int(stop_id)).exists()
        if not stop:
            return self._error("not_found", _("Stop tidak ditemukan."))
        if not received_by:
            return self._error(
                "missing_receiver",
                _("Nama penerima wajib. Tanda tangan tanpa nama penerima adalah coretan; "
                  "yang menagih adalah keduanya sekaligus."),
                {"received_by": _("wajib")},
            )
        values = {
            "received_by_name": received_by,
            "received_at": stop.received_at or fields.Datetime.now(),
            "pod_source": "device",
        }
        if signature:
            values["pod_signature"] = signature
        if qty_delivered is not None:
            values["qty_delivered"] = float(qty_delivered)
        if qty_rejected is not None:
            values["qty_rejected"] = float(qty_rejected)
            if float(qty_rejected) and not rejection_reason:
                return self._error(
                    "missing_rejection_reason",
                    _("Penolakan tanpa alasan tidak dapat ditagihkan maupun diklaim."),
                    {"rejection_reason": _("wajib bila ada yang ditolak")},
                )
            if rejection_reason:
                values["rejection_reason"] = rejection_reason
        try:
            # Savepoint, bukan sekadar try. Menjawab "ditolak" atas keadaan yang
            # terlanjur separuh tersimpan adalah bentuk kebohongan yang paling
            # mahal: perangkat pengemudi mengulang, stop sudah ber-POD, dan
            # tidak ada log yang menunjukkan keduanya pernah bertentangan.
            with self.env.cr.savepoint():
                stop.write(values)
                for index, photo in enumerate(photos or []):
                    existing = self.env["ir.attachment"].search([
                        ("res_model", "=", "lgx.trip.stop"),
                        ("res_id", "=", stop.id),
                        ("name", "=", "pod-%s-%s.jpg" % (stop.id, index)),
                    ], limit=1)
                    if existing:
                        continue
                    attachment = self.env["ir.attachment"].create({
                        "name": "pod-%s-%s.jpg" % (stop.id, index),
                        "datas": photo,
                        "res_model": "lgx.trip.stop",
                        "res_id": stop.id,
                        "mimetype": "image/jpeg",
                    })
                    stop.pod_photo_ids = [(4, attachment.id)]
        except (AccessError, UserError, ValidationError) as error:
            return self._error("rejected", str(error))
        return self._ok({
            "stop_id": stop.id,
            "trip": stop.trip_id.name,
            "has_pod": stop.has_pod,
            "pod_missing_on_trip": stop.trip_id.pod_missing_count,
        })

    @api.model
    def driver_update_trip(self, trip_id=None, action=None, odometer=None, **kwargs):
        """Ubah status trip dari perangkat. Aksi dibatasi daftar putih."""
        allowed = {
            "dispatch": "action_dispatch",
            "in_transit": "action_in_transit",
            "deliver": "action_deliver",
        }
        if action not in allowed:
            return self._error("bad_action", _("Aksi '%s' tidak dikenal.", action))
        trip = self.env["lgx.trip"].browse(int(trip_id or 0)).exists()
        if not trip:
            return self._error("not_found", _("Trip tidak ditemukan."))
        try:
            # Odometer dan perubahan status harus jatuh atau berdiri bersama.
            # Tanpa savepoint, aksi yang ditolak aturan ODOL atau POD tetap
            # meninggalkan odometer baru di trip yang statusnya tidak berubah.
            with self.env.cr.savepoint():
                if odometer is not None:
                    field_name = "odometer_start" if action == "dispatch" else "odometer_end"
                    trip.write({field_name: float(odometer)})
                getattr(trip, allowed[action])()
        except (AccessError, UserError, ValidationError) as error:
            return self._error("rejected", str(error))
        return self._ok({"trip_id": trip.id, "state": trip.state})

    # --- pemindai gudang (LGX-E01, LGX-E03) --------------------------------
    @api.model
    def scan_receive(self, picking_id=None, barcode=None, quantity=1.0, lot_name=None,
                     owner_id=None, **kwargs):
        """Terima barang hasil pemindaian. Pemilik WAJIB.

        Barcode GS1-128 diurai di SISI SERVER memakai ``barcodes_gs1_nomenclature``,
        bukan di perangkat: aturan penguraian berubah, dan perangkat lapangan
        adalah hal paling sulit diperbarui serentak.
        """
        if not picking_id or not barcode:
            return self._error("missing_input", _("picking_id dan barcode wajib diisi."))
        picking = self.env["stock.picking"].browse(int(picking_id)).exists()
        if not picking:
            return self._error("not_found", _("Picking tidak ditemukan."))
        parsed = self._parse_barcode(barcode)
        product = self._resolve_product(parsed, barcode)
        if not product:
            return self._error("unknown_barcode", _("Barcode '%s' tidak dikenal.", barcode))
        owner = picking.owner_id
        if owner_id:
            owner = self.env["res.partner"].browse(int(owner_id))
        if not owner:
            return self._error(
                "missing_owner",
                _("Pemilik barang wajib pada setiap penerimaan gudang 3PL. Stok tanpa "
                  "pemilik akan tercampur, dan stok yang sudah tercampur tidak dapat "
                  "dipisahkan tanpa stock opname penuh."),
                {"owner_id": _("wajib")},
            )
        move = picking.move_ids.filtered(lambda m: m.product_id == product)[:1]
        if not move:
            return self._error("not_in_picking",
                               _("Produk %s tidak ada di picking ini.", product.display_name))
        # Pemindaian PERTAMA menolkan kuantitas isian-otomatis Odoo. Yang dihitung
        # pemindai adalah apa yang benar-benar ada di palet, bukan apa yang
        # dijanjikan dokumen — dan menumpuk di atas tebakan sistem menghasilkan
        # angka yang lolos validasi lalu meledak saat stok opname.
        #
        # PENOLAKAN ITU MENOLKAN kuantitas. Karena itu lgx_begin_scan ikut masuk
        # savepoint di bawah, bukan berdiri di luarnya: kalau barisnya gagal
        # dibuat, picking harus kembali persis seperti sebelum dipindai. Versi
        # sebelumnya menolkan lebih dulu lalu menjawab "ditolak", dan operator
        # gudang tidak punya cara mengetahui isian-otomatisnya sudah hilang.
        try:
            with self.env.cr.savepoint():
                if hasattr(picking, "lgx_begin_scan"):
                    picking.lgx_begin_scan()
                line_values = {
                    "picking_id": picking.id,
                    "move_id": move.id,
                    "product_id": product.id,
                    "quantity": float(quantity),
                    "owner_id": owner.id,
                    "location_dest_id": move.location_dest_id.id,
                    "location_id": move.location_id.id,
                }
                if lot_name or parsed.get("lot"):
                    line_values["lot_name"] = lot_name or parsed.get("lot")
                if parsed.get("expiry"):
                    line_values["expiration_date"] = parsed["expiry"]
                self.env["stock.move.line"].create(line_values)
        except (AccessError, UserError, ValidationError) as error:
            return self._error("rejected", str(error))
        return self._ok({
            "picking": picking.name,
            "product": product.display_name,
            "quantity": float(quantity),
            "owner": owner.display_name,
            "lot": lot_name or parsed.get("lot"),
        })

    @api.model
    def scan_pick(self, picking_id=None, barcode=None, location=None, quantity=1.0, **kwargs):
        """Ambil barang hasil pemindaian, dengan validasi lokasi.

        Pemindaian yang salah DITOLAK dengan pesan jelas, bukan diam-diam
        diterima. Picking yang menerima apa pun yang dipindai adalah picking yang
        tidak menambah akurasi dibanding kertas.
        """
        if not picking_id or not barcode:
            return self._error("missing_input", _("picking_id dan barcode wajib diisi."))
        picking = self.env["stock.picking"].browse(int(picking_id)).exists()
        if not picking:
            return self._error("not_found", _("Picking tidak ditemukan."))
        parsed = self._parse_barcode(barcode)
        product = self._resolve_product(parsed, barcode)
        if not product:
            return self._error("unknown_barcode", _("Barcode '%s' tidak dikenal.", barcode))
        move_line = picking.move_line_ids.filtered(lambda l: l.product_id == product)[:1]
        if not move_line:
            return self._error(
                "not_in_picking",
                _("Produk %s tidak ada dalam daftar ambil picking %s.",
                  product.display_name, picking.name),
            )
        if location:
            expected = move_line.location_id
            scanned = self.env["stock.location"].search([("barcode", "=", location)], limit=1) \
                or self.env["stock.location"].search([("complete_name", "=", location)], limit=1)
            if not scanned or scanned != expected:
                return self._error(
                    "wrong_location",
                    _("Lokasi yang dipindai (%s) bukan lokasi pengambilan yang benar (%s).",
                      location, expected.complete_name),
                    {"expected_location": expected.complete_name},
                )
        try:
            with self.env.cr.savepoint():
                move_line.quantity = float(quantity)
        except (AccessError, UserError, ValidationError) as error:
            return self._error("rejected", str(error))
        return self._ok({
            "picking": picking.name,
            "product": product.display_name,
            "quantity": float(quantity),
            "location": move_line.location_id.complete_name,
        })

    @api.model
    def wms_task_list(self, kind="incoming", limit=40, **kwargs):
        """Daftar picking terbuka untuk operator gudang.

        TIDAK memakai sudo: apa yang terlihat ditentukan record rule, dan itu
        memang seharusnya — operator satu gudang tidak perlu melihat antrian
        gudang lain, dan endpoint yang mem-bypass rule adalah endpoint yang
        membocorkannya begitu ada satu pemanggil salah kunci.
        """
        if kind not in ("incoming", "outgoing", "internal"):
            return self._error("bad_kind", _("Jenis tugas '%s' tidak dikenal.", kind))
        pickings = self.env["stock.picking"].search([
            ("picking_type_id.code", "=", kind),
            ("state", "in", ("assigned", "confirmed")),
        ], limit=min(int(limit or 40), 100), order="scheduled_date, id")
        return self._ok({
            "kind": kind,
            "tasks": [{
                "id": picking.id,
                "name": picking.name,
                "partner": picking.partner_id.display_name or None,
                "client": (picking.lgx_wms_client_id.name
                           if "lgx_wms_client_id" in picking._fields
                           and picking.lgx_wms_client_id else None),
                "owner": picking.owner_id.display_name or None,
                "scheduled": picking.scheduled_date and str(picking.scheduled_date) or None,
                "state": picking.state,
                "lines": [{
                    "product": move.product_id.display_name,
                    "barcode": move.product_id.barcode or None,
                    "demand": move.product_uom_qty,
                    "done": move.quantity,
                    "location": (move.location_id.complete_name if kind != "incoming"
                                 else move.location_dest_id.complete_name),
                } for move in picking.move_ids],
            } for picking in pickings],
        })

    @api.model
    def _parse_barcode(self, barcode):
        """Urai GS1-128 di sisi server. Mengembalikan dict polos."""
        result = {}
        nomenclature = self.env.company.nomenclature_id
        if not nomenclature:
            return result
        try:
            parsed = nomenclature.parse_barcode(barcode)
        except Exception:  # noqa: BLE001 — barcode tak terurai bukan galat sistem
            return result
        if isinstance(parsed, dict):
            return {"code": parsed.get("code")}
        for rule in parsed or []:
            rule_type = (rule.get("rule") or {}).type if hasattr(rule.get("rule") or {}, "type") \
                else rule.get("type")
            value = rule.get("value")
            if rule_type == "lot":
                result["lot"] = value
            elif rule_type == "product":
                result["product"] = value
            elif rule_type in ("use_date", "expiration_date"):
                result["expiry"] = value
            elif rule_type == "quantity":
                result["quantity"] = value
        return result

    @api.model
    def _resolve_product(self, parsed, barcode):
        Product = self.env["product.product"]
        code = parsed.get("product") or barcode
        return (Product.search([("barcode", "=", code)], limit=1)
                or Product.search([("default_code", "=", code)], limit=1))

    # --- gudang: isolasi antar klien ---------------------------------------
    @api.model
    def wms_stock_by_client(self, client_id=None, **kwargs):
        """Stok per pemilik barang, tunduk record rule.

        Sengaja TIDAK memakai sudo. Isolasi antar klien gudang adalah janji
        kontraktual, dan janji yang hanya ditegakkan di layar akan bocor lewat
        endpoint pertama yang dibuat untuk kenyamanan.
        """
        domain = [("lgx_wms_client_id", "!=", False)]
        if client_id:
            domain.append(("lgx_wms_client_id", "=", int(client_id)))
        quants = self.env["stock.quant"].search(domain)
        grouped = {}
        for quant in quants:
            key = quant.lgx_wms_client_id
            entry = grouped.setdefault(key.id, {
                "client_id": key.id, "client": key.name, "lines": [],
            })
            entry["lines"].append({
                "product": quant.product_id.display_name,
                "location": quant.location_id.complete_name,
                "lot": quant.lot_id.name or None,
                "quantity": quant.quantity,
            })
        return self._ok({"clients": list(grouped.values())})
