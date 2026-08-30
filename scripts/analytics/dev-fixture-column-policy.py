#!/usr/bin/env python3
"""Development fixture ONLY: seed ``warehouse.column_policy`` from Odoo's classification table.

**The Data Warehouse agent owns this table in production.** This script exists so Backend can build
and test the loader while DWH's seeder is still being written, and it is deliberately kept in
``scripts/analytics/`` (Backend's directory) rather than in ``analytics/warehouse/`` (DWH's).

It reads ``pdp_field_classification`` -- the declaration surface of frozen contract 01 -- and applies
contract 05's mapping, which is not negotiable and is therefore written out here as data rather than
inferred:

    public, internal  -> none
    personal          -> hmac_sha256
    sensitive         -> hmac_sha256_nullable   (mask_null = drop_to_null)
    secret            -> drop

Run it against the fixture warehouse:

    docker exec -i odoo19-bct-cdc-fixture-db psql ... < (this script's output)

or directly, with the repo's .env loaded.
"""

from __future__ import annotations

import os
import subprocess
import sys

CLASS_TO_TRANSFORM = {
    "public": "none",
    "internal": "none",
    "personal": "hmac_sha256",
    "sensitive": "hmac_sha256_nullable",
    "secret": "drop",
}

#: Rulings recorded in `docs/agents/contracts/01-classification.md` that the addon's seed data has
#: not caught up with yet. The contract is authoritative over the CSV; each entry names why.
#:
#: res.partner.barcode -- Lead ruling, contract 01 commit 064d3c2. The column is `jsonb` AND
#: company_dependent, so Odoo stores a map keyed by company id. Hashing that blob yields a digest
#: that changes whenever any single company's value changes (useless as a join key) and leaks how
#: many companies hold a value. Reclassified sensitive + drop_to_null: it does not land.
#: `addons/custom_pdp_core/data/pdp.field.classification.csv` still says `personal`; that is
#: Platform-Addons' file to change and has been raised to the Lead.
CONTRACT_OVERRIDES = {
    ("res_partner", "barcode"): ("sensitive", "hmac_sha256_nullable", True),
}


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def load_dotenv(path: str) -> None:
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def psql_source(sql: str) -> str:
    """Read from the Odoo OLTP database through the running postgres container."""
    result = subprocess.run(
        ["docker", "compose", "-p", "odoo19-bct", "exec", "-T", "postgres",
         "psql", "-U", "odoo", "-d", env("ODOO_DB_NAME", "bct"), "-tAF", "|", "-c", sql],
        capture_output=True, text=True, check=True,
    )
    return result.stdout


def main() -> int:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    load_dotenv(os.path.join(root, ".env"))

    rows = psql_source(
        "SELECT replace(model_name,'.','_'), field_name, pdp_class, drop_to_null "
        "FROM pdp_field_classification ORDER BY 1,2"
    )
    values = []
    overridden = []
    for line in rows.splitlines():
        if not line.strip():
            continue
        table, column, pdp_class, drop_to_null = line.split("|")
        transform = CLASS_TO_TRANSFORM[pdp_class]
        mask_null = pdp_class == "sensitive" and drop_to_null == "t"
        override = CONTRACT_OVERRIDES.get((table, column))
        if override:
            pdp_class, transform, mask_null = override
            overridden.append("%s.%s" % (table, column))
        values.append(
            "('%s','%s','%s','%s',%s)"
            % (table, column, pdp_class, transform, "true" if mask_null else "false")
        )

    statement = (
        "TRUNCATE warehouse.column_policy;\n"
        "INSERT INTO warehouse.column_policy "
        "(source_table, source_column, pdp_class, transform, mask_null) VALUES\n"
        + ",\n".join(values)
        + ";\n"
    )

    proc = subprocess.run(
        ["docker", "exec", "-i", "odoo19-bct-cdc-fixture-db", "psql",
         "-U", env("WAREHOUSE_DB_USER", "warehouse"), "-d", env("WAREHOUSE_DB", "warehouse"),
         "-v", "ON_ERROR_STOP=1"],
        input=statement, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        return proc.returncode
    print("seeded %d column policy rows" % len(values))
    if overridden:
        print("contract-01 overrides applied (addon seed data is behind): %s" % ", ".join(overridden))
    return 0


if __name__ == "__main__":
    sys.exit(main())
