-- GRAIN: (tenant_id, product_key, company_id, operating_unit_id)
--
-- Net position derived from completed moves, not from stock.quant. That is a
-- deliberate choice and it is worth being explicit about the trade: quant is
-- Odoo's authoritative on-hand figure, but it is a mutable snapshot with no
-- history, so a warehouse built on it can answer "how much now" and nothing
-- else. Summing signed moves gives the same answer AND makes every historical
-- position reconstructible, which is the point of having a warehouse.
--
-- Only `done` moves count. A reserved or waiting move has not changed stock.

select
    tenant_id,
    product_key,
    company_key,
    operating_unit_key,
    company_id,
    operating_unit_id,
    product_id,
    sum(case when is_in then quantity else 0 end) as qty_in,
    sum(case when is_out then quantity else 0 end) as qty_out,
    sum(signed_quantity) as net_qty,
    count(*) as move_count,
    count(*) filter (where is_inventory) as inventory_adjustment_count,
    max(move_datetime) as last_move_at
from {{ ref('fct_stock_move') }}
where state = 'done'
group by 1, 2, 3, 4, 5, 6, 7
