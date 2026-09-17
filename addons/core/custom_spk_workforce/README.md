# Custom SPK Workforce

Shift attendance for pay, work logs for cost, and the monthly run that keeps
permanent labour from disappearing out of job cost.

## Name mapping

| BPD | Here |
|---|---|
| `booth_workforce` | `custom_spk_workforce` |
| `booth.attendance` | `custom.spk.attendance` |
| `booth.work.log` | `custom.spk.work.log` |
| `worker_type` | **not created** — reuses `x_custom_employment_type` |
| `labor_category` | `x_spk_labor_category` |
| `shift_rate` | `x_spk_shift_rate` |

## The one reuse decision worth knowing

`worker_type` (daily/permanent) is **not** added. `x_custom_employment_type`
already exists on `hr.employee` in `custom_hr_payroll_id`, and PPh 21 is computed
from it. Two fields answering one question would eventually disagree, and costing
would follow whichever was stale. `x_spk_is_daily` is derived from it and stored.

That makes this a `core/` module depending on `ee_gap`, which `custom_hht_bridge`
already does. The alternative — a parallel field — is worse.

`labor_category` is a genuinely separate axis and is new here: permanent-vs-daily
says how someone is paid, direct-vs-indirect says whether their time belongs to a
job at all. A supervisor is usually permanent *and* indirect, so their cost is
overhead however many workshops they walk through.

## Why two layers

Attendance answers *was this person here* and drives pay. A work log answers
*which job did their time land on* and drives cost. One record cannot do both: the
month's attendance total is the number of shifts worked, while the work log total is
at most that, split across however many jobs were touched.

## The gate, and why it is asymmetric

A daily worker's shift cannot be approved unmapped: the wage leaves the company
that week, and if nothing carries it, the money is spent with no job attached and
nobody finds out until margin disagrees with the bank.

A permanent worker's shift **can** be approved unmapped. Their pay does not depend
on it, so a hard gate would only teach people to tick a box carelessly. A daily cron
flags unmapped paid shifts instead — daily rather than weekly, because daily workers
are paid weekly: found on Friday it is a correction, found on Monday it is a
write-off.

## Allocation: shift count, not direct cost

`custom.spk.labor.allocation` divides the period's permanent **direct** payroll by
the shifts those people actually worked, and charges each SPK for the shifts it
received. Indirect staff are excluded from both sides.

The alternative the BPD offers — spreading over each job's direct cost — is one
query cheaper and wrong in the same direction every time: it flatters jobs staffed
by permanent workers and penalises jobs that leaned on daily labour. Recording the
shift costs the supervisor nothing, because the box was already ticked.

Two refusals keep it honest. No shifts refuses rather than dividing by zero. Shifts
with no approved payslip refuses rather than allocating zero, which would silently
declare that month's jobs free of labour.

## Idle time is not somebody's job

A daily worker present with nothing to build is still paid. Pushing that onto
whichever SPK is open makes a job carry cost it did not incur. So the company names
an idle account and an internal-work account, and the supervisor picks one. The
share of shifts landing on idle is worth watching: money out with no job attached.

## Status

**Never executed.** 30 tests, none run — the authoring session could not start Odoo.

```
docker exec odoo19-bct-odoo odoo -d <db> -i custom_spk_workforce \
  --test-enable --test-tags /custom_spk_workforce --stop-after-init --workers=0 \
  --http-port=8999 --gevent-port=8998 --without-demo=True
```

Likely first failures, in order of suspicion:

1. `account.analytic.plan` may be required on `account.analytic.account` in this
   build; the fixtures pass `plan_id` when a plan exists and omit it otherwise.
2. `res.config.settings` uses the `<app>`/`<setting>` layout, which is version
   sensitive.
3. The `IntegrityError` assertions rely on `models.Constraint`, the Odoo 19 form of
   `_sql_constraints`.
