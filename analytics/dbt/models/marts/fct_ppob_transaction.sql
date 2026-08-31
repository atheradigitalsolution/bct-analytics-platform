-- GRAIN: one PPOB transaction. (tenant_id, ppob_transaction_id) is unique.
--
-- REVENUE SEMANTICS, and this is the single easiest thing to get wrong in this
-- warehouse: `amount` is pass-through - collected from the customer and owed to
-- the biller - and is NOT revenue. The revenue of a PPOB row is `commission`.
-- A typical row is 100 000 IDR of amount against 1 500 IDR of commission, so a
-- mart that sums amount and calls it revenue overstates it by roughly 40x
-- (custom_ppob/MODULE_KNOWLEDGE.md §2). The column is named
-- `commission_revenue` here so the mistake has to be deliberate.
--
-- sla_target_seconds is SNAPSHOT ONTO THE FACT. The module computes
-- sla_breached against the biller's CURRENT target, so raising a target
-- retroactively un-breaches history; the module says so and says the warehouse
-- must snapshot the target if it wants history to stay true. It does.

select
    {{ surrogate_key(['t.tenant_id', 't.ppob_transaction_id']) }} as ppob_transaction_key,
    t.tenant_id,
    t.ppob_transaction_id,
    t.transaction_name,

    t.requested_at::date as date_day,
    t.requested_at,
    t.settled_at,

    {{ surrogate_key(['t.tenant_id', 't.partner_id']) }} as partner_key,
    {{ surrogate_key(['t.tenant_id', 't.product_id']) }} as product_key,
    {{ surrogate_key(['t.tenant_id', 't.biller_id']) }} as biller_key,
    {{ surrogate_key(['t.tenant_id', 't.company_id']) }} as company_key,
    {{ surrogate_key(['t.tenant_id', 'coalesce(t.operating_unit_id, -1)']) }} as operating_unit_key,
    {{ surrogate_key(['t.tenant_id', 't.requested_at::date']) }} as date_key,

    t.partner_id,
    t.product_id,
    t.biller_id,
    b.biller_code,
    b.biller_category,
    t.company_id,
    coalesce(t.operating_unit_id, -1) as operating_unit_id,
    t.currency_id,

    t.state,
    t.customer_ref,      -- `sensitive`: already an HMAC digest, still supports repeat-customer counts
    t.customer_name,     -- `personal`:  already an HMAC digest
    t.biller_reference,

    t.amount as pass_through_amount,
    t.admin_fee,
    t.commission as commission_revenue,
    t.total_amount as customer_paid_amount,
    (t.admin_fee - t.commission) as channel_share,

    t.sla_seconds,
    t.sla_breached,
    b.sla_target_seconds as sla_target_seconds_at_build,
    (t.state = 'success') as is_success,
    (t.state = 'failed') as is_failed,
    (t.state = 'reversed') as is_reversed
from {{ ref('stg_ppob_transaction') }} as t
join {{ ref('stg_ppob_biller') }} as b
    on
        t.tenant_id = b.tenant_id
        and t.biller_id = b.biller_id
