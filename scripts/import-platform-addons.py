#!/usr/bin/env python3
"""
import-platform-addons.py — copy addons from the odoo-platform suite into this repo.

Authorised by docs/adr/0002-addon-import.md. That ADR, not this script, is the
record of what was decided and why; the constants below implement it.

The import is deliberately wave-based. 38 of the 154 source modules add columns to
tables this deployment replicates, and analytics/cdc/bct_cdc/policy.py hard-fails on
an unclassified column. A wave is not finished when the files land -- it is finished
when the classification seed has been regenerated and the loader runs clean.

Usage:
  python scripts/import-platform-addons.py --source E:/Projects/Odoo/platform/addons \
      --wave 0                      # dry run: prints the plan, writes nothing
  python scripts/import-platform-addons.py --source ... --wave 0 --apply
  python scripts/import-platform-addons.py --verify-depends

Waves are slices of the dependency graph by topological layer, so every wave is
dependency-closed on the waves before it.
"""

from __future__ import annotations

import argparse
import ast
import csv
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEST = REPO / "addons"
CATALOG = REPO / "docs" / "module-catalog.csv"

# ADR 0002 section 5 -- not imported at all.
SKIP = {
    "base_rest": "needs OCA `component`, never vendored; installable=False; unreferenced",
    "partner_firstname": "unreferenced; the only AGPL-3 module in the suite",
    "custom_stock_delivery_report_fix": "retired by its own manifest; breaks fresh installs on 19",
    "custom_vertical_example": "scaffold template that advertises itself as an application",
    # ADR 0002 section 3 -- zero dependents, and it defines pdp.masked.mixin a second time.
    "custom_pdp_masking": "collides with this repo's masking; nothing depends on it",
}

# ADR 0002 sections 3 and 4 -- renamed on the way in.
#
# The client-identifying maps (module renames, content substitutions, dedupe
# specs) are NOT in this repo: keeping the old client names here would make the
# scrubber itself the last file still carrying them. They live in the untracked
# scripts/client-renames.local.json (git-excluded; the master copy is kept
# outside the repo). Without that file the import cannot de-brand upstream
# code, so `--apply` refuses to run; the read-only consumers
# (refresh_module_catalog.py, migrate-client-renames.py) degrade gracefully to
# the generic entries below.
_LOCAL_RENAMES = Path(__file__).with_name("client-renames.local.json")

#: Non-client renames that belong to the repo itself.
RENAMES: dict[str, str] = {
    # Collision with this repo's own module. Upstream's custom_pdp_core is a
    # taxonomy of classification codes; since 2026-09 it is MERGED (together with
    # this repo's per-column registry) into compliance/custom_pdp. A re-import of
    # the upstream module would overwrite the merged module - review manually
    # instead of replaying this rename blindly.
    "custom_pdp_core": "custom_pdp",
    # Too generic a name for what it contains.
    "custom_ops_reports": "custom_asset_ops_reports",
}

# Applied to the CONTENTS and PATHS of every imported module (ADR 0002 section 4).
# Order matters: the specific client rules (from the local file) must run before
# the generic cleanup below - substituting a client name for a common noun can
# leave "the the"; collapsing duplicates afterwards is simpler than making every
# substitution agree with the article and noun around it.
CONTENT_SUBS: list[tuple[str, str]] = [
    # Brand seed comments are replaced with a generic explanation.
    (r"<!-- Brand seed\.[\s\S]*?-->",
     "<!-- Brand seed: generic retail segments, not one customer's brand list.\n"
     "             `legal_entity` is left unset; each tenant fills in its own. -->"),
    # Upstream test secrets are replaced with obviously-fake ones.
    (r'"s3cr3t-very-long-key"', '"dummy-hmac-key-for-tests"'),
    (r'"test-secret-please-change"', '"dummy-webhook-secret"'),
    (r'"va-test-secret-BCA"', '"dummy-va-callback-secret"'),
    # Written to match the value AFTER the client CamelCase rules have run.
    (r'"PmoTest!2026"', '"dummy-portal-password"'),
    # Prose cleanup, LAST.
    (r"\bthe the\b", "the"),
    (r"\bThe the\b", "The"),
    (r"\btenant tenant\b", "tenant"),
    (r"\bthe tenant drone\b", "the drone"),
    (r"\bthe tenant Inventory\b", "the Inventory"),
    # legal_entity named a real company; an empty cell is honest, a guess is not.
    (r"[ \t]*<field name=\"legal_entity\">[^<]*</field>\n", ""),
]

# Duplicate payloads removed on import (ADR 0002 section 3, catalogue P0
# findings). Keyed by UPSTREAM module name; client-specific, so it lives in the
# local file too.
DEDUPE: dict[str, dict] = {}

if _LOCAL_RENAMES.exists():
    import json as _json
    _local = _json.loads(_LOCAL_RENAMES.read_text(encoding="utf-8"))
    RENAMES.update(_local.get("renames", {}))
    # Client substitutions run BEFORE the generic cleanup entries above.
    CONTENT_SUBS = [tuple(x) for x in _local.get("content_subs", [])] + CONTENT_SUBS
    DEDUPE.update(_local.get("dedupe", {}))
HAVE_CLIENT_RENAMES = _LOCAL_RENAMES.exists()


def apply_dedupe(dest: Path, name: str) -> list[str]:
    """Drop duplicated data files and add the dependency that supplies them."""
    spec = DEDUPE.get(name)
    if not spec:
        return []
    notes = []
    manifest = dest / "__manifest__.py"
    text = manifest.read_text(encoding="utf-8")
    for rel in spec["drop_data"]:
        target = dest / rel
        if target.exists():
            target.unlink()
        # Remove the manifest entry too, or the install fails on a missing file.
        text = re.sub(rf'^\s*["\']{re.escape(rel)}["\'],?\s*\n', "", text, flags=re.M)
        notes.append(f"dropped {rel}")
    for dep in spec["add_depends"]:
        if f'"{dep}"' not in text and f"'{dep}'" not in text:
            text = re.sub(r'("depends"\s*:\s*\[)', rf'\1\n        "{dep}",', text, count=1)
            notes.append(f"added depends on {dep}")
    manifest.write_text(text, encoding="utf-8", newline="")
    return notes


# Waves are dependency-closed slices of the topological layer graph, NOT tiers.
# Tier is a packaging concept: addons/core/ holds modules at layers 0 through 4
# (custom_bast sits in core/ but depends on compliance/custom_pdp_audit). Importing
# by tier leaves dangling dependencies; importing by layer never does.
WAVES: dict[int, tuple[str, range]] = {
    0: ("foundation -- custom_core and the modules that need nothing else", range(0, 2)),
    1: ("the compliance and adapter layer that most of the suite sits on", range(2, 4)),
    2: ("the bulk of ee_gap -- accounting, WMS, HR, marketing", range(4, 5)),
    3: ("modules built on that bulk", range(5, 6)),
    4: ("the top of the graph -- control plane, verticals, tenant modules", range(6, 99)),
}


def load_catalog() -> dict[str, dict]:
    if not CATALOG.exists():
        sys.exit(
            f"catalogue not found: {CATALOG}\n"
            "The original 23-column row set came from tools/module_inventory.py in the "
            "upstream odoo-platform repo, which is not available here.\n"
            "To rebuild the measured columns from this tree instead, run "
            "tools/refresh_module_catalog.py -- but it needs an existing CSV to carry "
            "the judgement columns forward, so recover the file from git first."
        )
    with CATALOG.open(encoding="utf-8", newline="") as fh:
        return {r["module"]: r for r in csv.DictReader(fh)}


def wave_members(wave: int, catalog: dict[str, dict]) -> list[dict]:
    if wave not in WAVES:
        sys.exit(f"unknown wave {wave}; valid: {sorted(WAVES)}")
    layers = WAVES[wave][1]
    return sorted((r for r in catalog.values() if int(r["layer"]) in layers),
                  key=lambda r: (int(r["layer"]), r["module"]))


def _rename_tokens(text: str) -> str:
    """Module names appear in depends lists, `odoo.addons.<mod>` imports, XML-ID
    prefixes (`<mod>.view_x`) and asset paths (`/<mod>/static/...`). A letter-or-digit
    boundary catches all of those without touching `custom_pdp_core_extra`."""
    for old, new in RENAMES.items():
        text = re.sub(rf"(?<![A-Za-z0-9_]){re.escape(old)}(?![A-Za-z0-9_])", new, text)
    return text


def _scrub_client(text: str) -> str:
    for pat, repl in CONTENT_SUBS:
        text = re.sub(pat, repl, text)
    return text


def import_module(src: Path, name: str, tier: str, apply: bool) -> tuple[Path, int]:
    """Copy one module, applying renames to paths and contents."""
    new_name = RENAMES.get(name, name)
    dest = DEST / tier / new_name
    # The scrub runs on every module. Customer identity turned up in modules that
    # are otherwise generic -- a mail host in custom_retail_import, a legal entity in
    # custom_project_portfolio's brand seed, a client-prefixed constant in a _tenants
    # module -- so restricting it to renamed modules left the name in the tree.

    if not apply:
        return dest, sum(1 for p in src.rglob("*") if p.is_file())

    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    text_suffixes = {".py", ".xml", ".csv", ".js", ".scss", ".md", ".txt", ".cfg",
                     ".po", ".pot", ".json", ".yml", ".yaml", ".sql"}
    count = 0
    for path in sorted(src.rglob("*")):
        if any(p in ("__pycache__", ".git", "node_modules") for p in path.parts):
            continue
        # Chart-template CSVs are named <model>-<template_code>.csv and Odoo resolves
        # the template by that suffix, so renaming the filename is required, not
        # cosmetic.
        rel_str = str(path.relative_to(src))
        rel_str = _scrub_client(rel_str)
        rel_str = _rename_tokens(rel_str)
        target = dest / rel_str

        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix in text_suffixes:
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                shutil.copy2(path, target)
                count += 1
                continue
            text = _scrub_client(_rename_tokens(text))
            # newline="" keeps LF as LF. Without it, Python on Windows writes
            # CRLF and every imported file trips mixed-line-ending in pre-commit.
            with target.open("w", encoding="utf-8", newline="") as fh:
                fh.write(text)
        else:
            shutil.copy2(path, target)
        count += 1
    return dest, count


def verify_python() -> int:
    """Every imported .py must still compile.

    The scrub rewrites identifiers, not just prose, so a rule that is right for a
    sentence can be wrong for a constant: `AIM_COMPANY` became `the tenant_COMPANY`
    and only surfaced when Odoo imported the module. Compiling the tree turns that
    into a fast, local failure.
    """
    bad = []
    for py in sorted(DEST.rglob("*.py")):
        try:
            ast.parse(py.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError) as exc:
            bad.append(f"{py.relative_to(DEST)}: {exc}")
    for b in bad:
        print("  " + b)
    n = sum(1 for _ in DEST.rglob("*.py"))
    print(f"{n} Python files, {len(bad)} that do not compile")
    return 1 if bad else 0


def verify_depends() -> int:
    """Every declared dependency must resolve to a module present here or to an Odoo CE
    module. A dangling dependency fails the install, so this runs before every wave."""
    present = {m.parent.name for m in DEST.rglob("__manifest__.py")}
    problems: list[str] = []
    for man in sorted(DEST.rglob("__manifest__.py")):
        try:
            data = ast.literal_eval(man.read_text(encoding="utf-8"))
        except (ValueError, SyntaxError) as exc:
            problems.append(f"{man.parent.name}: unparseable manifest ({exc})")
            continue
        for dep in data.get("depends", []):
            if dep in present:
                continue
            if dep in SKIP:
                problems.append(f"{man.parent.name} -> depends on SKIPPED {dep}")
            elif dep.startswith(("custom_", "l10n_id_coa", "auth_jwt", "queue_job")):
                problems.append(f"{man.parent.name} -> depends on MISSING {dep}")
    for p in problems:
        print("  " + p)
    print(f"{len(present)} modules present, {len(problems)} dependency problems")
    return 1 if problems else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", help="odoo-platform addons root")
    ap.add_argument("--wave", type=int, help="which wave to import")
    ap.add_argument("--apply", action="store_true", help="actually write; default is a dry run")
    ap.add_argument("--verify-depends", action="store_true",
                    help="check every declared dependency resolves, then exit")
    ap.add_argument("--verify-python", action="store_true",
                    help="check every imported .py still compiles, then exit")
    args = ap.parse_args(argv)

    if args.verify_python:
        return verify_python()
    if args.verify_depends:
        return verify_depends()
    if args.wave is None or not args.source:
        ap.error("--wave and --source are required unless --verify-depends is given")

    source = Path(args.source)
    catalog = load_catalog()
    members = wave_members(args.wave, catalog)

    print(f"Wave {args.wave} -- {WAVES[args.wave][0]} (layers {WAVES[args.wave][1].start}..{min(WAVES[args.wave][1].stop - 1, 9)})")
    if args.apply and not HAVE_CLIENT_RENAMES:
        sys.exit(
            "scripts/client-renames.local.json is missing: without the client "
            "rename map the import cannot de-brand upstream code. Restore it "
            "from the copy kept outside the repo before using --apply."
        )
    print("APPLYING" if args.apply else "DRY RUN (pass --apply to write)")
    print()

    imported = skipped = files = cdc_cols = 0
    for row in members:
        name, tier = row["module"], row["tier"]
        if name in SKIP:
            print(f"     skip   {name:38} {SKIP[name]}")
            skipped += 1
            continue
        src = source / tier / name
        if not src.is_dir():
            found = [p for p in source.glob(f"{tier}/**/{name}") if p.is_dir()]
            if not found:
                print(f"  MISSING {name:38} not found under {tier}/")
                continue
            src = found[0]
        dest, n = import_module(src, name, tier, args.apply)
        if args.apply:
            for note in apply_dedupe(dest, name):
                print(f"          dedupe: {note}")
        note = f"-> {RENAMES[name]} " if name in RENAMES else ""
        cdc = int(row.get("cdc_impact_cols") or 0)
        cdc_cols += cdc
        cdcnote = f"[+{cdc} replicated cols]" if cdc else ""
        print(f"  L{row['layer']} import {name:38} {tier}/ {note}{cdcnote}")
        imported += 1
        files += n

    print(f"\n{imported} modules ({files} files), {skipped} skipped.")
    if cdc_cols:
        print(f"\nThis wave adds {cdc_cols} columns to replicated tables. The CDC loader "
              f"will hard-fail\nuntil they are classified:")
        print("  python addons/compliance/custom_pdp/tools/generate_classification_seed.py")
        print("  make up-analytics")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
