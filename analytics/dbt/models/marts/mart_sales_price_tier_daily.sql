-- GRAIN: (tenant_id, date_day, operating_unit_id, company_id, hj_level,
--         sales_channel, product_key, partner_key)
--
-- Aggregated to the LOWEST grain the metric registry declares as a legal
-- group-by, not to the narrowest grain one panel happens to need. A mart rolled
-- up past a declared dimension cannot answer its own contract, and the API then
-- has to fall back to the fact table - which is the whole thing a mart exists
-- to avoid. Same reasoning as mart_sales_daily.
--
-- hj_level is part of the grain and is NULLABLE. Lines whose tier was never
-- snapshotted collapse into one group per day rather than disappearing, and
-- lines_without_hj_level states how many they are. Dropping them would make
-- every tier percentage add to 100 % of a total that is not the real total.
--
-- RATIOS ARE NOT PRE-COMPUTED HERE. gross_margin_pct and
-- sales_below_default_tier_pct are declared in the registry as `ratio`
-- aggregations over sums, so they are computed after filtering. A ratio stored
-- per row would be averaged by any group-by, which weights a 10-sack line the
-- same as a 10-tonne line.

select
    tenant_id,
    date_day,
    operating_unit_id,
    company_id,
    hj_level,
    hj_level_label,
    sales_channel,
    product_key,
    partner_key,
    customer_type,
    sales_region,
    operating_unit_key,
    company_key,
    date_key,

    count(*) as line_count,
    count(distinct source_order_id) as order_count,
    sum(qty) as qty,
    sum(amount_untaxed) as amount_untaxed,
    sum(amount_total) as amount_total,
    sum(amount_total) - sum(amount_untaxed) as amount_tax,

    sum(hpp_amount) as hpp_amount,
    sum(gross_margin) as gross_margin,

    -- The companions. Every one of these counts lines the measures above could
    -- NOT account for, so a consumer can qualify a total instead of presenting
    -- a partial figure as a whole one.
    count(*) filter (where not has_hpp) as lines_without_hpp,
    count(*) filter (where not is_hj_recorded) as lines_without_hj_level,
    count(*) filter (where is_below_default_tier) as lines_below_default_tier,
    count(*) filter (where is_below_default_tier is null)
        as lines_default_tier_unknown
from {{ ref('fct_sales_price_tier_line') }}
group by 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14
