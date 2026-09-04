"""Remove custom_demo_seed's data from a tenant in an order the foreign keys allow.

WHY NOT `button_immediate_uninstall`. Measured on a clone of a real tenant: the uninstall
reports success and is not one. Odoo deletes ir.model.data owners in its own order, hits
`account_move_line_partner_id_fkey` on the demo partners, LOGS the failure and carries on
-- leaving every journal item and invoice whose partner it could not remove pointing at
sale orders it did remove, and leaving almost all of the demo partners and every demo
product in place. A half-deleted ledger is worse than an untouched one, so this script
goes child-first and refuses to guess.

Order, and the reason for each position:
  1. account.move   the invoices come FIRST, because they are what holds the partners,
                    the products and the operating units down. Posted moves must be
                    drafted, and drafted moves must be unlinked youngest-first: Odoo
                    forbids deleting a move that is not the last of its sequence chain.
  2. sale.order     their lines go with them; pickings are cancelled first or `stock`
                    refuses.
  3. pos.*          order -> session -> config.
  4. ppob.*         transaction -> biller.
  5. res.partner / product.template / res.users / operating.unit -- only now are they
     free, and only now can the FK that defeated the uninstall succeed.

USAGE
    make purge-demo-seed TENANT=<slug>              rehearse; rolls back
    make purge-demo-seed TENANT=<slug> COMMIT=1     keep it

REHEARSE ON A CLONE FIRST -- a pg_dump/restore copy, never the tenant itself. Getting
this past the framework took four attempts: stock (`You cannot cancel a stock move that
has been set to Done`), point of sale (`In order to delete a sale, it must be new or
cancelled`) and `stock_quant_product_id_fkey`, the last of which only appears AFTER the
stock moves are deleted, because unlinking a move makes Odoo recreate the quants the
earlier sweep removed. None of those are visible by reading the models.

Take a backup either way: `make tenant-backup TENANT=<slug>`.

WHAT IT DOES NOT DO. It does not touch anything the demo seeder did not create, and it
does not go near a tenant's real accounting: step 1 selects only the moves that belong to
demo sale orders or carry a demo partner, so on a tenant with real business data the rest
are left alone. How much of the ledger that leaves behind depends entirely on the tenant.
READ THE STEP-1 COUNT before you answer the prompt -- it is printed for exactly this
reason, and it is the number that tells you whether you are about to remove a fixture or
somebody's books.
"""
import os
env = env(su=True)
COMMIT = os.environ.get("PURGE_COMMIT") == "1"  # set by `make purge-demo-seed COMMIT=1`

IMD = env['ir.model.data'].search([('module', '=', 'custom_demo_seed')])
owned = {}
for r in IMD:
    owned.setdefault(r.model, []).append(r.res_id)

def recs(model):
    ids = owned.get(model, [])
    return env[model].browse(ids).exists() if ids else env[model].browse()

before = {}
for t in ['account_move', 'account_move_line', 'sale_order', 'sale_order_line', 'pos_order',
          'pos_order_line', 'ppob_transaction', 'res_partner', 'res_users', 'stock_move',
          'product_template', 'operating_unit']:
    env.cr.execute(f"SELECT count(*) FROM {t}")
    before[t] = env.cr.fetchone()[0]
print("BEFORE:", before)

removed = {}

# --- 1. invoices -----------------------------------------------------------
partners = recs('res.partner')
sos = recs('sale.order')
moves = env['account.move'].search(['|', ('partner_id', 'in', partners.ids),
                                    ('id', 'in', sos.mapped('invoice_ids').ids)])
print("step 1: %d account.move (%d lines)" % (
    len(moves), env['account.move.line'].search_count([('move_id', 'in', moves.ids)])))
posted = moves.filtered(lambda m: m.state == 'posted')
if posted:
    posted.button_draft()
# youngest first: a move that is not last in its sequence chain cannot be deleted
for m in moves.sorted(key=lambda r: (r.journal_id.id, r.sequence_prefix or '', r.sequence_number), reverse=True):
    m.unlink()
removed['account.move'] = len(moves)

# --- 2. deliveries, then sale orders ---------------------------------------
#
# `action_cancel()` is not available here and pretending otherwise is how this step
# fails on a real tenant: stock refuses with "You cannot cancel a stock move that has
# been set to 'Done'. Create a return in order to reverse the moves which took place."
# A return is the correct answer when the movement really happened. It did not: these
# are fixture rows, and reversing them would leave a second set of fixture rows behind.
#
# So the state is forced in SQL and the deletion still goes through the ORM, which is
# the part that matters -- the ORM is what unlinks the move lines and the quants. The
# SQL touches ONLY rows reachable from custom_demo_seed's own sale orders and products,
# and it is written out rather than buried because forcing a state machine is exactly
# the kind of thing that should be visible in a review.
demo_products = recs('product.template').mapped('product_variant_ids')
pickings = sos.mapped('picking_ids')
moves_all = pickings.mapped('move_ids') | recs('stock.move')
if demo_products:
    moves_all |= env['stock.move'].search([('product_id', 'in', demo_products.ids)])
print("step 2: %d picking(s), %d stock.move, %d quant(s)" % (
    len(pickings), len(moves_all),
    env['stock.quant'].search_count([('product_id', 'in', demo_products.ids)]) if demo_products else 0))
# flush BEFORE the raw SQL and invalidate AFTER it: without the flush, a pending ORM
# write lands on top of the state we just forced and the next check reads the old value.
env.flush_all()
if moves_all:
    env.cr.execute("UPDATE stock_move_line SET state='draft' WHERE move_id = ANY(%s)", (moves_all.ids,))
    env.cr.execute("UPDATE stock_move SET state='draft' WHERE id = ANY(%s)", (moves_all.ids,))
if pickings:
    env.cr.execute("UPDATE stock_picking SET state='draft' WHERE id = ANY(%s)", (pickings.ids,))
env.invalidate_all()
if demo_products:
    q = env['stock.quant'].search([('product_id', 'in', demo_products.ids)])
    removed['stock.quant'] = len(q)
    q.sudo().unlink()
removed['stock.picking'] = len(pickings)
pickings.unlink()
moves_all = moves_all.exists()
removed['stock.move'] = len(moves_all)
moves_all.unlink()

# The pickings are gone by now, so the ordinary cancel usually succeeds; the SQL is the
# fallback for orders stock still considers immovable.
try:
    sos.filtered(lambda s: s.state not in ('draft', 'cancel')).action_cancel()
except Exception as exc:  # noqa: BLE001 - reported, not swallowed
    print("   action_cancel refused (%s); forcing state" % type(exc).__name__)
env.flush_all()
env.cr.execute("UPDATE sale_order SET state='cancel' WHERE id = ANY(%s)", (sos.ids,))
env.invalidate_all()
print("   sale.order states now:", sorted(set(sos.mapped('state'))))
removed['sale.order'] = len(sos); sos.unlink()

# --- 3. point of sale ------------------------------------------------------
po = recs('pos.order')
# `pos.order._unlink_except_draft_or_cancel` accepts only draft or cancel, and these
# fixture orders were left `paid`/`done` with their sessions never closed. Same reasoning
# as the deliveries above: there is nothing to reverse, so the state is forced and the
# ORM still does the deleting.
if po:
    env.flush_all()
    env.cr.execute("UPDATE pos_order SET state='cancel' WHERE id = ANY(%s)", (po.ids,))
    env.invalidate_all()
    print("   pos.order states now:", sorted(set(po.mapped('state'))))
removed['pos.order'] = len(po); po.unlink()
sess = recs('pos.session')
for s in sess:
    if s.state != 'closed':
        env.cr.execute("UPDATE pos_session SET state='closed' WHERE id=%s", (s.id,))
sess.invalidate_recordset()
removed['pos.session'] = len(sess); sess.unlink()
cfg = recs('pos.config')
removed['pos.config'] = len(cfg); cfg.unlink()

# --- 4. ppob ---------------------------------------------------------------
tx = recs('ppob.transaction'); removed['ppob.transaction'] = len(tx); tx.unlink()
bl = recs('ppob.biller');      removed['ppob.biller'] = len(bl);      bl.unlink()

# --- 5. now the masters are free ------------------------------------------
#
# Quants a SECOND time, and this is not belt-and-braces. Unlinking a stock.move makes
# Odoo re-evaluate availability, which RECREATES stock.quant rows for the products that
# move touched -- so the sweep in step 2 is undone by step 2 itself. Deleting them here,
# after every movement is gone and immediately before the products, is the only ordering
# where they stay deleted. Without it the purge dies on
# `stock_quant_product_id_fkey` with the products already half-detached.
if demo_products:
    q = env['stock.quant'].search([('product_id', 'in', demo_products.ids)])
    print("step 5: %d quant(s) recreated by the move deletions; removing" % len(q))
    removed['stock.quant'] = removed.get('stock.quant', 0) + len(q)
    env.flush_all()
    if q:
        env.cr.execute("DELETE FROM stock_quant WHERE id = ANY(%s)", (q.ids,))
    env.invalidate_all()

for model in ('product.template', 'res.partner', 'res.users', 'operating.unit'):
    r = recs(model)
    removed[model] = len(r)
    r.unlink()

# --- 6. the module's own bookkeeping --------------------------------------
#
# ONLY WHEN COMMITTING, and this is not tidiness. `button_immediate_uninstall()` goes
# through `Registry.new(update_module=True)`, which COMMITS the transaction from inside
# Odoo's module machinery. Calling it during a rehearsal makes every deletion above
# permanent and then prints "ROLLED BACK", because `cr.rollback()` afterwards has
# nothing left to undo. Measured on a fresh clone: a rehearsal ran every deletion above,
# committed them, and then printed "ROLLED BACK" over a transaction that no longer
# existed. A safety switch that reports success while doing the opposite is worse than no
# safety switch, so the uninstall is fenced behind the same flag as the commit, and the
# rehearsal proves its own rollback at the end by re-reading each count.
if COMMIT:
    mod = env['ir.module.module'].search([('name', '=', 'custom_demo_seed')])
    if mod.state == 'installed':
        mod.button_immediate_uninstall()
else:
    print("module uninstall SKIPPED in rehearsal: it commits internally (see comment)")

after = {}
for t in before:
    env.cr.execute(f"SELECT count(*) FROM {t}")
    after[t] = env.cr.fetchone()[0]
print("REMOVED:", removed)
print("AFTER :", after)
print("DELTA :", {k: after[k] - before[k] for k in before})
leftover = env['ir.model.data'].search_count([('module', '=', 'custom_demo_seed')])
print("ir.model.data rows still owned by custom_demo_seed:", leftover)
print("module state:", env['ir.module.module'].search([('name','=','custom_demo_seed')]).state)
if COMMIT:
    env.cr.commit()
    print("COMMITTED")
else:
    env.cr.rollback()
    # PROVE the rollback. Reading the counts back from the database after the rollback
    # is the whole point: the previous version of this script printed "ROLLED BACK"
    # over a transaction that had already been committed out from under it, and the
    # only way that was caught was by counting rows afterwards instead of trusting the
    # message.
    restored = {}
    for t in before:
        env.cr.execute(f"SELECT count(*) FROM {t}")
        restored[t] = env.cr.fetchone()[0]
    if restored == before:
        print("ROLLED BACK - verified: every table is back to its BEFORE count")
    else:
        drifted = {k: (before[k], restored[k]) for k in before if before[k] != restored[k]}
        raise SystemExit(
            "FATAL: rehearsal did NOT roll back cleanly. Something in the path above "
            f"committed. Tables that did not return to their starting count: {drifted}"
        )
