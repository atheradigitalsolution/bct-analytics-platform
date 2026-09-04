#!/usr/bin/env python3
"""Fail if .gitignore silently drops a file that must ship.

Two checks, because the bug has two faces:

  A. PATTERN REGRESSION. An unanchored `data/` matches at every depth, so it
     excluded addons/*/data/*.csv - the 724-row contract 01 classification map
     among them - while every local check passed, because the files existed in
     the working tree. `git status` shows nothing and tests pass; it only
     surfaces on a clean clone. These probes assert the patterns themselves,
     using paths that need not exist.

  B. DECLARED-BUT-UNTRACKED. Odoo aborts on a missing declared data file, so
     every path in an addon manifest's `data`/`demo` list must be tracked, not
     merely present on disk. This is the failure the pattern bug caused.

  C. EXTERNAL TREE NOT A CLONE. `addons/ee_gap/` is versioned in its own
     repository and cloned into place, so this repo deliberately ignores it.
     "Ignored" and "absent on the next host" look identical from here unless
     something asserts the difference: the directory must exist AND be a real
     clone, and check B then asks THAT repository what it tracks. A hand-copied
     tree passes every on-disk test and disappears on a clean host.

`git check-ignore -q` is the authoritative form: with -v it also exits 0 on a
NEGATION match, which reports a file that ships as if it were ignored.
"""
import ast
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Representative paths. They do not need to exist - these test the patterns.
MUST_SHIP = [
    "addons/custom_pdp_core/data/pdp.field.classification.csv",
    "addons/any_module/data/anything.xml",
    "analytics/dbt/data/seed.csv",
    "analytics/dbt/models/marts/build/model.sql",
    "analytics/warehouse/init/data/bootstrap.sql",
    "insight-portal/src/data/fixtures.json",
    "insight-portal/logs/README.md",
    "observability/grafana/dashboards/data/panel.json",
    "tests/data/fixture.json",
    "docs/data/diagram.svg",
    "tests/fixtures/jwt-public.pem",
    "tests/fixtures/service.crt",
]
MUST_BE_IGNORED = [
    ".env",
    ".env.bak-20260101T000000Z",
    "data/runtime.db",
    "backups/bct/20260101/database.dump",
    "logs/odoo.log",
    "postgres/conf.d/local.conf",
    "node_modules/pkg/index.js",
    "insight-portal/node_modules/pkg/index.js",
    "tests/fixtures/jwt-private.pem",
    "security/age.key",
    # ee_gap lives in its own repository and is cloned into this path. If the
    # anchor ever slips, THIS repo starts tracking 2 112 files again.
    "addons/ee_gap/l10n_id_psak_custom/__manifest__.py",
]

# Addon trees that are versioned in a DIFFERENT repository and cloned into
# place. Check B still applies to them - a declared data file that nobody
# tracks anywhere breaks the install just the same - but "tracked" has to be
# asked of the repository that actually owns the file.
EXTERNAL_ADDON_TREES = {
    "addons/ee_gap": "github.com/atheradigitalsolution/athera-odoo-ee-gap",
}


def ignored(path: str) -> bool:
    return subprocess.run(
        ["git", "check-ignore", "-q", "--no-index", path],
        cwd=ROOT, capture_output=True,
    ).returncode == 0


def why(path: str) -> str:
    r = subprocess.run(["git", "check-ignore", "-v", "--no-index", path],
                       cwd=ROOT, capture_output=True, text=True)
    return r.stdout.strip().split("\t")[0] if r.stdout else "?"


def main() -> int:
    problems = []

    for p in MUST_SHIP:
        if ignored(p):
            problems.append(f"A. would be silently dropped: {p}\n     matched by {why(p)}")
    for p in MUST_BE_IGNORED:
        if not ignored(p):
            problems.append(f"A. should be ignored but is not: {p}")

    tracked = set(subprocess.run(["git", "ls-files"], cwd=ROOT,
                                 capture_output=True, text=True).stdout.split("\n"))

    # An external tree must be a real clone. A hand-copied directory passes every
    # "the file is on disk" test and then does not exist on the next host, which
    # is precisely the clean-clone failure this guard was written for. Ask the
    # nested repository what IT tracks; refuse to guess.
    for prefix, origin in EXTERNAL_ADDON_TREES.items():
        tree = ROOT / prefix
        if not tree.is_dir():
            problems.append(
                f"C. {prefix}/ is missing. It is cloned from {origin}; "
                f"run `make addons-ee-gap`. Odoo's addons_path still lists it and "
                f"modules inside it are installed in production.")
            continue
        if not (tree / ".git").exists():
            problems.append(
                f"C. {prefix}/ exists but is not a git clone of {origin}. "
                f"A copied tree cannot be reproduced on a clean host.")
            continue
        inner = subprocess.run(["git", "ls-files"], cwd=tree,
                               capture_output=True, text=True)
        if inner.returncode != 0:
            problems.append(f"C. {prefix}/: `git ls-files` failed: {inner.stderr.strip()}")
            continue
        tracked |= {f"{prefix}/{rel}" for rel in inner.stdout.split("\n") if rel}
    # rglob, not glob("*/..."). ADR 0002 nested the tree as
    # addons/<group>/<module>/, so a one-level glob sees only the five modules
    # written here and is blind to the 149 imported ones - which is exactly the
    # class of silent omission this guard exists to catch.
    for manifest in sorted((ROOT / "addons").rglob("__manifest__.py")):
        module = manifest.parent.relative_to(ROOT / "addons").as_posix()
        try:
            spec = ast.literal_eval(manifest.read_text(encoding="utf-8"))
        except (ValueError, SyntaxError) as exc:
            problems.append(f"B. cannot parse {manifest.relative_to(ROOT)}: {exc}")
            continue
        for key in ("data", "demo"):
            for rel in spec.get(key, []) or []:
                path = f"addons/{module}/{rel}"
                if path not in tracked:
                    on_disk = (ROOT / path).exists()
                    detail = "present on disk but UNTRACKED" if on_disk else "missing entirely"
                    extra = f"; matched by {why(path)}" if ignored(path) else ""
                    problems.append(
                        f"B. {module} declares '{key}': {rel} - {detail}{extra}")

    if problems:
        print("gitignore guard: FAIL", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        print("\n  A clean clone would not install. Fix the PATTERN in .gitignore;\n"
              "  `git add -f` fixes one file and leaves the next one broken.", file=sys.stderr)
        return 1

    n = sum(1 for _ in (ROOT / "addons").rglob("__manifest__.py"))
    print(f"gitignore guard: OK - {len(MUST_SHIP)} must-ship and "
          f"{len(MUST_BE_IGNORED)} must-ignore patterns correct; "
          f"all declared data/demo files across {n} addon(s) are tracked")
    return 0


if __name__ == "__main__":
    sys.exit(main())
