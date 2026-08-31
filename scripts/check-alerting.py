#!/usr/bin/env python3
"""Fail if the alerting path is not actually armed.

`promtool check rules` proves a rule PARSES. Prometheus reporting `health: ok`
proves it EVALUATED without error. Neither proves it can ever fire, and neither
proves a firing alert would reach anyone:

  * a rule referencing a metric no exporter emits evaluates cleanly forever and
    is silently inert;
  * a scrape target that is down disarms every rule built on it;
  * Alertmanager being absent means a firing alert goes nowhere at all.

All three are the same failure shape this build keeps meeting - a check that
cannot fail is mistaken for one that passes. ADR 0001 accepted
max_slot_wal_keep_size=2GB *conditional on* slot-lag alerting working, so
"the rules are green" is not a sufficient answer.

Exit codes: 0 armed, 1 a hard failure, 0 with SKIP when Prometheus is not up
(the observability overlay is optional - `make up-obs`).
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

PROM = os.environ.get("PROMETHEUS_URL", "http://127.0.0.1:39090")
TIMEOUT = 10

# Metric names that are legitimately absent when the thing they describe does
# not exist. A slot series with zero slots is correct, not broken.
CONDITIONAL = {
    "pg_replication_slots_pg_wal_lsn_diff": "no replication slot exists yet",
    "pg_replication_slots_active": "no replication slot exists yet",
    "pg_replication_slot_wal_status": "no replication slot exists yet",
    "bct_cdc_slot_lag_bytes": "the CDC consumer is not running",
}

METRIC_RE = re.compile(r"\b([a-zA-Z_:][a-zA-Z0-9_:]*)\b(?:\s*\{|\s*[><=!]|\s*\)|\s*$|\s)")
PROMQL_KEYWORDS = {
    "by", "without", "on", "ignoring", "group_left", "group_right", "offset",
    "bool", "and", "or", "unless", "sum", "min", "max", "avg", "count", "rate",
    "irate", "increase", "delta", "abs", "ceil", "floor", "round", "clamp_max",
    "clamp_min", "histogram_quantile", "topk", "bottomk", "quantile", "stddev",
    "stdvar", "count_values", "absent", "absent_over_time", "changes", "time",
    "vector", "scalar", "predict_linear", "deriv", "humanize", "humanize1024",
    "last_over_time", "avg_over_time", "max_over_time", "min_over_time",
    "sum_over_time", "count_over_time", "label_replace", "group",
}


def get(path: str):
    """GET a Prometheus API path.

    PROMETHEUS_URL comes from the environment, so the scheme is validated rather
    than trusted: urlopen happily accepts `file:///etc/passwd`, which would turn
    a monitoring check into a file read. Flagged by ruff S310, and the flag was
    right - the fix is the check, not a suppression.
    """
    url = PROM + path
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(
            f"refusing to open {parsed.scheme!r} URL; PROMETHEUS_URL must be http or https"
        )
    with urllib.request.urlopen(url, timeout=TIMEOUT) as r:  # noqa: S310 - scheme checked above
        return json.load(r)


def main() -> int:
    # A misconfigured PROMETHEUS_URL must not masquerade as "Prometheus is down".
    # Reporting a config error as a SKIP is the same failure shape as a check
    # that cannot fail: it reads as "nothing to see here".
    parsed = urllib.parse.urlparse(PROM)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        print(f"check-alerting: FAIL - PROMETHEUS_URL is not a usable http(s) URL: {PROM!r}",
              file=sys.stderr)
        return 1

    try:
        get("/-/healthy")
    except Exception as exc:
        print(f"check-alerting: SKIP - Prometheus not reachable at {PROM} ({exc.__class__.__name__}).")
        print("  The observability overlay is optional. Start it with `make up-obs`.")
        print("  NOT a pass: slot-lag alerting is unverified while it is down.")
        return 0

    failures: list[str] = []
    warnings: list[str] = []

    # 1. every scrape target up
    targets = get("/api/v1/targets?state=active")["data"]["activeTargets"]
    for t in targets:
        job = t["labels"].get("job", "?")
        if t["health"] != "up":
            failures.append(f"scrape target '{job}' is {t['health']}: {t.get('lastError','')[:120]}")
    print(f"  scrape targets: {sum(1 for t in targets if t['health']=='up')}/{len(targets)} up")

    # 2. Prometheus must actually know an Alertmanager
    am = get("/api/v1/alertmanagers")["data"]
    active = [a["url"] for a in am.get("activeAlertmanagers", [])]
    if not active:
        failures.append(
            "Prometheus has NO active Alertmanager - every alert would fire into nothing. "
            f"dropped={[a['url'] for a in am.get('droppedAlertmanagers', [])]}")
    print(f"  alertmanagers: {len(active)} active")

    # 3. every metric an alert rule references must resolve to a series
    known = set(get("/api/v1/label/__name__/values")["data"])
    groups = get("/api/v1/rules")["data"]["groups"]
    n_rules = 0
    for g in groups:
        for rule in g["rules"]:
            if rule.get("type") != "alerting":
                continue
            n_rules += 1
            expr = rule["query"]
            refs = {m for m in METRIC_RE.findall(expr)
                    if m not in PROMQL_KEYWORDS and not m.isdigit()}
            missing = sorted(r for r in refs if r not in known and "_" in r)
            if missing:
                for m in missing:
                    why = CONDITIONAL.get(m)
                    line = f"{rule['name']}: no series for '{m}'"
                    (warnings if why else failures).append(
                        f"{line} ({why})" if why else
                        f"{line} - this rule can never fire, however green it looks")
    print(f"  alerting rules: {n_rules} evaluated")

    for w in warnings:
        print(f"  WARN  {w}")

    if failures:
        print("\ncheck-alerting: FAIL", file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        return 1

    print("check-alerting: OK - targets up, Alertmanager reachable, every rule's metrics resolve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
