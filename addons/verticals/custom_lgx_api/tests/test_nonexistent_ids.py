# -*- coding: utf-8 -*-
"""Id yang SAH secara tipe tetapi tidak ada recordnya.

Bentuk ketiga dari cacat kontrak, dan yang paling mudah terjadi di lapangan.
Tidak ada klien yang mengirim "abc" kecuali sedang mengetes; setiap klien
mengirim id lama dari tab yang usang, cache yang basi, atau record yang baru
dihapus orang lain. Yang pertama cacat sintaksis, yang ini keadaan normal
sistem yang hidup.

Ia lolos dari dekorator `lgx_public_api` karena `int(999999)` berhasil — tidak
ada ValueError untuk ditangkap. Dan ia lolos dari penjaga `if not record`
karena **recordset atas id yang tidak ada bernilai TRUTHY**. Yang meledak
adalah pembacaan field jauh sesudahnya, atau basis data saat menulis.
"""
from odoo.tests import TransactionCase, tagged

ID_HANTU = 999_999


@tagged("post_install", "-at_install")
class TestNonexistentIds(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.service = cls.env["lgx.api.service"]
        cls.dispatcher = cls.env["res.users"].create({
            "name": "Dispatcher Uji", "login": "dispatcher@uji.invalid",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_user").id,
                cls.env.ref("custom_lgx_base.group_lgx_trucking_dispatcher").id,
            ])],
        })

    def test_browse_on_a_missing_id_is_truthy_and_that_is_the_trap(self):
        """Prasyarat yang membuat sisa berkas ini masuk akal.

        Kalau Odoo suatu saat mengubah ini, penjaga `.exists()` menjadi
        berlebihan dan uji di bawah berhenti menguji apa pun — jadi asumsinya
        dipegang eksplisit di sini, bukan diandaikan.
        """
        hantu = self.env["lgx.driver"].browse(ID_HANTU)
        self.assertTrue(hantu, "Recordset atas id yang tidak ada TETAP truthy.")
        self.assertFalse(hantu.exists(), ".exists() yang membedakannya.")

    def test_missing_driver_id_is_refused_not_a_crash(self):
        """Tanpa .exists(), `driver.name` di badan jawaban melempar MissingError.

        MissingError tidak ditangkap dekorator maupun blok except mana pun, jadi
        dispatcher yang salah ketik id menerima 500.
        """
        result = self.service.with_user(self.dispatcher).driver_trip_list(
            driver_id=ID_HANTU)
        self.assertIn("error", result, "Harus ditolak, bukan meledak.")
        self.assertEqual(result["error"]["code"], "no_driver")

    def test_missing_owner_id_is_refused_before_the_database_sees_it(self):
        """Tanpa .exists(), id hantu ditulis ke stock.move.line.

        Yang menolaknya kemudian adalah foreign key di basis data — jauh dari
        sini, sebagai 500, dan dengan transaksi yang sudah batal.
        """
        picking, product = self._picking_with_product()
        # action_confirm sudah membuat baris isian-otomatis, jadi yang diukur
        # SELISIHNYA. Menuntut nol akan menguji fixture, bukan kode.
        sebelum = len(picking.move_line_ids)
        result = self.service.scan_receive(
            picking_id=picking.id, barcode=product.barcode,
            quantity=5, owner_id=ID_HANTU)
        self.assertIn("error", result)
        self.assertEqual(result["error"]["code"], "unknown_owner")
        picking.invalidate_recordset()
        self.assertEqual(
            len(picking.move_line_ids), sebelum,
            "Tidak ada baris yang boleh lahir dari pemindaian yang ditolak.",
        )

    def test_a_real_owner_is_still_accepted(self):
        """Penjaga tidak boleh rakus — pemilik yang sah tetap dipindai."""
        picking, product = self._picking_with_product()
        owner = self.env["res.partner"].create({"name": "PT Pemilik Sah"})
        result = self.service.scan_receive(
            picking_id=picking.id, barcode=product.barcode,
            quantity=5, owner_id=owner.id)
        self.assertNotIn("error", result, result.get("error"))
        picking.invalidate_recordset()
        milik_pemilik = picking.move_line_ids.filtered(
            lambda l: l.owner_id == owner)
        self.assertTrue(
            milik_pemilik,
            "Baris hasil pemindaian harus membawa pemiliknya — stok tanpa "
            "pemilik akan tercampur, dan itu hanya dapat dipisahkan dengan "
            "stock opname penuh.",
        )

    # --- fixture -----------------------------------------------------------
    def _picking_with_product(self):
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1)
        picking_type = self.env["stock.picking.type"].search([
            ("code", "=", "incoming"), ("warehouse_id", "=", warehouse.id),
        ], limit=1)
        product = self.env["product.product"].create({
            "name": "Kardus Uji Barcode",
            "type": "consu", "is_storable": True,
            "barcode": "8991234567890",
        })
        picking = self.env["stock.picking"].create({
            "picking_type_id": picking_type.id,
            "location_id": self.env.ref("stock.stock_location_suppliers").id,
            "location_dest_id": picking_type.default_location_dest_id.id,
            "move_ids": [(0, 0, {
                # Odoo 19 menghapus stock.move.name; penggantinya
                # description_picking.
                "description_picking": product.name,
                "product_id": product.id,
                "product_uom_qty": 10.0,
                "location_id": self.env.ref("stock.stock_location_suppliers").id,
                "location_dest_id": picking_type.default_location_dest_id.id,
            })],
        })
        picking.action_confirm()
        return picking, product
