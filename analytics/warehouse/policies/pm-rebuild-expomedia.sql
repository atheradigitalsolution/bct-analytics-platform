-- pm-rebuild-expomedia.sql — rebuild union policy_master untuk tenant expomedia.
-- Sesuai instruksi compose/insight.yml: "WHEN A TENANT IS ADDED: rebuild
-- policy_master's union, then re-prove the superset BEFORE running sync-policy."
-- Jalankan: docker exec -i odoo19-bct-postgres psql -U odoo -d policy_master \
--             -v ON_ERROR_STOP=1 < analytics/warehouse/policies/pm-rebuild-expomedia.sql
BEGIN;

-- 1) Union skema: 54 kolom expomedia yang belum ada (dari modul crm, hr_expense,
--    sale_timesheet, custom_pph_witholding, custom_coretax_bupot, report_templates, dll.)
ALTER TABLE public.account_move ADD COLUMN IF NOT EXISTS "custom_match_result_id" integer;
ALTER TABLE public.account_move ADD COLUMN IF NOT EXISTS "custom_match_status" character varying;
ALTER TABLE public.account_move ADD COLUMN IF NOT EXISTS "x_custom_coretax_kode_status" character varying(2);
ALTER TABLE public.account_move ADD COLUMN IF NOT EXISTS "x_custom_coretax_replaced_by_id" integer;
ALTER TABLE public.account_move ADD COLUMN IF NOT EXISTS "x_custom_coretax_replacement_of_id" integer;
ALTER TABLE public.account_move ADD COLUMN IF NOT EXISTS "x_custom_ic_mirror_id" integer;
ALTER TABLE public.account_move ADD COLUMN IF NOT EXISTS "x_custom_ic_rule_id" integer;
ALTER TABLE public.account_move ADD COLUMN IF NOT EXISTS "x_custom_ic_source_id" integer;
ALTER TABLE public.account_move ADD COLUMN IF NOT EXISTS "x_custom_total_withheld" numeric;
ALTER TABLE public.account_move ADD COLUMN IF NOT EXISTS "x_custom_withholding_move_id" integer;
ALTER TABLE public.account_move_line ADD COLUMN IF NOT EXISTS "expense_id" integer;
ALTER TABLE public.account_move_line ADD COLUMN IF NOT EXISTS "x_custom_tax_label" character varying;
ALTER TABLE public.account_move_line ADD COLUMN IF NOT EXISTS "x_custom_withholding_category_id" integer;
ALTER TABLE public.product_template ADD COLUMN IF NOT EXISTS "can_be_expensed" boolean;
ALTER TABLE public.product_template ADD COLUMN IF NOT EXISTS "service_upsell_threshold" double precision;
ALTER TABLE public.product_template ADD COLUMN IF NOT EXISTS "x_custom_withholding_category_id" integer;
ALTER TABLE public.res_company ADD COLUMN IF NOT EXISTS "brand_accent_color" character varying;
ALTER TABLE public.res_company ADD COLUMN IF NOT EXISTS "expense_journal_id" integer;
ALTER TABLE public.res_company ADD COLUMN IF NOT EXISTS "home_announcement_active" boolean;
ALTER TABLE public.res_company ADD COLUMN IF NOT EXISTS "home_announcement_html" text;
ALTER TABLE public.res_company ADD COLUMN IF NOT EXISTS "internal_project_id" integer;
ALTER TABLE public.res_company ADD COLUMN IF NOT EXISTS "leave_timesheet_task_id" integer;
ALTER TABLE public.res_company ADD COLUMN IF NOT EXISTS "project_time_mode_id" integer;
ALTER TABLE public.res_company ADD COLUMN IF NOT EXISTS "report_bank_details" text;
ALTER TABLE public.res_company ADD COLUMN IF NOT EXISTS "report_footer_note" character varying;
ALTER TABLE public.res_company ADD COLUMN IF NOT EXISTS "report_show_product_name" boolean;
ALTER TABLE public.res_company ADD COLUMN IF NOT EXISTS "timesheet_encode_uom_id" integer;
ALTER TABLE public.res_company ADD COLUMN IF NOT EXISTS "x_custom_coretax_user_id" character varying;
ALTER TABLE public.res_company ADD COLUMN IF NOT EXISTS "x_custom_ic_enabled" boolean;
ALTER TABLE public.res_company ADD COLUMN IF NOT EXISTS "x_custom_nitku_suffix" character varying;
ALTER TABLE public.res_company ADD COLUMN IF NOT EXISTS "x_custom_npwp_penandatangan" character varying;
ALTER TABLE public.res_partner ADD COLUMN IF NOT EXISTS "credit_limit_check_method" character varying;
ALTER TABLE public.res_partner ADD COLUMN IF NOT EXISTS "custom_credit_limit" numeric;
ALTER TABLE public.res_partner ADD COLUMN IF NOT EXISTS "custom_credit_limit_check_method" character varying;
ALTER TABLE public.res_partner ADD COLUMN IF NOT EXISTS "custom_followup_last_sent" timestamp without time zone;
ALTER TABLE public.res_partner ADD COLUMN IF NOT EXISTS "custom_followup_level_id" integer;
ALTER TABLE public.res_partner ADD COLUMN IF NOT EXISTS "custom_followup_next_date" date;
ALTER TABLE public.res_partner ADD COLUMN IF NOT EXISTS "x_custom_birth_date" date;
ALTER TABLE public.res_partner ADD COLUMN IF NOT EXISTS "x_custom_birth_place" character varying;
ALTER TABLE public.res_partner ADD COLUMN IF NOT EXISTS "x_custom_foreign_counterparty" boolean;
ALTER TABLE public.res_partner ADD COLUMN IF NOT EXISTS "x_custom_has_valid_npwp" boolean;
ALTER TABLE public.res_partner ADD COLUMN IF NOT EXISTS "x_custom_kitas" character varying;
ALTER TABLE public.res_partner ADD COLUMN IF NOT EXISTS "x_custom_nik" character varying;
ALTER TABLE public.res_partner ADD COLUMN IF NOT EXISTS "x_custom_nitku" character varying;
ALTER TABLE public.res_partner ADD COLUMN IF NOT EXISTS "x_custom_npwp" character varying;
ALTER TABLE public.res_partner ADD COLUMN IF NOT EXISTS "x_custom_npwp_status" character varying;
ALTER TABLE public.res_partner ADD COLUMN IF NOT EXISTS "x_custom_passport" character varying;
ALTER TABLE public.res_partner ADD COLUMN IF NOT EXISTS "x_custom_pkp" boolean;
ALTER TABLE public.res_partner ADD COLUMN IF NOT EXISTS "x_custom_ptkp" character varying;
ALTER TABLE public.res_partner ADD COLUMN IF NOT EXISTS "x_custom_tin" character varying;
ALTER TABLE public.sale_order ADD COLUMN IF NOT EXISTS "custom_credit_check_log_id" integer;
ALTER TABLE public.sale_order ADD COLUMN IF NOT EXISTS "opportunity_id" integer;
ALTER TABLE public.sale_order_line ADD COLUMN IF NOT EXISTS "has_displayed_warning_upsell" boolean;
ALTER TABLE public.sale_order_line ADD COLUMN IF NOT EXISTS "remaining_hours" double precision;

-- 2) Satu baris klasifikasi yang belum ada sama sekali
INSERT INTO pdp_field_classification (model_name, field_name, pdp_class, legal_basis, drop_to_null, active)
SELECT 'sale.order','opportunity_id','internal','Not personal data - business record',false,true
WHERE NOT EXISTS (SELECT 1 FROM pdp_field_classification WHERE model_name='sale.order' AND field_name='opportunity_id');

-- 3) Ruling user 2026-09-11 (onboarding expomedia): field identitas orang = sensitive
--    (HMAC di warehouse), tanggal lahir (DATE, tak bisa HMAC) = secret (drop).
--    Lebih ketat dari seed custom_pdp_core (internal). Hanya expomedia yang punya
--    kolom-kolom ini secara fisik, jadi dampak ekstraksi terbatas ke tenant itu.
UPDATE pdp_field_classification SET pdp_class='sensitive', drop_to_null=false,
  notes=COALESCE(notes,'')||' [ruling user 2026-09-11: sensitive/HMAC utk warehouse]'
WHERE model_name='res.partner' AND field_name IN
  ('x_custom_nik','x_custom_birth_place','x_custom_kitas','x_custom_nitku',
   'x_custom_npwp','x_custom_npwp_status','x_custom_passport','x_custom_ptkp','x_custom_tin');
UPDATE pdp_field_classification SET pdp_class='sensitive', drop_to_null=false,
  notes=COALESCE(notes,'')||' [ruling user 2026-09-11]'
WHERE model_name='res.company' AND field_name='x_custom_npwp_penandatangan';
UPDATE pdp_field_classification SET pdp_class='secret',
  notes=COALESCE(notes,'')||' [ruling user 2026-09-11: DATE tak bisa HMAC -> drop]'
WHERE model_name='res.partner' AND field_name='x_custom_birth_date';

-- 4) Verifikasi dalam transaksi
SELECT 'kolom_baru_res_partner', count(*) FROM information_schema.columns
  WHERE table_name='res_partner' AND column_name IN ('x_custom_nik','x_custom_npwp');
SELECT 'sensitive_rows', count(*) FROM pdp_field_classification
  WHERE pdp_class='sensitive' AND model_name IN ('res.partner','res.company')
    AND field_name LIKE 'x\_custom\_%';

COMMIT;
