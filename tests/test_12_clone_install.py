"""Verify from a clone of the branch, never from the working tree.

This is PLAN.md's standing rule, and it exists because of a defect that was invisible to everything
else the project runs: an unanchored ``data/`` pattern in ``.gitignore`` silently excluded three
install-critical files, including the entire 724-row classification seed. Every module's
``__manifest__.py`` declared them, so a fresh clone could not install those modules at all -- while
every test passed, because the tests ran against a working tree where the files exist on disk.

``git status`` shows nothing. The working tree keeps working. CI on a warm checkout is fine. The
bug appears only on a clean clone, which is exactly what "brings up a clean stack from a fresh
clone" promises.

So: clone the branch into a temporary directory and assert, **against the clone**, that every file
any manifest or dbt project declares is actually present. The clone is removed afterwards.
"""

from __future__ import annotations

import ast
import pathlib
import shutil
import subprocess
import tempfile

import pytest

from helpers import env

pytestmark = []

BRANCH = "feat/analytics-platform"


@pytest.fixture(scope="module")
def clone():
    target = pathlib.Path(tempfile.mkdtemp(prefix="bct-clone-"))
    destination = target / "repo"
    result = subprocess.run(
        ["git", "clone", "--branch", BRANCH, "--single-branch",
         str(env.repo_root()), str(destination)],
        capture_output=True, text=True, timeout=600,
    )
    if result.returncode != 0:
        shutil.rmtree(target, ignore_errors=True)
        pytest.fail("git clone of %s failed:\n%s" % (BRANCH, result.stderr))
    yield destination
    shutil.rmtree(target, ignore_errors=True)


def _manifest_data_files(manifest_path: pathlib.Path):
    """Read `data`, `demo` and `assets` file lists out of a manifest without importing it."""
    text = manifest_path.read_text(encoding="utf-8")
    try:
        manifest = ast.literal_eval(text)
    except (ValueError, SyntaxError) as exc:
        pytest.fail("cannot parse %s: %s" % (manifest_path, exc))
    declared = []
    for key in ("data", "demo", "qweb"):
        declared.extend(manifest.get(key) or [])
    for bundle in (manifest.get("assets") or {}).values():
        declared.extend(bundle if isinstance(bundle, list) else [])
    return manifest, declared


def test_the_clone_contains_every_file_the_manifests_declare(clone, evidence):
    addons = clone / "addons"
    assert addons.is_dir(), "the clone has no addons/ directory at all"

    report, missing = [], []
    modules = sorted(p for p in addons.iterdir() if (p / "__manifest__.py").exists())
    assert modules, "no module with a __manifest__.py in the clone"

    for module in modules:
        manifest, declared = _manifest_data_files(module / "__manifest__.py")
        absent = [f for f in declared
                  if not f.startswith(("/", "http")) and not (module / f).exists()]
        report.append("%-26s %2d declared, %d missing" % (module.name, len(declared), len(absent)))
        for f in absent:
            missing.append("%s declares %s, which is NOT in the clone" % (module.name, f))
    evidence.add("modules in the clone of %s" % BRANCH, "\n".join(report))
    assert not missing, "\n".join(missing)


def test_the_clone_contains_the_analytics_and_warehouse_inputs(clone, evidence):
    """Files nothing imports but everything depends on: SQL init, dbt project, alert rules."""
    required = [
        "analytics/warehouse/init/sql/20-schemas-roles.sql",
        "analytics/warehouse/init/sql/30-metadata.sql",
        "analytics/warehouse/init/sql/40-grants.sql",
        "analytics/dbt/dbt_project.yml",
        "analytics/dbt/profiles.yml",
        "observability/prometheus/rules/platform.rules.yml",
        "docker-compose.yml",
        "docker-compose.analytics.yml",
        "Makefile",
        ".env.example",
        "tests/run.sh",
        "tests/prometheus/slot_lag_alerts_test.yml",
    ]
    present, absent = [], []
    for path in required:
        (present if (clone / path).exists() else absent).append(path)
    evidence.add(
        "present in the clone", "\n".join(present) or "(none)"
    )
    evidence.add("MISSING from the clone", "\n".join(absent) or "none")
    assert not absent, (
        "these files exist in the working tree but are not in a fresh clone, so a clean checkout "
        "cannot bring the stack up: %r" % absent
    )


def test_no_secret_material_is_in_the_clone(clone, evidence):
    """The signing key and `.env` must be absent from a clone; `.env.example` must be present."""
    must_be_absent = [
        ".env",
        "login-gateway/secrets/jwt-private.pem",
        "login-gateway/secrets/jwt-next-private.pem",
    ]
    leaked = [p for p in must_be_absent if (clone / p).exists()]
    evidence.add(
        "secret-bearing paths in the clone",
        "\n".join("%s  %s" % ("PRESENT" if (clone / p).exists() else "absent", p)
                  for p in must_be_absent),
    )
    assert not leaked, "committed secret material: %r" % leaked
    assert (clone / ".env.example").exists(), ".env.example is missing from the clone"


def test_dbt_models_referenced_by_the_project_are_in_the_clone(clone, evidence):
    """A model directory that exists locally but is gitignored would fail `dbt build` on a clone."""
    models = clone / "analytics" / "dbt" / "models"
    local_models = env.repo_root() / "analytics" / "dbt" / "models"
    if not local_models.exists():
        pytest.skip("analytics/dbt/models does not exist in the working tree either (NOT RUN)")
    local = sorted(p.relative_to(local_models).as_posix()
                   for p in local_models.rglob("*") if p.is_file())
    cloned = sorted(p.relative_to(models).as_posix()
                    for p in models.rglob("*") if p.is_file()) if models.exists() else []
    absent = [f for f in local if f not in cloned]
    evidence.add(
        "dbt model files: working tree vs clone",
        "working tree %d files\nclone        %d files\nmissing from clone: %s"
        % (len(local), len(cloned), absent or "none"),
    )
    assert not absent, (
        "%d dbt file(s) exist locally but are not tracked, so `dbt build` on a fresh clone would "
        "not see them: %r" % (len(absent), absent[:20])
    )
