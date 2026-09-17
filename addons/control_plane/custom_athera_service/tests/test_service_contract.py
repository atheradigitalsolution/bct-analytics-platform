# -*- coding: utf-8 -*-
"""Uji untuk athera.service.contract.

Yang diuji di sini adalah hal-hal yang bisa salah dalam diam: aritmetika saldo,
state yang mengikuti aritmetika, dan state yang TIDAK boleh diikutkan. Uji yang
hanya membuat satu record lalu memeriksa ia ada tidak menolak apa pun.
"""

from psycopg2 import IntegrityError

from odoo.tests.common import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestAtheraServiceContract(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tenant = cls.env["tenant.registry"].create({
            "slug": "uji_svc",
            "display_name": "Klien Uji Layanan",
            "db_name": "uji_svc",
        })
        cls.contract = cls.env["athera.service.contract"].create({
            "name": "SVC/UJI/0001",
            "tenant_id": cls.tenant.id,
            "service_type": "maintenance",
            "hours_purchased": 10.0,
        })

    def _ticket(self, hours):
        return self.env["helpdesk.ticket"].create({
            "subject": "Tiket uji %s jam" % hours,
            "athera_contract_id": self.contract.id,
            "athera_hours_spent": hours,
        })

    def test_saldo_awal_sama_dengan_jam_dibeli(self):
        """Kontrak tanpa pekerjaan apa pun menyisakan persis yang dibeli."""
        self.assertEqual(self.contract.hours_consumed, 0.0)
        self.assertEqual(self.contract.hours_remaining, 10.0)

    def test_jam_tiket_mengurangi_saldo(self):
        self._ticket(3.0)
        self._ticket(2.5)
        self.contract.invalidate_recordset()
        self.assertEqual(self.contract.hours_consumed, 5.5)
        self.assertEqual(self.contract.hours_remaining, 4.5)

    def test_state_berjalan_menjadi_habis_lalu_kembali(self):
        """State mengikuti aritmetika di KEDUA arah.

        Arah kedua yang penting: kontrak yang jamnya ditambah harus kembali
        `running`. Implementasi yang hanya menyetel `exhausted` dan tidak pernah
        membatalkannya akan mengunci setiap kontrak yang pernah habis sekali.
        """
        self.contract.action_start()
        self.assertEqual(self.contract.state, "running")

        self._ticket(10.0)
        self.contract.invalidate_recordset()
        self.assertEqual(self.contract.hours_remaining, 0.0)
        self.assertEqual(self.contract.state, "exhausted")

        self.contract.hours_purchased = 15.0
        self.contract.invalidate_recordset()
        self.assertEqual(self.contract.hours_remaining, 5.0)
        self.assertEqual(self.contract.state, "running")

    def test_saldo_minus_diizinkan_dan_terlihat(self):
        """Pekerjaan yang melewati saldo tetap tercatat, dan saldonya jadi negatif.

        Ini keputusan produk, bukan kelalaian: menolak pencatatan mendorong jam
        keluar dari buku. Uji ini yang menjaganya kalau ada yang tergoda menambah
        constraint `hours_remaining >= 0`.
        """
        self.contract.action_start()
        self._ticket(12.0)
        self.contract.invalidate_recordset()
        self.assertEqual(self.contract.hours_remaining, -2.0)
        self.assertEqual(self.contract.state, "exhausted")

    def test_draft_dan_closed_tidak_ditimpa_oleh_aritmetika(self):
        """Dua state milik manusia. Sebuah tiket yang masuk tidak boleh memindahkannya."""
        self.assertEqual(self.contract.state, "draft")
        self._ticket(99.0)
        self.contract.invalidate_recordset()
        self.assertEqual(self.contract.state, "draft",
                         "draft tidak boleh berubah karena ada jam masuk")

        self.contract.action_close()
        self._ticket(1.0)
        self.contract.invalidate_recordset()
        self.assertEqual(self.contract.state, "closed",
                         "closed tidak boleh dibuka kembali oleh jam masuk")

    def test_nilai_kontrak_dihitung_dari_tarif(self):
        self.contract.rate_hour = 250000.0
        self.assertEqual(self.contract.amount_total, 2500000.0)

    def test_task_membawa_klien_lewat_kontrak(self):
        """Tenant di task tidak diisi tangan — ia datang dari kontrak, jadi tidak bisa
        berselisih dengan kontraknya."""
        project = self.env["project.project"].create({"name": "Proyek Uji Layanan"})
        task = self.env["project.task"].create({
            "name": "Task uji",
            "project_id": project.id,
            "athera_contract_id": self.contract.id,
        })
        self.assertEqual(task.athera_tenant_id, self.tenant)

    @mute_logger("odoo.sql_db")
    def test_jam_dibeli_negatif_ditolak(self):
        with self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.env["athera.service.contract"].create({
                    "name": "SVC/UJI/NEG",
                    "tenant_id": self.tenant.id,
                    "hours_purchased": -1.0,
                })
