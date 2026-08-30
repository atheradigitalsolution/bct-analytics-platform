# Part of custom_demo_seed. Licence: LGPL-3.
"""Parameterised, idempotent, reproducible demo volume.

Why this module exists: the Phase 4 performance budget is "p95 under 2 s with 12 months of data",
and that cannot be measured against an empty database. This generates the data.

Three properties it must have, and how each is obtained:

* **Idempotent.** Every record is created through :meth:`_ensure`, which registers an
  ``ir.model.data`` external ID. A second run finds the external ID and returns the existing
  record instead of creating a new one. Running the generator twice therefore changes no row
  count. This is stronger than a "does a record with this name exist?" check: it survives
  renames and it makes ``uninstall`` remove exactly the demo rows and nothing else.
* **Reproducible.** All randomness comes from a single ``random.Random(seed)``. The same seed
  produces the same partners, the same amounts and the same date spread.
* **Never in production.** ``custom_demo_seed`` is not ``auto_install``, not a dependency of any
  other module, and generates nothing at install time. Data appears only when the method is
  called explicitly.

Everything it writes is obviously synthetic - see :meth:`_ensure_partners`.
"""

import logging
import random
from datetime import date, datetime, time, timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

MODULE = "custom_demo_seed"

#: Marker carried by every generated record, so a human can tell demo data from real data at a
#: glance and so `_reset` can find it without guessing.
DEMO_TAG = "Demo"

OPERATING_UNITS = [
    ("OU-DEMO-JKT", "Cabang Jakarta (Demo)"),
    ("OU-DEMO-BDG", "Cabang Bandung (Demo)"),
    ("OU-DEMO-SBY", "Cabang Surabaya (Demo)"),
    ("OU-DEMO-MDN", "Cabang Medan (Demo)"),
]

BILLERS = [
    ("DEMO-PLN-PRE", "PLN Prabayar (Demo)", "electricity", 20),
    ("DEMO-PLN-POST", "PLN Pascabayar (Demo)", "electricity", 30),
    ("DEMO-PDAM", "PDAM Kota (Demo)", "water", 45),
    ("DEMO-TELCO", "Pulsa Seluler (Demo)", "telco", 15),
    ("DEMO-INET", "Internet Rumah (Demo)", "internet", 60),
    ("DEMO-BPJS", "BPJS Kesehatan (Demo)", "insurance", 90),
]

#: Obviously-synthetic person names. Common Indonesian given names, but every record also carries
#: a "(Demo NNN)" suffix, a `.invalid` e-mail domain and a `+62-800-555-` phone, so none of these
#: can be mistaken for a real person's record.
GIVEN_NAMES = [
    "Budi", "Siti", "Agus", "Dewi", "Eko", "Rina", "Joko", "Ani", "Bayu", "Lestari",
    "Andi", "Maya", "Rizki", "Putri", "Hendra", "Sari", "Fajar", "Indah", "Yusuf", "Nurul",
]
FAMILY_NAMES = [
    "Santoso", "Wijaya", "Pratama", "Kusuma", "Hidayat", "Nugroho", "Saputra", "Wahyuni",
    "Permata", "Halim",
]
CITIES = ["Jakarta", "Bandung", "Surabaya", "Medan", "Semarang", "Makassar"]

PRODUCTS = [
    ("DEMO-P-VCR-010", "Voucher Data Demo 10GB", 55000.0, 42000.0, False),
    ("DEMO-P-VCR-025", "Voucher Data Demo 25GB", 110000.0, 88000.0, False),
    ("DEMO-P-TKN-050", "Token Listrik Demo 50rb", 52500.0, 50000.0, False),
    ("DEMO-P-TKN-100", "Token Listrik Demo 100rb", 102500.0, 100000.0, False),
    ("DEMO-P-SIM-001", "Kartu Perdana Demo", 25000.0, 15000.0, False),
    ("DEMO-P-RTR-001", "Router WiFi Demo", 450000.0, 310000.0, False),
    ("DEMO-P-RTR-002", "Router WiFi Demo Pro", 890000.0, 640000.0, False),
    ("DEMO-P-CBL-001", "Kabel LAN Demo 5m", 35000.0, 18000.0, False),
    ("DEMO-P-ADP-001", "Adaptor Demo 12V", 75000.0, 41000.0, False),
    ("DEMO-P-INS-001", "Jasa Instalasi Demo", 150000.0, 90000.0, True),
    ("DEMO-P-SVC-001", "Jasa Perawatan Demo", 200000.0, 120000.0, True),
    ("DEMO-P-CNS-001", "Konsultasi Jaringan Demo", 500000.0, 300000.0, True),
]

FAILURE_REASONS = [
    "Saldo deposit biller tidak mencukupi (demo)",
    "Nomor pelanggan tidak ditemukan di sistem biller (demo)",
    "Timeout dari host biller (demo)",
    "Tagihan sudah dibayar melalui kanal lain (demo)",
]


class DemoSeedGenerator(models.TransientModel):
    """Service object. Transient because it holds no state between runs."""

    _name = "demo.seed.generator"
    _description = "Demo Data Seed Generator"

    seed = fields.Integer(default=20260101, required=True)
    partner_count = fields.Integer(string="Partners", default=40, required=True)
    product_count = fields.Integer(string="Products", default=12, required=True)
    operating_unit_count = fields.Integer(string="Operating Units", default=2, required=True)
    months = fields.Integer(default=12, required=True)
    sale_orders_per_month = fields.Integer(default=10, required=True)
    pos_orders_per_month = fields.Integer(default=8, required=True)
    ppob_per_month = fields.Integer(default=30, required=True)
    with_pos = fields.Boolean(string="Generate POS orders", default=True)

    def action_generate(self):
        self.ensure_one()
        summary = self.generate(
            seed=self.seed,
            partners=self.partner_count,
            products=self.product_count,
            operating_units=self.operating_unit_count,
            months=self.months,
            sale_orders_per_month=self.sale_orders_per_month,
            pos_orders_per_month=self.pos_orders_per_month,
            ppob_per_month=self.ppob_per_month,
            with_pos=self.with_pos,
        )
        message = "\n".join("%s: %s" % (key, value) for key, value in sorted(summary.items()))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Demo data generated"),
                "message": message,
                "sticky": True,
                "type": "success",
            },
        }

    # ==================================================================
    # Entry point
    # ==================================================================

    @api.model
    def generate(
        self,
        seed=20260101,
        partners=40,
        products=12,
        operating_units=2,
        months=12,
        sale_orders_per_month=10,
        pos_orders_per_month=8,
        ppob_per_month=30,
        with_pos=True,
        company=None,
    ):
        """Generate demo volume and return a dict of counts.

        Safe to call repeatedly: a second call with the same arguments creates nothing.

        :param seed: RNG seed. Same seed, same data.
        :param months: how many whole months back from today to spread the data over.
        :return: ``{"partners": n, "sale_orders": n, ...}`` - the number of records that now exist,
            not the number created by this call.
        """
        if not self.env.user._is_admin():
            raise UserError(_("Only an administrator may generate demo data."))
        if operating_units < 2:
            raise UserError(
                _("At least 2 Operating Units are required: the demo must span more than one.")
            )
        if operating_units > len(OPERATING_UNITS):
            raise UserError(
                _("At most %s Operating Units are defined.", len(OPERATING_UNITS))
            )

        env = self.env(su=True)
        company = company or env.company
        rng = random.Random(seed)
        started = datetime.now()
        _logger.info(
            "custom_demo_seed: generating (seed=%s, months=%s, company=%s)",
            seed, months, company.display_name,
        )

        self._ensure_chart_of_accounts(env, company)
        units = self._ensure_operating_units(env, company, operating_units)
        partner_records = self._ensure_partners(env, company, partners, rng)
        product_records = self._ensure_products(env, company, products)
        biller_records = self._ensure_billers(env, company)
        self._ensure_demo_users(env, units)
        self._ensure_stock(env, company, product_records)

        pos_configs = self._ensure_pos_configs(env, company, units) if with_pos else None

        for offset in range(months - 1, -1, -1):
            month_start = (date.today().replace(day=1) - relativedelta(months=offset))
            self._seed_sale_orders(
                env, company, month_start, offset, units, partner_records, product_records,
                sale_orders_per_month, rng,
            )
            self._seed_ppob(
                env, company, month_start, offset, units, partner_records, product_records,
                biller_records, ppob_per_month, rng,
            )
            if pos_configs:
                self._seed_pos(
                    env, company, month_start, offset, units, partner_records, product_records,
                    pos_configs, pos_orders_per_month, rng,
                )

        summary = self.summary(company=company)
        summary["elapsed_seconds"] = round((datetime.now() - started).total_seconds(), 1)
        _logger.info("custom_demo_seed: done %s", summary)
        return summary

    @api.model
    def summary(self, company=None):
        """Return the current row counts of everything this module generates."""
        env = self.env(su=True)
        company = company or env.company
        demo_orders = env["sale.order"].search([("name", "like", "%")]).filtered(
            lambda order: self._is_demo(order)
        )
        return {
            "operating_units": env["operating.unit"].search_count(
                [("code", "like", "OU-DEMO-%")]
            ),
            "partners": env["res.partner"].search_count([("ref", "like", "DEMO-C-%")]),
            "products": env["product.template"].search_count(
                [("default_code", "like", "DEMO-P-%")]
            ),
            "billers": env["ppob.biller"].search_count([("code", "like", "DEMO-%")]),
            "sale_orders": len(demo_orders),
            "sale_order_lines": env["sale.order.line"].search_count(
                [("order_id", "in", demo_orders.ids)]
            ),
            "invoices": env["account.move"].search_count(
                [("move_type", "=", "out_invoice"),
                 ("operating_unit_id.code", "like", "OU-DEMO-%")]
            ),
            "stock_moves": env["stock.move"].search_count(
                [("picking_id.operating_unit_id.code", "like", "OU-DEMO-%")]
            ),
            "pos_orders": env["pos.order"].search_count(
                [("operating_unit_id.code", "like", "OU-DEMO-%")]
            ),
            "ppob_transactions": env["ppob.transaction"].search_count(
                [("biller_id.code", "like", "DEMO-%")]
            ),
        }

    # ==================================================================
    # Idempotency
    # ==================================================================

    def _is_demo(self, record):
        return bool(
            self.env["ir.model.data"].sudo().search_count([
                ("module", "=", MODULE),
                ("model", "=", record._name),
                ("res_id", "=", record.id),
            ])
        )

    def _ensure(self, env, xmlid, model, values):
        """Return the record registered under ``custom_demo_seed.<xmlid>``, creating it if absent.

        This is the whole idempotency mechanism. Do not create a demo record any other way.
        """
        existing = env.ref("%s.%s" % (MODULE, xmlid), raise_if_not_found=False)
        if existing:
            return existing
        record = env[model].create(values)
        env["ir.model.data"].create({
            "module": MODULE,
            "name": xmlid,
            "model": model,
            "res_id": record.id,
            "noupdate": True,
        })
        return record

    def _exists(self, env, xmlid):
        return env.ref("%s.%s" % (MODULE, xmlid), raise_if_not_found=False)

    def _tag(self, env, xmlid, record):
        env["ir.model.data"].create({
            "module": MODULE,
            "name": xmlid,
            "model": record._name,
            "res_id": record.id,
            "noupdate": True,
        })
        return record

    # ==================================================================
    # Master data
    # ==================================================================

    def _ensure_chart_of_accounts(self, env, company):
        if company.chart_template:
            return
        _logger.info("custom_demo_seed: loading generic_coa into %s", company.display_name)
        env["account.chart.template"].try_loading("generic_coa", company=company)

    def _ensure_operating_units(self, env, company, count):
        units = env["operating.unit"].browse()
        for code, name in OPERATING_UNITS[:count]:
            units |= self._ensure(env, "ou_%s" % code.lower().replace("-", "_"), "operating.unit", {
                "name": name,
                "code": code,
                "company_id": company.id,
            })
        return units

    def _ensure_partners(self, env, company, count, rng):
        """Create obviously-synthetic customers.

        Every value is unmistakably fake:

        * the display name carries a ``(Demo NNN)`` suffix;
        * e-mail uses ``@contoh.invalid`` - ``.invalid`` is reserved by RFC 2606 and can never
          resolve;
        * phone numbers use ``+62-800-555-NNNN``; ``800`` is not an assignable Indonesian mobile
          prefix and ``555`` is the long-standing fiction convention;
        * ``ref`` is ``DEMO-C-NNNN``.

        ``vat`` is deliberately left EMPTY. Odoo's ``base_vat`` validates the Indonesian NPWP
        checksum, so a value that survived validation would by definition be checksum-valid - i.e.
        it would look exactly like a real NPWP. That is the "invents data resembling a real
        person's identifiers" failure the brief forbids, so the field stays blank and the masking
        of ``res.partner.vat`` is demonstrated by the unit tests instead.
        """
        country = env.ref("base.id", raise_if_not_found=False)  # Indonesia
        partners = env["res.partner"].browse()
        for index in range(1, count + 1):
            given = GIVEN_NAMES[(index - 1) % len(GIVEN_NAMES)]
            family = FAMILY_NAMES[(index - 1) // len(GIVEN_NAMES) % len(FAMILY_NAMES)]
            values = {
                "name": "%s %s (Demo %03d)" % (given, family, index),
                "ref": "DEMO-C-%04d" % index,
                "email": "%s.%s.%03d@contoh.invalid" % (given.lower(), family.lower(), index),
                "phone": "+62-800-555-%04d" % index,
                "street": "Jl. Contoh Demo No. %d" % (index % 200 + 1),
                "city": CITIES[index % len(CITIES)],
                "zip": "%05d" % (10000 + index),
                "is_company": False,
                "customer_rank": 1,
                "comment": "Data contoh untuk pengujian. Bukan orang sungguhan.",
            }
            if country:
                values["country_id"] = country.id
            partners |= self._ensure(env, "partner_%04d" % index, "res.partner", values)
        return partners

    def _ensure_products(self, env, company, count):
        products = env["product.product"].browse()
        for index, (code, name, price, cost, is_service) in enumerate(PRODUCTS[:count], start=1):
            template = self._ensure(env, "product_%02d" % index, "product.template", {
                "name": name,
                "default_code": code,
                "list_price": price,
                "standard_price": cost,
                "type": "service" if is_service else "consu",
                "is_storable": not is_service,
                "sale_ok": True,
                "purchase_ok": not is_service,
                "available_in_pos": not is_service,
                "invoice_policy": "order",
                "company_id": False,
            })
            products |= template.product_variant_id
        return products

    def _ensure_billers(self, env, company):
        billers = env["ppob.biller"].browse()
        for code, name, category, sla in BILLERS:
            billers |= self._ensure(
                env, "biller_%s" % code.lower().replace("-", "_"), "ppob.biller", {
                    "name": name,
                    "code": code,
                    "category": category,
                    "sla_target_seconds": sla,
                    "company_id": company.id,
                }
            )
        return billers

    def _ensure_demo_users(self, env, units):
        """Two internal users, each entitled to exactly one Operating Unit.

        They exist so the cross-unit isolation of ``custom_operating_unit`` can be demonstrated by
        logging in, not only by a unit test. Passwords are NOT set: the accounts cannot be logged
        into until an administrator sets one, which keeps a demo-seeded database from shipping a
        known credential.
        """
        group_ids = [
            env.ref("base.group_user").id,
            env.ref("custom_ppob.group_ppob_user").id,
        ]
        for index, unit in enumerate(units[:2], start=1):
            self._ensure(env, "user_ou_%d" % index, "res.users", {
                "name": "Petugas %s (Demo)" % unit.name,
                "login": "demo.ou%d@contoh.invalid" % index,
                "group_ids": [(6, 0, group_ids)],
                "allowed_operating_unit_ids": [(6, 0, unit.ids)],
                "default_operating_unit_id": unit.id,
            })

    def _ensure_stock(self, env, company, products):
        """Put stock on hand, so deliveries validate without going negative.

        Uses the inventory-adjustment flow rather than writing quants directly, so the resulting
        `stock.move` rows are the same shape a real adjustment produces.
        """
        if self._exists(env, "stock_seeded"):
            return
        warehouse = env["stock.warehouse"].search([("company_id", "=", company.id)], limit=1)
        if not warehouse:
            return
        location = warehouse.lot_stock_id
        storable = products.filtered(lambda p: p.is_storable)
        if not storable:
            return
        quants = env["stock.quant"].with_context(inventory_mode=True).create([
            {
                "product_id": product.id,
                "location_id": location.id,
                "inventory_quantity": 100000.0,
            }
            for product in storable
        ])
        quants.action_apply_inventory()
        marker = self._ensure(env, "stock_seeded", "ir.config_parameter", {
            "key": "custom_demo_seed.stock_seeded",
            "value": fields.Datetime.to_string(fields.Datetime.now()),
        })
        return marker

    def _ensure_pos_configs(self, env, company, units):
        """One point of sale per Operating Unit, each with one long-lived open session.

        Odoo allows only one open ``pos.session`` per ``pos.config`` at a time, and closing a
        session posts accounting entries - doing that 12 times per unit would make the fixture slow
        and fragile for no analytic benefit. So the fixture opens one session per unit and spreads
        ``pos.order.date_order`` across the 12 months instead. The warehouse reads ``date_order``,
        which is faithful; what it does not reproduce is realistic session boundaries. Recorded in
        MODULE_KNOWLEDGE.md.
        """
        payment_method = env["pos.payment.method"].search(
            [("company_id", "=", company.id), ("is_cash_count", "=", True)], limit=1
        )
        if not payment_method:
            payment_method = env["pos.payment.method"].search(
                [("company_id", "=", company.id)], limit=1
            )
        configs = {}
        for unit in units:
            key = unit.code.lower().replace("-", "_")
            values = {
                "name": "Kasir %s" % unit.name,
                "company_id": company.id,
            }
            if payment_method:
                values["payment_method_ids"] = [(6, 0, payment_method.ids)]
            config = self._ensure(env, "pos_config_%s" % key, "pos.config", values)
            session = self._exists(env, "pos_session_%s" % key)
            if not session:
                session = env["pos.session"].search(
                    [("config_id", "=", config.id), ("state", "!=", "closed")], limit=1
                )
                if not session:
                    session = env["pos.session"].create({
                        "config_id": config.id,
                        "user_id": env.uid,
                    })
                self._tag(env, "pos_session_%s" % key, session)
            if session.state == "opening_control":
                session.set_opening_control(0, None)
            configs[unit.id] = (config, session)
        return configs

    # ==================================================================
    # Monthly volume
    # ==================================================================

    def _month_datetime(self, month_start, rng, index):
        """Spread a record across the month, in business hours, deterministically."""
        last_day = (month_start + relativedelta(months=1)) - timedelta(days=1)
        span = (last_day - month_start).days
        day = month_start + timedelta(days=rng.randint(0, max(span, 0)))
        if day > date.today():
            day = date.today()
        moment = time(hour=rng.randint(8, 19), minute=rng.randint(0, 59), second=rng.randint(0, 59))
        return datetime.combine(day, moment)

    def _seed_sale_orders(self, env, company, month_start, offset, units, partners, products,
                          count, rng):
        sellable = products.filtered(lambda p: p.sale_ok)
        if not sellable or not partners:
            return
        for index in range(1, count + 1):
            xmlid = "so_%s_%02d" % (month_start.strftime("%Y%m"), index)
            if self._exists(env, xmlid):
                continue
            when = self._month_datetime(month_start, rng, index)
            unit = units[rng.randrange(len(units))]
            partner = partners[rng.randrange(len(partners))]
            lines = []
            for _line in range(rng.randint(1, 4)):
                product = sellable[rng.randrange(len(sellable))]
                lines.append((0, 0, {
                    "product_id": product.id,
                    "product_uom_qty": rng.randint(1, 12),
                }))
            order = env["sale.order"].create({
                "partner_id": partner.id,
                "company_id": company.id,
                "operating_unit_id": unit.id,
                "date_order": when,
                "order_line": lines,
            })
            self._tag(env, xmlid, order)
            order.action_confirm()
            # action_confirm resets date_order to now for a draft->sale transition in some flows;
            # pin it back so the 12-month spread survives.
            order.write({"date_order": when})
            self._deliver(env, order, when)
            self._invoice(env, order, when)

    def _deliver(self, env, order, when):
        for picking in order.picking_ids:
            if picking.state in ("done", "cancel"):
                continue
            picking.action_assign()
            for move in picking.move_ids:
                move.quantity = move.product_uom_qty
                move.picked = True
            picking._action_done()
            picking.write({"date_done": when, "scheduled_date": when})
            picking.move_ids.write({"date": when})

    def _invoice(self, env, order, when):
        if order.invoice_status != "to invoice":
            return
        moves = order._create_invoices()
        if not moves:
            return
        invoice_date = when.date()
        moves.write({"invoice_date": invoice_date, "date": invoice_date})
        moves.action_post()

    def _seed_ppob(self, env, company, month_start, offset, units, partners, products, billers,
                   count, rng):
        if not billers:
            return
        Transaction = env["ppob.transaction"]
        for index in range(1, count + 1):
            xmlid = "ppob_%s_%03d" % (month_start.strftime("%Y%m"), index)
            if self._exists(env, xmlid):
                continue
            when = self._month_datetime(month_start, rng, index)
            unit = units[rng.randrange(len(units))]
            biller = billers[rng.randrange(len(billers))]
            partner = partners[rng.randrange(len(partners))] if rng.random() < 0.7 else None
            amount = float(rng.choice([20000, 50000, 100000, 150000, 200000, 350000, 500000]))
            admin_fee = float(rng.choice([1500, 2000, 2500, 3000]))
            commission = float(rng.choice([500, 750, 1000, 1250]))
            txn = Transaction.create({
                "biller_id": biller.id,
                "partner_id": partner.id if partner else False,
                "operating_unit_id": unit.id,
                "company_id": company.id,
                # "DEMO-" prefix makes the subscriber number unmistakably synthetic.
                "customer_ref": "DEMO-%011d" % (index + offset * 1000 + biller.id * 100000),
                "customer_name": partner.name if partner else "Pelanggan Tunai (Demo)",
                "amount": amount,
                "admin_fee": admin_fee,
                "commission": min(commission, admin_fee),
                "requested_at": when,
            })
            self._tag(env, xmlid, txn)
            txn.action_submit()
            roll = rng.random()
            latency = rng.randint(3, int(biller.sla_target_seconds * 2.5) or 60)
            settled = when + timedelta(seconds=latency)
            if roll < 0.92:
                txn.action_succeed(
                    biller_reference="DEMO-REF-%s-%05d" % (month_start.strftime("%Y%m"), index),
                    settled_at=settled,
                )
                if rng.random() < 0.02:
                    txn.action_reverse(reason="Pembatalan atas permintaan pelanggan (demo)")
            else:
                txn.action_fail(
                    reason=rng.choice(FAILURE_REASONS),
                    settled_at=settled,
                )

    def _seed_pos(self, env, company, month_start, offset, units, partners, products,
                  pos_configs, count, rng):
        sellable = products.filtered(lambda p: p.available_in_pos)
        if not sellable or not pos_configs:
            return
        for index in range(1, count + 1):
            xmlid = "pos_%s_%03d" % (month_start.strftime("%Y%m"), index)
            if self._exists(env, xmlid):
                continue
            unit = units[rng.randrange(len(units))]
            entry = pos_configs.get(unit.id)
            if not entry:
                continue
            config, session = entry
            payment_method = config.payment_method_ids[:1]
            when = self._month_datetime(month_start, rng, index)
            partner = partners[rng.randrange(len(partners))] if rng.random() < 0.4 else None
            lines = []
            total = 0.0
            for _line in range(rng.randint(1, 3)):
                product = sellable[rng.randrange(len(sellable))]
                qty = rng.randint(1, 4)
                price = product.list_price
                subtotal = price * qty
                total += subtotal
                lines.append((0, 0, {
                    "product_id": product.id,
                    "qty": qty,
                    "price_unit": price,
                    "price_subtotal": subtotal,
                    "price_subtotal_incl": subtotal,
                    "full_product_name": product.display_name,
                    "tax_ids": [(6, 0, [])],
                }))
            order = env["pos.order"].create({
                "session_id": session.id,
                "company_id": company.id,
                "operating_unit_id": unit.id,
                "partner_id": partner.id if partner else False,
                "date_order": when,
                "amount_total": total,
                "amount_tax": 0.0,
                "amount_paid": 0.0,
                "amount_return": 0.0,
                "lines": lines,
            })
            self._tag(env, xmlid, order)
            if payment_method:
                order.add_payment({
                    "pos_order_id": order.id,
                    "amount": total,
                    "payment_date": fields.Datetime.to_string(when),
                    "payment_method_id": payment_method.id,
                })
                order.action_pos_order_paid()
            order.write({"date_order": when})
