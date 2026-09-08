-- ===========================================================================
-- 50-seed.sql — the two metadata tables that are configuration, not data.
--
-- Idempotent: every statement is an upsert keyed on the natural key, so
-- re-applying converges rather than duplicating, and an operator edit is
-- overwritten by the tracked value (the ADR is authoritative, not the
-- database -- same posture as custom_pdp_masking's noupdate="0" rules).
-- ===========================================================================

-- Created and executed as the owning role, not as the applying superuser.
SET ROLE :wh_user;

-- ---------------------------------------------------------------------------
-- Per-mart freshness SLA — GATE 2 accepted this table AS WRITTEN, including
-- its deliberate non-uniformity. PPOB is 60 s because SLA breaches are the
-- point of that view; finance is 60 min because financial reporting tolerates
-- hourly and a uniform-strict policy was explicitly rejected as wasting VPS
-- headroom. Do not "tidy" these into one number.
-- ---------------------------------------------------------------------------
INSERT INTO warehouse.mart_sla (mart_name, sla_seconds, on_breach, source_tables, note) VALUES
  ('mart_ppob_transaction',   60,  'page',
     ARRAY['ppob_transaction','ppob_biller'],
     'PPOB is operational. A stale PPOB view hides exactly the SLA breaches it exists to show.'),
  ('fct_ppob_transaction',    60,  'page',
     ARRAY['ppob_transaction','ppob_biller'],
     'Same source, same SLA as the aggregate it feeds.'),
  ('mart_stock_position',     300, 'alert',
     ARRAY['stock_move','stock_picking'],
     'Dashboard shows is_stale on breach.'),
  ('fct_stock_move',          300, 'alert',
     ARRAY['stock_move','stock_picking'], NULL),
  ('mart_sales_daily',        300, 'alert',
     ARRAY['sale_order','sale_order_line'],
     'Dashboard shows is_stale on breach.'),
  ('fct_sale_order_line',     300, 'alert',
     ARRAY['sale_order','sale_order_line'], NULL),
  ('fct_pos_order_line',      300, 'alert',
     ARRAY['pos_order','pos_order_line'],
     'POS is a revenue channel in the metric contract and shares the sales SLA.'),
  ('mart_revenue_daily',      900, 'alert',
     ARRAY['account_move','account_move_line','ppob_transaction','pos_order','pos_order_line'],
     'Widest source set of any mart: net revenue nets credit notes off invoiced revenue.'),
  ('mart_account_move_line',  3600,'alert',
     ARRAY['account_move','account_move_line'],
     'Financial reporting tolerates hourly. ADR 0001, freshness table.'),
  ('fct_account_move_line',   3600,'alert',
     ARRAY['account_move','account_move_line'], NULL),
  ('fct_sales_price_tier_line', 300, 'alert',
     ARRAY['sale_order','sale_order_line','pos_order','pos_order_line'],
     'Two channels, so the widest source set of the two sales SLAs and the tighter number.'),
  ('mart_sales_price_tier_daily', 300, 'alert',
     ARRAY['sale_order','sale_order_line','pos_order','pos_order_line'],
     'Harga HJ1-HJ9. Same SLA as mart_sales_daily: it answers the same commercial question.'),
  ('dim_partner',             3600,'alert', ARRAY['res_partner'],       'SCD2 dimension.'),
  ('dim_product',             3600,'alert', ARRAY['product_product','product_template'], 'SCD2 dimension.'),
  ('dim_company',             3600,'alert', ARRAY['res_company'],       NULL),
  ('dim_operating_unit',      3600,'alert', ARRAY['operating_unit'],    NULL)
ON CONFLICT (mart_name) DO UPDATE SET
  sla_seconds   = EXCLUDED.sla_seconds,
  on_breach     = EXCLUDED.on_breach,
  source_tables = EXCLUDED.source_tables,
  note          = EXCLUDED.note;

-- ---------------------------------------------------------------------------
-- Tenant registry.
--
-- `bct` is the real tenant: it is the Odoo database name, which is what
-- contract 05 defines _tenant_id to be.
--
-- `bct_t2` is a TEST TENANT and is flagged as one. It exists because tenant
-- isolation cannot be proven with one tenant -- "returns zero rows for another
-- tenant's data" needs another tenant to have data. It mirrors the same Odoo
-- database under a second tenant identity and, critically, a DIFFERENT SALT,
-- which is also what makes contract 01's cross-tenant separation property
-- testable: the same partner must hash differently in the two tenants.
--
-- It is NOT a second Odoo database. Standing one up to develop against is
-- forbidden by master prompt §3.0 / anti-pattern §7.1, and this achieves the
-- isolation proof without it. is_test_tenant is surfaced on dim_tenant so no
-- dashboard mistakes it for production volume.
-- ---------------------------------------------------------------------------
INSERT INTO warehouse.tenant_registry
  (tenant_id, display_name, source_database, slot_name, publication, mask_salt_env, is_test_tenant, active) VALUES
  ('bct',    'ATHERA (primary)',        'bct', 'bct_slot_bct',    'bct_cdc_bct',    'WAREHOUSE_MASK_SALT_BCT',     false, true),
  -- bct_fixture, NOT bct. Repointed on 2026-09-04 so the isolation fixture would
  -- stop being rebuilt out of the production tenant it exists to be distinguished
  -- from. That change was made in the DATABASE and never here, and this file is
  -- re-applied by warehouse-apply.sh on every `make up-analytics` with
  -- `ON CONFLICT DO UPDATE SET source_database = EXCLUDED.source_database` --
  -- so the seed silently reverted the registry on the next bring-up, gen-fdw
  -- dutifully repointed odoo_src_bct_t2 back at `bct`, and load-fixture then
  -- loaded 65 rows of PRODUCTION data under _tenant_id='bct_t2' instead of the
  -- fixture's 2115. Measured on 2026-09-05, not reasoned about. The tracked DDL
  -- has to agree with the running system or warehouse-apply.sh is a drift
  -- generator rather than a drift detector.
  ('bct_t2', 'ATHERA isolation tenant', 'bct_fixture', 'bct_slot_bct_t2', 'bct_cdc_bct_t2', 'WAREHOUSE_MASK_SALT_DEFAULT', true,  true),
  -- ndi, onboarded 2026-09-05. Its own database, its own slot, its own publication and its
  -- own salt: mask_salt_env is WAREHOUSE_MASK_SALT_NDI and NOT the DEFAULT that bct_t2 uses,
  -- because a second tenant sharing DEFAULT makes hmac(value, DEFAULT) a join key ACROSS
  -- tenants -- RLS still holds the rows apart, but anyone holding two tenants' output can
  -- link the same natural person. compose/insight.yml's cdc-ndi forwards that variable with
  -- `:?`, so an unset salt is a startup failure rather than a silent downgrade.
  ('ndi',    'NDI (pabrik pakan ternak)', 'ndi', 'bct_slot_ndi', 'bct_cdc_ndi', 'WAREHOUSE_MASK_SALT_NDI', false, true)
ON CONFLICT (tenant_id) DO UPDATE SET
  display_name    = EXCLUDED.display_name,
  source_database = EXCLUDED.source_database,
  slot_name       = EXCLUDED.slot_name,
  publication     = EXCLUDED.publication,
  mask_salt_env   = EXCLUDED.mask_salt_env,
  is_test_tenant  = EXCLUDED.is_test_tenant,
  active          = EXCLUDED.active;

RESET ROLE;
