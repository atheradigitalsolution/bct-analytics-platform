# Prometheus scrape drop-in directory

`prometheus.yml` loads every `*.yml` in this directory through
`scrape_config_files`. Each file contains a **bare list of scrape configs** —
no `global:`, no top-level `scrape_configs:` key, just the list:

    - job_name: warehouse
      static_configs:
        - targets: ["warehouse-exporter:9187"]
          labels:
            service: warehouse

## Ownership

| Pattern | Owner |
|---|---|
| `analytics-*.yml` | **Data Warehouse agent** |
| anything else | Platform-Infra |

Platform-Infra owns the loading mechanism and never edits `analytics-*.yml`.
The Data Warehouse agent never edits `prometheus.yml`.

## Applying a change

    docker compose -p odoo19-bct restart prometheus

or, without a restart (`--web.enable-lifecycle` is enabled):

    curl -XPOST http://127.0.0.1:39090/-/reload

## Validate before you restart

A malformed file makes Prometheus refuse to start, and it will take the
existing dashboards down with it. Check first:

    docker run --rm -v "$PWD/observability/prometheus:/p" \
      prom/prometheus:v2.55.1 promtool check config /p/prometheus.yml
