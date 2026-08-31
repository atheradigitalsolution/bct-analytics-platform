-- Unit cost per product PER COMPANY, unpacked from Odoo's company_dependent map.
--
-- GRAIN: (tenant_id, product_key, company_id). That is the grain the DATA has,
-- and it is why this is a separate model rather than a column on dim_product.
--
-- WHY NOT A COLUMN ON dim_product. product_product.standard_price is
-- company_dependent in Odoo 19, so the stored value is a map keyed by company
-- id - {"1": 42000.0} - not a scalar. Putting it on dim_product would need one
-- of two wrong things:
--   * pick one company's cost and call it "the" cost, which is silently wrong
--     the moment a tenant has two companies with different costs; or
--   * explode dim_product to one row per company, which breaks product_key
--     uniqueness, breaks the SCD2 version key, and breaks the relationships
--     test on every fact that points at it.
-- Contract 01's ruling on res.partner.barcode is the same principle: a map
-- keyed by something other than the row's own subject is never a scalar.
--
-- WHY NOT list_price, WITH THE ERROR MEASURED RATHER THAN ASSERTED.
-- list_price is the SALES price. Valuing inventory at it overstates by the
-- entire margin - the same shape as summing PPOB pass_through_amount and
-- calling it revenue: a plausible column that is wrong by a large factor.
--
-- On this database, measured, and reproduced after a full re-seed:
--
--     sum(list_price)     2 645 000
--     sum(unit_cost)      1 814 000
--     overstatement          1.46x
--
-- The number is here on purpose. "We should use standard_price" is a
-- preference somebody can casually undo; "list_price overstates inventory by
-- 46% on our own data" is a measurement they have to argue with.
--
-- TYPE 1, deliberately. This is the CURRENT cost. Cost history would need
-- standard_price in the SCD2 snapshot's check_cols, which is a real design
-- question (a cost revaluation would then create a new product version, and
-- every as-of join would start returning two rows for the revaluation date).
-- Not doing it silently: if historical valuation is ever needed, that is a
-- change worth designing rather than a column to add.
--
-- NOT VERIFIED, stated here so it is not mistaken for tested: the
-- NULL-valuation branch in mart_stock_position (has_unit_cost = false) is
-- written and reviewed but has never executed against real data. Both
-- products without a standard_price in this seed - Tips and Down Payment
-- (POS) - are non-storable, so they have no stock moves and never reach a
-- position row. That correlation is structural rather than accidental: a
-- product with no cost is usually a service. Exercising it needs a seeded
-- STORABLE product with stock moves and no standard_price.

with unpacked as (

    select
        p.tenant_id,
        p.product_id,
        c.key as company_key_text,
        c.value as unit_cost_text
    from {{ ref('stg_product_product') }} as p
    cross join
        lateral jsonb_each_text(
            -- jsonb_each_text raises on a non-object. A company_dependent column
            -- should always hold an object or NULL, but "should" is not a
            -- guarantee about a column another system writes.
            case
                when jsonb_typeof(p.standard_price) = 'object' then p.standard_price
                else '{}'::jsonb
            end
        ) as c
    -- Keys are company ids. Anything else is not a company-dependent map and
    -- must not be cast to integer - it would abort the whole model rather than
    -- skip one bad row.
    where c.key ~ '^[0-9]+$'

)

select
    {{ surrogate_key(['u.tenant_id', 'u.product_id', 'u.company_key_text']) }} as product_cost_key,
    {{ surrogate_key(['u.tenant_id', 'u.product_id']) }} as product_key,
    {{ surrogate_key(['u.tenant_id', 'u.company_key_text']) }} as company_key,
    u.tenant_id,
    u.product_id,
    u.company_key_text::integer as company_id,
    u.unit_cost_text::numeric as unit_cost
from unpacked as u
