{{ config(materialized='view') }}

-- Product variants - the grain fct_* joins on.
--
-- Staging does exactly three things and no more: deduplicate to the latest
-- version per (tenant, id), drop rows whose latest version is a tombstone, and
-- rename `_tenant_id` to `tenant_id`. All three live in the raw_latest macro so
-- they cannot drift between models. No business logic here.

with latest as (
    {{ raw_latest('product_product') }}
)

select
    _tenant_id as tenant_id,
    id as product_id,
    product_tmpl_id,
    default_code,
    barcode,
    active,
    create_date,
    write_date
from latest
