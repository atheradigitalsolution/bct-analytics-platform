#!/usr/bin/env python3
"""Merge custom_pdp_core + custom_pdp_taxonomy into custom_pdp, in the database.

OpenUpgrade-style module merge: NO uninstall (uninstalling custom_pdp_core would
drop pdp_field_classification and its ~1.1k seed rows, killing the warehouse).
Instead the two modules' ir_model_data ownership is transferred to custom_pdp,
one ir_module_module row is renamed to custom_pdp and the other deleted, and
every ir_module_module_dependency pointing at the old names is rewritten.

Known xmlid collision between the two source modules: `menu_pdp_root` (both
defined it). The taxonomy menu survives; the registry menu's children are
re-parented onto it and the registry menu is deleted. Any OTHER collision
aborts the run - resolve it explicitly, never silently.

Per-DB variants handled:
  - both installed (bct, bct_fixture, simrs_demo, acme_l10n, ndi, expomedia)
  - only custom_pdp_core installed (acme)
  - only custom_pdp_taxonomy installed (athera_admin, athera_lgx)
  - neither (skipped)

Idempotent: a DB where custom_pdp already exists installed is reported and
skipped. Dry run by default; write with --apply. After --apply, run
    odoo -d <db> -u custom_pdp --stop-after-init
to load the merged module (data files, menus, xmlid garbage collection).
"""

from __future__ import annotations

import argparse
import subprocess
import sys

PG_CONTAINER = "odoo19-bct-postgres"
OLD = ("custom_pdp_core", "custom_pdp_taxonomy")
NEW = "custom_pdp"


def psql(db: str, sql: str) -> list[list[str]]:
    out = subprocess.run(
        ["docker", "exec", PG_CONTAINER, "psql", "-U", "odoo", "-d", db,
         "-X", "-A", "-t", "-F", "\t", "-v", "ON_ERROR_STOP=1", "-c", sql],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        sys.exit(f"[{db}] psql failed:\n{sql}\n{out.stderr}")
    return [line.split("\t") for line in out.stdout.splitlines() if line]


def one(db: str, sql: str) -> str | None:
    rows = psql(db, sql)
    return rows[0][0] if rows else None


def module_state(db: str, name: str) -> str | None:
    return one(db, f"SELECT state FROM ir_module_module WHERE name = '{name}'")


def snapshot(db: str) -> dict:
    return {
        "registry_rows": one(db, "SELECT count(*) FROM pdp_field_classification")
        if one(db, "SELECT 1 FROM information_schema.tables WHERE table_name='pdp_field_classification'")
        else "0",
        "tagged_fields": one(db,
            "SELECT count(*) FROM ir_model_fields WHERE x_pdp_classification_id IS NOT NULL")
        if one(db, "SELECT 1 FROM information_schema.columns "
                   "WHERE table_name='ir_model_fields' AND column_name='x_pdp_classification_id'")
        else "0",
    }


def migrate_db(db: str, apply: bool) -> None:
    st = {m: module_state(db, m) for m in OLD + (NEW,)}
    print(f"\n=== {db}: core={st[OLD[0]]} taxonomy={st[OLD[1]]} {NEW}={st[NEW]}")

    if st[NEW] in ("installed", "to upgrade"):
        print(f"[{db}] {NEW} already present and installed - nothing to do.")
        return
    installed_old = [m for m in OLD if st[m] in ("installed", "to upgrade")]
    if not installed_old:
        print(f"[{db}] neither source module installed - skipping.")
        return

    before = snapshot(db)
    print(f"[{db}] before: registry={before['registry_rows']} tagged={before['tagged_fields']}")

    # 1. xmlid collisions between the two source modules.
    collisions = [r[0] for r in psql(db,
        "SELECT name FROM ir_model_data "
        f"WHERE module IN ('{OLD[0]}','{OLD[1]}') "
        "GROUP BY name HAVING COUNT(DISTINCT module) > 1")]
    unexpected = [c for c in collisions if c != "menu_pdp_root"]
    if unexpected:
        sys.exit(f"[{db}] unexpected xmlid collisions {unexpected} - resolve explicitly first.")

    stmts: list[str] = []

    # 2. Known collision: keep the taxonomy menu, fold the registry menu into it.
    if "menu_pdp_root" in collisions:
        stmts += [
            f"""
            UPDATE ir_ui_menu SET parent_id = tax.res_id
              FROM ir_model_data tax, ir_model_data core
             WHERE tax.module = '{OLD[1]}'  AND tax.name = 'menu_pdp_root'
               AND core.module = '{OLD[0]}' AND core.name = 'menu_pdp_root'
               AND ir_ui_menu.parent_id = core.res_id
            """,
            f"""
            DELETE FROM ir_ui_menu
             WHERE id = (SELECT res_id FROM ir_model_data
                          WHERE module = '{OLD[0]}' AND name = 'menu_pdp_root')
            """,
            f"DELETE FROM ir_model_data WHERE module = '{OLD[0]}' AND name = 'menu_pdp_root'",
        ]

    # 3. Transfer xmlid ownership.
    stmts.append(
        f"UPDATE ir_model_data SET module = '{NEW}' WHERE module IN ('{OLD[0]}','{OLD[1]}')")

    # 4. ir_module_module surgery. The registry owner (core) is the identity
    #    that survives where it is installed; otherwise the taxonomy row is.
    survivor = OLD[0] if st[OLD[0]] in ("installed", "to upgrade") else OLD[1]
    for name in OLD + (NEW,):
        if name == survivor:
            continue
        if module_state(db, name) is None:
            continue
        # leftover row (uninstalled twin, or a pre-created custom_pdp row):
        # remove it and its bookkeeping so the rename below cannot collide.
        stmts += [
            f"""
            DELETE FROM ir_module_module_dependency
             WHERE module_id = (SELECT id FROM ir_module_module WHERE name = '{name}')
            """,
            f"DELETE FROM ir_model_data WHERE module = 'base' AND name = 'module_{name}'",
            f"DELETE FROM ir_module_module WHERE name = '{name}'",
        ]
    stmts += [
        f"UPDATE ir_module_module SET name = '{NEW}' WHERE name = '{survivor}'",
        f"UPDATE ir_model_data SET name = 'module_{NEW}' "
        f"WHERE module = 'base' AND name = 'module_{survivor}'",
    ]

    # 5. Rewrite dependencies on the old names (dedupe first: a module that
    #    depended on both old names would otherwise carry two identical rows).
    stmts += [
        f"""
        DELETE FROM ir_module_module_dependency d
         USING ir_module_module_dependency keep
         WHERE d.name IN ('{OLD[0]}','{OLD[1]}') AND keep.name IN ('{OLD[0]}','{OLD[1]}')
           AND d.module_id = keep.module_id AND d.id > keep.id
        """,
        f"UPDATE ir_module_module_dependency SET name = '{NEW}' "
        f"WHERE name IN ('{OLD[0]}','{OLD[1]}')",
    ]

    if not apply:
        print(f"[{db}] DRY RUN - would execute {len(stmts)} statements. Re-run with --apply.")
        return

    body = "; ".join(" ".join(s.split()) for s in stmts)
    psql(db, f"BEGIN; {body}; COMMIT;")

    # 6. Verification.
    after = snapshot(db)
    orphans = one(db,
        f"SELECT count(*) FROM ir_model_data WHERE module IN ('{OLD[0]}','{OLD[1]}')")
    deps = one(db,
        f"SELECT count(*) FROM ir_module_module_dependency WHERE name IN ('{OLD[0]}','{OLD[1]}')")
    new_state = module_state(db, NEW)
    print(f"[{db}] after:  registry={after['registry_rows']} tagged={after['tagged_fields']} "
          f"orphan_xmlids={orphans} old_deps={deps} {NEW}={new_state}")
    assert orphans == "0" and deps == "0", f"[{db}] surgery left orphans behind"
    assert int(after["registry_rows"]) >= int(before["registry_rows"]), f"[{db}] registry shrank"
    assert int(after["tagged_fields"]) >= int(before["tagged_fields"]), f"[{db}] tags shrank"
    print(f"[{db}] OK - now run: odoo -d {db} -u {NEW} --stop-after-init")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", action="append", default=[],
                    help="database to migrate (repeatable); default: all non-template DBs")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = ap.parse_args()

    dbs = args.db or [r[0] for r in psql("postgres",
        "SELECT datname FROM pg_database WHERE NOT datistemplate "
        "AND datname NOT IN ('postgres','policy_master')")]
    for db in dbs:
        migrate_db(db, args.apply)


if __name__ == "__main__":
    main()
