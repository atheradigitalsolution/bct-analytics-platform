# -*- coding: utf-8 -*-
"""LGX-D01, D02, D03, D05 — dispatch, ODOL, POD, dan uang jalan."""
import base64

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDispatchAndAdvance(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.params = cls.env["ir.config_parameter"].sudo()
        cls.customer = cls.env["res.partner"].create({"name": "PT Uji Trucking"})
        cls.driver_partner = cls.env["res.partner"].create({"name": "Budi Pengemudi"})
        cls.driver = cls.env["lgx.driver"].create({
            "name": "Budi Pengemudi",
            "partner_id": cls.driver_partner.id,
            "sim_number": "1234-5678-9012",
            "sim_class": "b2_umum",
            "sim_expiry_date": "2030-12-31",
        })
        cls.model = cls.env["fleet.vehicle.model"].search([], limit=1)
        if not cls.model:
            brand = cls.env["fleet.vehicle.model.brand"].create({"name": "Uji"})
            cls.model = cls.env["fleet.vehicle.model"].create({
                "name": "Tronton Uji", "brand_id": brand.id,
            })
        cls.vehicle = cls.env["fleet.vehicle"].create({
            "model_id": cls.model.id,
            "license_plate": "B 9999 UJI",
            "lgx_is_freight": True,
            "lgx_jbb_kg": 26000,
            "lgx_jbi_kg": 24000,
            "lgx_kerb_weight_kg": 9000,
            "lgx_kir_expiry_date": "2030-01-01",
            "lgx_stnk_expiry_date": "2030-01-01",
        })
        cls.origin = cls.env.ref("custom_lgx_base.loc_idjkt")
        cls.destination = cls.env.ref("custom_lgx_base.loc_bandung")
        cls.route = cls.env["lgx.route"].create({
            "origin_location_id": cls.origin.id,
            "destination_location_id": cls.destination.id,
            "distance_km": 180,
            "tariff_ids": [(0, 0, {
                "pricing_basis": "per_trip",
                "price": 3_500_000,
                "standard_advance": 800_000,
                "valid_from": "2026-01-01",
            })],
        })

    def _trip(self, weight=10_000, **kwargs):
        values = {
            "trip_type": "ftl",
            "vehicle_id": self.vehicle.id,
            "driver_id": self.driver.id,
            "route_id": self.route.id,
            "cargo_weight_kg": weight,
            "planned_start": "2026-09-20 06:00:00",
            "planned_end": "2026-09-20 18:00:00",
        }
        values.update(kwargs)
        return self.env["lgx.trip"].create(values)

    # --- LGX-D02 : ODOL ----------------------------------------------------
    def test_load_within_jbi_is_accepted(self):
        trip = self._trip(weight=10_000)
        self.assertEqual(trip.odol_status, "ok")
        trip.action_assign()
        self.assertEqual(trip.state, "assigned")

    def test_overload_warns_before_enforcement_date_and_demands_a_reason(self):
        """Sebelum tanggal penegakan: peringatan yang dapat dilewati DENGAN ALASAN."""
        self.params.set_param("lgx.odol_enforcement_date", "2027-01-01")
        trip = self._trip(weight=20_000)  # 20t + 9t kerb = 29t > JBI 24t
        self.assertEqual(trip.odol_status, "warning")
        with self.assertRaises(UserError) as ctx:
            trip.action_assign()
        self.assertIn("alasan", str(ctx.exception).lower())
        trip.odol_override_reason = "Muatan sudah di atas bak saat aturan diterapkan; sekali ini."
        trip.action_assign()
        self.assertEqual(trip.state, "assigned")

    def test_overload_is_blocked_from_the_enforcement_date(self):
        """Sejak tanggal penegakan: alasan tidak lagi cukup."""
        self.params.set_param("lgx.odol_enforcement_date", "2026-01-01")
        trip = self._trip(weight=20_000)
        trip.invalidate_recordset()
        self.assertEqual(trip.odol_status, "blocked")
        trip.odol_override_reason = "Tetap ingin jalan"
        with self.assertRaises(UserError):
            trip.action_assign()
        self.params.set_param("lgx.odol_enforcement_date", "2027-01-01")

    def test_vehicle_without_jbi_is_unknown_not_ok(self):
        """Kendaraan tanpa data JBI dinyatakan TIDAK DAPAT DIVALIDASI, bukan lolos.

        "Belum diperiksa" yang diperlakukan sebagai "aman" adalah cara sebuah
        armada berangkat kelebihan muatan dengan sistem yang tampak hijau.
        """
        vehicle = self.env["fleet.vehicle"].create({
            "model_id": self.model.id, "license_plate": "B 1111 UJI",
            "lgx_is_freight": True,
        })
        trip = self._trip(weight=50_000, vehicle_id=vehicle.id)
        self.assertEqual(trip.odol_status, "unknown")
        self.assertNotEqual(trip.odol_status, "ok")

    # --- LGX-D01 : penugasan ----------------------------------------------
    def test_expired_driver_licence_blocks_assignment(self):
        self.driver.sim_expiry_date = "2020-01-01"
        self.driver.invalidate_recordset()
        trip = self._trip()
        with self.assertRaises(ValidationError) as ctx:
            trip.action_assign()
        self.assertIn("SIM", str(ctx.exception))
        self.driver.sim_expiry_date = "2030-12-31"

    def test_overlapping_vehicle_assignment_is_rejected(self):
        first = self._trip()
        first.action_assign()
        second = self._trip()
        with self.assertRaises(ValidationError) as ctx:
            second.action_assign()
        self.assertIn(first.name, str(ctx.exception))

    # --- LGX-D04 : POD -----------------------------------------------------
    def test_trip_cannot_be_delivered_without_pod(self):
        trip = self._trip()
        self.env["lgx.trip.stop"].create({
            "trip_id": trip.id, "stop_type": "dropoff",
            "partner_id": self.customer.id, "qty_planned": 100,
        })
        trip.action_assign()
        trip.action_dispatch()
        with self.assertRaises(UserError) as ctx:
            trip.action_deliver()
        self.assertIn("POD", str(ctx.exception))

    def test_signature_without_receiver_name_is_not_a_pod(self):
        """Tanda tangan tanpa nama penerima adalah coretan; yang menagih keduanya."""
        trip = self._trip()
        stop = self.env["lgx.trip.stop"].create({
            "trip_id": trip.id, "stop_type": "dropoff",
            "partner_id": self.customer.id, "qty_planned": 100,
            "pod_signature": base64.b64encode(b"tandatangan"),
        })
        self.assertFalse(stop.has_pod)
        stop.received_by_name = "Siti"
        stop.invalidate_recordset()
        self.assertTrue(stop.has_pod)

    def test_trip_is_delivered_once_every_dropoff_has_pod(self):
        trip = self._trip()
        self.env["lgx.trip.stop"].create({
            "trip_id": trip.id, "stop_type": "dropoff",
            "partner_id": self.customer.id, "qty_planned": 100,
            "qty_delivered": 100,
            "pod_signature": base64.b64encode(b"tandatangan"),
            "received_by_name": "Siti",
        })
        trip.action_assign()
        trip.action_dispatch()
        trip.action_deliver()
        self.assertEqual(trip.state, "delivered")

    # --- LGX-D03 dan D05 : uang jalan -------------------------------------
    def test_advance_limit_comes_from_the_route_master(self):
        trip = self._trip()
        trip.action_create_advance()
        self.assertEqual(trip.advance_id.amount_limit, 800_000)
        self.assertEqual(trip.advance_id.amount_requested, 800_000)

    def test_advance_above_limit_needs_a_recorded_reason(self):
        trip = self._trip()
        trip.action_create_advance()
        advance = trip.advance_id
        advance.amount_requested = 2_000_000
        with self.assertRaises(UserError) as ctx:
            advance.action_approve()
        self.assertIn("alasan", str(ctx.exception).lower())
        advance.approval_reason = "Rute banjir, perlu jalur memutar berbayar."
        advance.action_approve()
        self.assertEqual(advance.state, "approved")

    def test_driver_cannot_hold_two_open_advances(self):
        first = self._trip()
        first.action_create_advance()
        first.advance_id.action_approve()
        second = self._trip(planned_start="2026-09-25 06:00:00", planned_end="2026-09-25 18:00:00")
        second.action_create_advance()
        with self.assertRaises(ValidationError) as ctx:
            second.advance_id.action_approve()
        self.assertIn(first.advance_id.name, str(ctx.exception))

    def test_trip_cannot_settle_while_advance_is_open(self):
        trip = self._trip()
        self.env["lgx.trip.stop"].create({
            "trip_id": trip.id, "stop_type": "dropoff",
            "partner_id": self.customer.id, "qty_planned": 10, "qty_delivered": 10,
            "pod_signature": base64.b64encode(b"ttd"), "received_by_name": "Siti",
        })
        trip.action_create_advance()
        trip.advance_id.action_approve()
        trip.advance_id.action_pay()
        trip.action_assign()
        trip.action_dispatch()
        trip.action_deliver()
        with self.assertRaises(UserError) as ctx:
            trip.action_settle()
        self.assertIn("uang jalan", str(ctx.exception).lower())

    def test_settlement_balance_becomes_a_receivable_or_a_reimbursement(self):
        trip = self._trip()
        trip.action_create_advance()
        advance = trip.advance_id
        advance.action_approve()
        advance.action_pay()
        self.env["lgx.trip.expense"].create({
            "trip_id": trip.id, "advance_id": advance.id,
            "category": "fuel", "amount": 500_000,
            "proof_ids": [(0, 0, {"name": "nota-bbm.jpg", "datas": base64.b64encode(b"x")})],
        })
        advance.invalidate_recordset()
        self.assertEqual(advance.balance, 300_000)
        self.assertEqual(advance.balance_direction, "return")
        advance.action_settle()
        self.assertEqual(advance.state, "settled")

    def test_expense_above_threshold_demands_proof(self):
        trip = self._trip()
        trip.action_create_advance()
        with self.assertRaises(ValidationError) as ctx:
            self.env["lgx.trip.expense"].create({
                "trip_id": trip.id, "advance_id": trip.advance_id.id,
                "category": "toll", "amount": 500_000,
            })
        self.assertIn("bukti", str(ctx.exception).lower())
