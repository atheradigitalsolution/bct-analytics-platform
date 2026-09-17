#!/usr/bin/env python3
"""refresh_module_catalog.py — refresh docs/module-catalog.csv from the tree on disk.

Why this exists
---------------
``scripts/import-platform-addons.py`` reads the catalogue and, when it is missing,
tells you to "Run tools/module_inventory.py first" — a file that does not exist
here. Per ``docs/module-catalog.md`` it lives in the upstream ``odoo-platform``
repo and takes inputs this repository does not have (a module-diff JSON, the PDP
classification seed, a path to an unpacked Odoo core). It produced the original
23-column row set; it cannot be run from here.

So the catalogue had no way back to the truth once modules were renamed or moved,
and it drifted: the committed CSV still named ``custom_arka_show_date``,
``custom_arka_aim_numbering`` and ``custom_levis_*`` long after they became
``custom_sale_show_date``, ``custom_doc_numbering`` and ``custom_retail_*``, and
it listed 154 modules against 162 on disk.

This is deliberately NOT named ``module_inventory.py``. It does strictly less than
the upstream tool, and shadowing that name would make a narrower script look like
the real generator.

A caveat that matters when reading history: the LOC figures this writes are
measured by the rule below (non-blank lines in code files), which is not
necessarily the upstream tool's rule — refreshed rows came out about 8% lower on
median. LOC is comparable across rows of the same generation, not across the
refresh boundary.

What it does and does not touch
-------------------------------
Some columns are measurements; the rest are judgements a script has no business
inventing. So this is a MERGE, not a rewrite:

  measured, recomputed every run
      module, tier, version, application, license, summary, loc, files, tests,
      dependents, name_collision, layer

  carried forward from the existing row, keyed by module name
      domain, maturity, coupling, disposition, cdc_impact_cols, packs, tags,
      models_without_search, core_field_dupes, commits, last_commit

A module that appears or disappears is reported, never silently dropped: a new
module gets empty judgement columns for a human to fill, and a module gone from
disk is listed so someone decides whether that was intentional.

``addons/ee_gap/`` is a nested clone (see .gitignore) and is scanned like any
other tier — its modules are real and installed.

Usage
-----
  python3 tools/module_inventory.py            # dry run: report, write nothing
  python3 tools/module_inventory.py --apply    # rewrite docs/module-catalog.csv
"""

from __future__ import annotations

import argparse
import ast
import csv
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ADDONS = REPO / "addons"
CATALOG = REPO / "docs" / "module-catalog.csv"

# Tier order mirrors addons_path in odoo/odoo.conf, which is also the load order.
TIER_ORDER = [
    "",  # modules sitting directly in addons/ with no tier
    "_vendor",
    "core",
    "control_plane",
    "compliance",
    "ee_gap",
    "operations",
    "verticals",
    "_tenants",
]

# Modules renamed in place when client names were scrubbed from the tree. Without
# this the merge would see a delete plus an unrelated insert, and every judgement
# column earned on the old row would be thrown away. Each pair below was confirmed
# by diffing the catalogue summary against the manifest summary on disk: identical
# text, client name removed.
RENAMES = {
    "custom_arka_show_date": "custom_sale_show_date",
    "custom_arka_aim_numbering": "custom_doc_numbering",
    "custom_arka_fx_header": "custom_account_fx_header",
    "custom_arka_aim_asset_register": "custom_asset_register_seed",
    "custom_arka_aim_opening_balance": "custom_opening_balance_seed",
    "custom_arka_aim_seed": "custom_tenant_coa_seed",
    "custom_levis_asset_accounts": "custom_retail_asset_accounts",
    "custom_levis_categ_approval": "custom_retail_categ_approval",
    "custom_levis_localization": "custom_retail_localization",
    "custom_levis_sales_dashboard": "custom_retail_sales_dashboard",
    "custom_ops_reports": "custom_asset_ops_reports",
    "custom_ppob_eraspace_bridge": "custom_ppob_pos_bridge",
    "l10n_erajaya": "l10n_id_coa_10d",
}

MEASURED = {
    "module", "tier", "version", "application", "license", "summary",
    "loc", "files", "tests", "dependents", "name_collision", "layer",
}

CODE_SUFFIXES = {".py", ".xml", ".csv", ".js", ".scss", ".css", ".sql"}


def discover(addons: Path) -> dict[str, dict]:
    """Every directory holding a __manifest__.py, keyed by technical name."""
    found: dict[str, dict] = {}
    collisions: Counter = Counter()
    for manifest in sorted(addons.rglob("__manifest__.py")):
        mod_dir = manifest.parent
        # Ignore manifests nested inside another module (fixtures, test data).
        if (mod_dir.parent / "__manifest__.py").exists():
            continue
        rel = mod_dir.relative_to(addons)
        tier = rel.parts[0] if len(rel.parts) > 1 else ""
        name = mod_dir.name
        collisions[name] += 1
        try:
            man = ast.literal_eval(manifest.read_text(encoding="utf-8").strip())
        except (ValueError, SyntaxError) as exc:
            print(f"  ! {name}: unreadable manifest ({exc})", file=sys.stderr)
            continue
        found[name] = {"dir": mod_dir, "tier": tier, "manifest": man}
    for name, n in collisions.items():
        if n > 1 and name in found:
            found[name]["collision"] = True
    return found


def measure(entry: dict) -> dict:
    """Count what can be counted. LOC excludes blank lines; tests counts files."""
    mod_dir: Path = entry["dir"]
    loc = files = tests = 0
    for path in mod_dir.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        files += 1
        if path.suffix not in CODE_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        loc += sum(1 for line in text.splitlines() if line.strip())
        if path.parent.name == "tests" and path.name.startswith("test_"):
            tests += 1
    return {"loc": loc, "files": files, "tests": tests}


def layer_of(name: str, found: dict, seen: frozenset = frozenset()) -> int:
    """Longest dependency chain to a module outside this repo. Cycles clamp to 0."""
    if name in seen or name not in found:
        return 0
    deps = found[name]["manifest"].get("depends") or []
    inner = [layer_of(d, found, seen | {name}) for d in deps if d in found]
    return 1 + max(inner) if inner else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="write docs/module-catalog.csv (default: report only)")
    args = ap.parse_args(argv)

    if not CATALOG.exists():
        print(f"catalogue not found: {CATALOG}", file=sys.stderr)
        return 2

    with CATALOG.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or [])
        previous = {r["module"]: r for r in reader}

    # Re-key renamed rows so their judgement columns survive the merge.
    renamed = []
    for old_name, new_name in RENAMES.items():
        if old_name in previous and new_name not in previous:
            previous[new_name] = previous.pop(old_name)
            renamed.append((old_name, new_name))

    found = discover(ADDONS)
    if not found:
        print(f"no modules found under {ADDONS}", file=sys.stderr)
        return 2

    dependents: Counter = Counter()
    for entry in found.values():
        for dep in entry["manifest"].get("depends") or []:
            if dep in found:
                dependents[dep] += 1

    rows, added, moved = [], [], []
    for name in sorted(found):
        entry = found[name]
        man = entry["manifest"]
        row = dict(previous.get(name) or {k: "" for k in fieldnames})
        old_tier = row.get("tier", "")
        row.update(measure(entry))
        row.update({
            "module": name,
            "tier": entry["tier"],
            "version": man.get("version", ""),
            "application": str(bool(man.get("application", False))),
            "license": man.get("license", ""),
            "summary": (man.get("summary") or "").replace("\n", " ").strip(),
            "dependents": dependents.get(name, 0),
            "name_collision": str(bool(entry.get("collision", False))),
            "layer": layer_of(name, found),
        })
        if name not in previous:
            added.append(name)
        elif old_tier != entry["tier"]:
            moved.append((name, old_tier, entry["tier"]))
        rows.append(row)

    removed = sorted(set(previous) - set(found))
    rows.sort(key=lambda r: (TIER_ORDER.index(r["tier"]) if r["tier"] in TIER_ORDER
                             else len(TIER_ORDER), r["module"]))

    print(f"scanned {len(found)} modules under {ADDONS.relative_to(REPO)}")
    print("by tier: " + ", ".join(
        f"{t or '(root)'}={n}" for t, n in
        sorted(Counter(r["tier"] for r in rows).items(),
               key=lambda kv: TIER_ORDER.index(kv[0]) if kv[0] in TIER_ORDER else 99)))
    for old_name, new_name in renamed:
        print(f"  RENAMED {old_name} -> {new_name} (judgement columns carried over)")
    for name, old, new in moved:
        print(f"  MOVED   {name}: {old or '(root)'} -> {new or '(root)'}")
    for name in added:
        print(f"  ADDED   {name} (judgement columns left blank for a human)")
    for name in removed:
        print(f"  GONE    {name} — in the catalogue, absent from disk")

    if not args.apply:
        print("\ndry run — nothing written. Re-run with --apply.")
        return 0

    with CATALOG.open("w", encoding="utf-8", newline="") as fh:
        # csv defaults to CRLF; the committed file is LF, and letting the default
        # through rewrites all 162 lines as a line-ending change that hides the
        # real diff.
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore",
                                lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nwrote {CATALOG.relative_to(REPO)} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
