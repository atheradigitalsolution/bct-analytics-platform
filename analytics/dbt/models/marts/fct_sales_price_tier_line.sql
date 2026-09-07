-- GRAIN: one sold line, from either channel.
-- (tenant_id, sales_channel, source_line_id) is unique.
--
-- WHY THIS FACT EXISTS SEPARATELY FROM fct_sale_order_line AND
-- fct_pos_order_line. A feed mill sells the same sack at nine different prices
-- (HJ1..HJ9) depending on who is buying, and the question "which tier did this
-- line actually go out at, and what did it cost us" cannot be answered by
-- looking at either channel alone: the same customer buys on a Sales Order on
-- terms and over the POS in cash. So the two channels are UNIONed here, once,
-- rather than in every consumer.
--
-- WHY THE TIER IS SNAPSHOTTED AND NOT RECONSTRUCTED. Odoo 19 does not store
-- pricelist_item_id on sale.order.line, so there is no way to work out after
-- the fact which tier a price came from. custom_ndi_pricing writes the tier and
-- the cost of goods onto the line at the moment the price is computed, and that
-- snapshot is the only truthful source. A line whose tier was not recorded
-- keeps hj_level NULL and is NOT dropped - is_hj_recorded is what lets a
-- consumer say how much of the total it could not attribute.
--
-- DIRECTION OF THE WATERFALL, verified rather than assumed. Measured on ndi
-- before this model was written: `distributor` partners carry
-- ndi_default_hj_level 5-6 and `retail` carries 1, and the average price_unit
-- falls as the tier number rises (358_319 at tier 2 -> 340_214 at tier 5). So a
-- HIGHER tier number is a CHEAPER price, and "below the customer's default
-- tier" is hj_level > partner_default_hj_level. Getting this backwards would
-- have inverted the panel while leaving it entirely plausible.
--
-- DO NOT SUM THIS WITH revenue_net. mart_revenue_daily already carries a `pos`
-- channel; adding the two double-counts every POS line.

with sale_lines as (

    select
        'sale' as sales_channel,
        f.tenant_id,
        f.sale_order_line_id as source_line_id,
        f.sale_order_id as source_order_id,
        f.order_name as source_order_name,
        f.date_day,
        f.date_key,
        f.partner_key,
        f.product_key,
        f.company_key,
        f.operating_unit_key,
        f.partner_id,
        f.product_id,
        f.company_id,
        f.operating_unit_id,
        f.product_uom_qty as qty,
        f.price_unit,
        f.discount,
        f.price_subtotal as amount_untaxed,
        f.price_total as amount_total,
        l.ndi_hj_level as hj_level_raw,
        l.ndi_hpp_snapshot as hpp_unit
    from {{ ref('fct_sale_order_line') }} as f
    join {{ ref('stg_sale_order_line') }} as l
        on
            f.tenant_id = l.tenant_id
            and f.sale_order_line_id = l.sale_order_line_id

),

pos_lines as (

    select
        'pos' as sales_channel,
        f.tenant_id,
        f.pos_order_line_id as source_line_id,
        f.pos_order_id as source_order_id,
        f.pos_order_name as source_order_name,
        f.date_day,
        f.date_key,
        f.partner_key,
        f.product_key,
        f.company_key,
        f.operating_unit_key,
        f.partner_id,
        f.product_id,
        f.company_id,
        f.operating_unit_id,
        f.qty,
        f.price_unit,
        f.discount,
        f.price_subtotal as amount_untaxed,
        -- price_subtotal_incl is the POS analogue of price_total. Naming them
        -- the same thing here is what makes the UNION legitimate; leaving the
        -- Odoo names would have made every downstream sum pick one arbitrarily.
        f.price_subtotal_incl as amount_total,
        l.ndi_hj_level as hj_level_raw,
        l.ndi_hpp_snapshot as hpp_unit
    from {{ ref('fct_pos_order_line') }} as f
    join {{ ref('stg_pos_order_line') }} as l
        on
            f.tenant_id = l.tenant_id
            and f.pos_order_line_id = l.pos_order_line_id

),

both_channels as (

    select * from sale_lines
    union all
    select * from pos_lines

),

typed as (

    select
        b.*,
        -- ndi_hj_level is a Selection field and therefore varchar in Postgres.
        -- Cast defensively: a value that is not a bare integer becomes NULL and
        -- is then reported by is_hj_recorded, rather than aborting the model.
        case
            when b.hj_level_raw ~ '^[1-9]$' then b.hj_level_raw::integer
        end as hj_level
    from both_channels as b

)

select
    {{ surrogate_key(['t.tenant_id', 't.sales_channel', 't.source_line_id']) }}
        as sales_price_tier_line_key,
    t.tenant_id,
    t.sales_channel,
    t.source_line_id,
    t.source_order_id,
    t.source_order_name,
    t.date_day,
    t.date_key,

    t.partner_key,
    t.product_key,
    t.company_key,
    t.operating_unit_key,
    t.partner_id,
    t.product_id,
    t.company_id,
    t.operating_unit_id,

    t.hj_level,
    -- Derived, never seeded. A seed in `marts` would have to carry tenant_id to
    -- pass assert_every_mart_carries_tenant_id, and a label for the number 3 is
    -- not tenant data. dbt_project.yml states the same rule for id_public_holiday.
    case when t.hj_level is not null then 'HJ' || t.hj_level::text end
        as hj_level_label,
    (t.hj_level is not null) as is_hj_recorded,

    -- Commercial segmentation that survives PDP masking. See stg_res_partner.
    p.ndi_customer_type as customer_type,
    p.ndi_sales_region as sales_region,
    p.ndi_default_hj_level as partner_default_hj_level,
    -- NULL, not false, when either side is unknown: "we cannot tell" and "the
    -- line was priced correctly" are different answers and a boolean that
    -- collapses them is how a discipline metric quietly understates itself.
    case
        when t.hj_level is null or p.ndi_default_hj_level is null then null
        else t.hj_level > p.ndi_default_hj_level
    end as is_below_default_tier,

    t.qty,
    t.price_unit,
    t.discount,
    t.amount_untaxed,
    t.amount_total,

    t.hpp_unit,
    (t.hpp_unit is not null) as has_hpp,
    -- NULL propagates on purpose. sum() skips NULL silently, so a mart that
    -- coalesced this to 0 would report a margin equal to full revenue for every
    -- line whose cost was never snapshotted - and it would look like a good
    -- month. has_hpp is the companion that lets a consumer say how much of the
    -- total is unattributed; the pattern is mart_stock_position.has_unit_cost.
    t.qty * t.hpp_unit as hpp_amount,
    t.amount_untaxed - (t.qty * t.hpp_unit) as gross_margin
from typed as t
left join {{ ref('stg_res_partner') }} as p
    on
        t.tenant_id = p.tenant_id
        and t.partner_id = p.partner_id
