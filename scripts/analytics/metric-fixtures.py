#!/usr/bin/env python3
"""Generate ``analytics/semantic-api/metrics/fixtures/*.json`` for the Frontend agent.

Contract 03's Frontend fixture rule: Frontend may develop against these, and a hand-written fixture
shape is a brief violation. So they are **generated from the same registry the API serves**, never
written by hand — if a metric's shape changes, the fixture changes with it and Frontend finds out
at build time rather than at integration time.

Two modes:

* **live** (default when a token is supplied): calls the running API and records the real response.
  The fixture is then a transcript of the actual contract, including ``meta``.
* **offline**: builds a response of the correct SHAPE from the metric definitions alone, with
  representative values. Used in CI, where no warehouse is running.

Both emit the same envelope, so Frontend cannot tell which produced a given file — that is the
point. A fixture whose shape depends on how it was generated is not a contract.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
METRICS_DIR = os.path.join(ROOT, "analytics", "semantic-api", "metrics")
FIXTURES_DIR = os.path.join(METRICS_DIR, "fixtures")

sys.path.insert(0, os.path.join(ROOT, "analytics", "semantic-api"))


def _sample_value(metric, index):
    if metric.type in ("count", "integer"):
        return 100 + index * 7
    if metric.type == "percent":
        return round(0.1 + index * 0.05, 4)
    if metric.type == "duration_seconds":
        return 30 + index * 5
    return round(1000000.0 + index * 250000.5, 2)


def _sample_dimension(name, index):
    if name.endswith("_month"):
        return (dt.date(2026, 1, 1) + dt.timedelta(days=31 * index)).replace(day=1).isoformat()
    if name.endswith("_day"):
        return (dt.date(2026, 1, 1) + dt.timedelta(days=index)).isoformat()
    if name.endswith("_id"):
        return 70 + index
    if name.endswith("_key"):
        # Keys in the warehouse are surrogate hashes, so a fixture must not look like a name.
        return "%032x" % (0xA1B2C3 + index)
    if name == "tenant_id":
        return "bct"
    return "%s_%d" % (name, index)


def offline_fixture(metric, dimensions, rows=6):
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    return {
        "metric": metric.name,
        "dimensions": dimensions,
        "rows": [
            dict(
                [(d, _sample_dimension(d, i)) for d in dimensions]
                + [("value", _sample_value(metric, i))]
            )
            for i in range(rows)
        ],
        "meta": {
            "tenant_id": "bct",
            "row_count": rows,
            "last_refreshed_at": now.isoformat(),
            "is_stale": False,
            "refresh_sla_seconds": metric.refresh_sla_seconds,
            "source_model": metric.source_model,
            "unit": metric.unit,
            "type": metric.type,
            "query_duration_ms": 12.3,
        },
    }


def live_fixture(url, token, metric, dimensions):
    filters = {}
    for key, spec in metric.filters.items():
        if not spec.get("required"):
            continue
        if spec.get("type") == "daterange":
            filters[key] = ["2026-01-01", "2026-12-31"]
    body = json.dumps({
        "metric": metric.name, "dimensions": dimensions, "filters": filters, "limit": 20,
    }).encode()
    request = urllib.request.Request(  # noqa: S310 - developer tool, URL supplied on the CLI
        url.rstrip("/") + "/v1/query",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + token},
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        return json.loads(response.read().decode())


def main():
    parser = argparse.ArgumentParser(description="Generate Frontend metric fixtures")
    parser.add_argument("--url", default="http://127.0.0.1:38200")
    parser.add_argument("--token", default=os.environ.get("SEMANTIC_API_TOKEN", ""))
    parser.add_argument("--offline", action="store_true",
                        help="Generate shapes from the registry alone; no running API needed.")
    args = parser.parse_args()

    from app.registry import load_registry

    registry = load_registry(METRICS_DIR)
    os.makedirs(FIXTURES_DIR, exist_ok=True)

    written = []
    for metric in registry.all():
        # One representative grouping per metric: the first non-tenant dimension. Frontend needs a
        # shape, not a data dump, and a smaller fixture is one they will actually read.
        dimensions = [d for d in metric.dimensions if d != "tenant_id"][:1]
        if args.token and not args.offline:
            try:
                payload = live_fixture(args.url, args.token, metric, dimensions)
            except (urllib.error.URLError, urllib.error.HTTPError) as exc:
                print("live fetch failed for %s (%s); falling back to offline shape"
                      % (metric.name, exc.__class__.__name__))
                payload = offline_fixture(metric, dimensions)
        else:
            payload = offline_fixture(metric, dimensions)

        path = os.path.join(FIXTURES_DIR, "%s.json" % metric.name)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, sort_keys=False)
            handle.write("\n")
        written.append(os.path.relpath(path, ROOT))

    catalogue = os.path.join(FIXTURES_DIR, "_catalogue.json")
    with open(catalogue, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(
            {"metrics": [
                {
                    "name": m.name, "label": m.label, "description": m.description,
                    "grain": m.grain, "dimensions": m.dimensions, "filters": m.filters,
                    "type": m.type, "unit": m.unit, "aggregation": m.aggregation,
                    "refresh_sla_seconds": m.refresh_sla_seconds, "pdp_class": m.pdp_class,
                    "source_model": m.source_model,
                }
                for m in registry.all()
            ]},
            handle, indent=2,
        )
        handle.write("\n")
    written.append(os.path.relpath(catalogue, ROOT))

    print("wrote %d fixture file(s):" % len(written))
    for path in written:
        print("  " + path.replace("\\", "/"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
