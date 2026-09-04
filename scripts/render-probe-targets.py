#!/usr/bin/env python3
"""Render the public blackbox probe targets from configuration.

WHY THIS EXISTS. Probing the public edge is the only way to notice an expired
certificate, a moved DNS record or a broken proxy before a client does -- the
internal probes reach services by name and prove none of it. But the probes have
to name real production hostnames, and Prometheus performs no environment
substitution in its configuration, so the naive way to do it is to type the
production domain into a tracked file. This repository is mirrored publicly and
that is exactly the kind of thing `make scan-secret` exists to keep out.

So the JOB is tracked and the TARGETS are generated. The scrape file in
scrape.d/ carries the logic and no hostname; this script writes the hostnames
into a file that git ignores, from the one place the domain is already
configured. Nothing new has to be remembered: the domain lives in exactly one
place and always did.

WHY A `.json` FILE, which looks arbitrary until you check: `prometheus.yml`
globs `scrape.d/*.yml` as full scrape configs. A generated file of file_sd
targets is NOT a scrape config, so a `.yml` name there would be parsed as one
and Prometheus would refuse the whole configuration. The extension keeps the two
kinds of file apart in the same directory, which avoids adding a mount.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = REPO_ROOT / "observability" / "prometheus" / "scrape.d" / "public-targets.json"

#: label -> (path probed, blackbox module).
#:
#: Each path was measured before being written here, and the expected status is
#: encoded in the module rather than assumed:
#:   the site apex and the two health endpoints answer 200;
#:   the ERP hostname answers 401 at the edge, which is its healthy response.
#: Subdomain LABELS are fine in a tracked file -- they are already in the
#: Caddyfile and in any certificate transparency log. The DOMAIN is not.
SURFACES = [
    ("",        "/",         "http_200_public", "site"),
    ("auth",    "/healthz",  "http_200_public", "gateway"),
    ("insight", "/healthz",  "http_200_public", "insight"),
    ("odoo",    "/web/login", "http_401_public", "odoo"),
]


def domain() -> str:
    """The deployment's domain, from the environment or from .env."""
    value = os.environ.get("ATHERA_DOMAIN", "").strip()
    if value:
        return value
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("ATHERA_DOMAIN="):
                return line.split("=", 1)[1].strip()
    return ""


def main() -> int:
    dom = domain()
    if not dom:
        # Fail loudly rather than writing an empty target list that would make a
        # green board mean "nothing is being probed".
        print("render-probe-targets: FAIL - ATHERA_DOMAIN is not set anywhere")
        return 1

    entries = []
    for sub, path, module, product in SURFACES:
        host = dom if not sub else f"{sub}.{dom}"
        entries.append(
            {
                "targets": [f"https://{host}{path}"],
                "labels": {"module": module, "product": product, "surface": "public"},
            }
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(entries, indent=2) + "\n")
    print(f"render-probe-targets: wrote {len(entries)} public probe target(s)")
    for e in entries:
        print(f"  {e['labels']['product']:<10} {e['labels']['module']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
