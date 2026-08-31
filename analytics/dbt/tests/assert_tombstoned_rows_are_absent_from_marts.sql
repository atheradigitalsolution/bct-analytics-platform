{{ config(severity='error') }}

-- A row whose latest landing version is a tombstone must not appear in a mart.
--
-- ADR 0001: every decoded DELETE lands as `_op='D'`, the landing zone stays
-- append-only, and marts filter to the latest non-deleted version per key - so
-- a delete in Odoo removes the row from the mart within the freshness SLA.
--
-- The subtle bug this catches is filtering tombstones BEFORE ranking rather
-- than after: that resurrects the previous version of a deleted record, which
-- is worse than leaving the delete unapplied, because the row then looks live
-- and current. raw_latest ranks first and checks _op second; this asserts the
-- result rather than trusting the macro.

with tombstoned as (
    select
        r._tenant_id as tenant_id,
        r.id as sale_order_line_id
    from {{ source('raw', 'sale_order_line') }} as r
    where
        r._op = 'D'
        and r._row_id = (
            select max(r2._row_id)
            from {{ source('raw', 'sale_order_line') }} as r2
            where
                r2._tenant_id = r._tenant_id
                and r2.id = r.id
        )
)

select
    t.tenant_id,
    t.sale_order_line_id
from tombstoned as t
join {{ ref('fct_sale_order_line') }} as f
    on
        t.tenant_id = f.tenant_id
        and t.sale_order_line_id = f.sale_order_line_id
