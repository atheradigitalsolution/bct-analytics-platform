"""Prometheus instrumentation for the CDC consumer.

Names are the ones published in ``docs/agents/contracts/06-api.md`` and agreed with the Data
Warehouse agent through the Lead, because DWH owns the Grafana panels that read them. Renaming one
breaks a dashboard silently, so treat these as a contract, not as log lines.

There is deliberately no ``rows_per_second`` gauge. DWH derives throughput as
``rate(bct_cdc_rows_total[5m])`` and states the window in the panel legend, which keeps the
averaging window visible to whoever reads the panel instead of hiding it inside this process.

Note deliberately kept here rather than in a dashboard comment: this exporter is the *consumer's*
belief about its own lag. ``postgres_exporter`` separately publishes the *server's* view
(``pg_replication_slots_pg_wal_lsn_diff``). The two disagreeing is a stronger fault signal than
either number alone -- it catches a consumer that believes it is caught up while Postgres says it is
2 GB behind, which is exactly the state that ends with an invalidated slot.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, start_http_server

ROWS_TOTAL = Counter(
    "bct_cdc_rows_total",
    "Rows landed in the raw schema.",
    ["tenant", "source_table", "op"],
)

END_TO_END_LAG = Gauge(
    "bct_cdc_end_to_end_lag_seconds",
    "Seconds between the source transaction commit and the row landing in raw.",
    ["tenant", "source_table"],
)

SLOT_LAG_BYTES = Gauge(
    "bct_cdc_replication_slot_lag_bytes",
    "WAL bytes retained for this slot: pg_current_wal_lsn() - confirmed_flush_lsn.",
    ["tenant", "slot"],
)

SLOT_INVALIDATED = Gauge(
    "bct_cdc_slot_invalidated",
    "1 when the replication slot's wal_status is 'lost'. The 2 GB cap fired; a re-snapshot is "
    "required and the mart has a hole until it is done.",
    ["tenant", "slot"],
)

LAST_SUCCESS = Gauge(
    "bct_cdc_last_success_timestamp_seconds",
    "Unix timestamp of the last successful poll cycle for this table. This is a HEARTBEAT, not an "
    "event: it advances on every successful cycle including cycles that moved zero rows. If it only "
    "moved when rows flowed, an idle-but-healthy pipeline would be indistinguishable from a dead "
    "one -- and this metric backs meta.is_stale, so that mistake makes the dashboard lie about "
    "freshness in exactly the case where freshness matters.",
    ["tenant", "source_table"],
)

FAILURES = Counter(
    "bct_cdc_failure_count_total",
    "Loader failures.",
    ["tenant", "source_table"],
)

BACKFILL_PROGRESS = Gauge(
    "bct_cdc_backfill_progress_ratio",
    "Resumable snapshot progress, 0..1. Stays where it was across a restart.",
    ["tenant", "source_table"],
)

UP = Gauge(
    "bct_cdc_up",
    "1 while the consumer holds its replication slot and is streaming.",
    ["tenant"],
)

def serve(port: int) -> None:
    start_http_server(port)
