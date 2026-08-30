#!/usr/bin/env python3
"""Generate a working `.env` from `.env.example`.

Contract
--------
`.env.example` is tracked and every secret in it is the literal string
``changeme``. This script copies it to `.env`, replacing exactly those
``changeme`` values with cryptographically random ones and leaving every other
value alone.

Design rules, each of which exists because of a specific failure mode:

* **Idempotent.** Re-running never rotates a secret that already has a real
  value in `.env`. Rotating the Postgres password behind a live volume gives
  you an Odoo that cannot log in to its own database, with no error that says
  so. Use ``--rotate KEY`` to rotate deliberately.
* **Additive.** New keys added to `.env.example` are merged into an existing
  `.env`; keys removed from the example are reported but never silently
  deleted, because a later agent may legitimately have added their own.
* **Backed up.** An existing `.env` is copied to ``.env.bak-<UTC timestamp>``
  before being rewritten. `.gitignore` excludes ``*.bak-*``.
* **0600.** On POSIX the result is owner-only. On Windows this is a no-op and
  the script says so rather than pretending.
* **No jq, no third-party imports.** `jq` is not installed on the target host
  and this must run on a clean machine before anything else exists.

Alphabet
--------
URL-safe base64 minus ``+/=`` padding. Postgres passwords, Redis
``requirepass`` and Odoo's ``admin_passwd`` all travel through shell, YAML,
libpq URIs and ini files; a ``$``, ``'`` or ``:`` in any of them produces a
failure that looks like a wrong password rather than a quoting bug.
"""
from __future__ import annotations

import argparse
import os
import re
import secrets
import shutil
import stat
import string
import sys
from datetime import datetime, timezone
from pathlib import Path

PLACEHOLDER = "changeme"

# Safe across shell, YAML, ini and libpq connection URIs.
ALPHABET = string.ascii_letters + string.digits

# Length per key. Longer where the value is a long-lived credential; shorter
# where a human has to retype it.
DEFAULT_LENGTH = 32
LENGTHS: dict[str, int] = {
    "ODOO_ADMIN_PASSWD": 40,
    "POSTGRES_PASSWORD": 40,
    "ODOO_DB_PASSWORD": 40,
    "WAREHOUSE_READER_PASSWORD": 40,
    "WAREHOUSE_DB_PASSWORD": 40,
    "WAREHOUSE_ADMIN_PASSWORD": 40,
    "WAREHOUSE_RLS_PASSWORD": 40,
    "WAREHOUSE_LOADER_PASSWORD": 40,
    "POSTGRES_EXPORTER_PASSWORD": 32,
    "REDIS_PASSWORD": 40,
    "GRAFANA_ADMIN_PASSWORD": 24,
    "WAREHOUSE_MASK_SALT_DEFAULT": 64,
    "WAREHOUSE_MASK_SALT_BCT": 64,
    "LOGIN_GATEWAY_JWT_KID": 16,
}

# Keys whose value must be identical to another key's. Odoo authenticates to
# Postgres as POSTGRES_USER, so its password is the same secret under a second
# name; generating them independently produces a stack that cannot start and an
# error message that blames the wrong thing.
MIRRORS: dict[str, str] = {
    "ODOO_DB_PASSWORD": "POSTGRES_PASSWORD",
}

LINE_RE = re.compile(r"^\s*(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=(?P<value>.*)$")


def gen(key: str) -> str:
    length = LENGTHS.get(key, DEFAULT_LENGTH)
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def parse_env(path: Path) -> dict[str, str]:
    """Read KEY=VALUE pairs. Comments and blanks ignored; last write wins."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        m = LINE_RE.match(raw)
        if m:
            out[m.group("key")] = m.group("value").strip()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Generate .env from .env.example, replacing every `changeme`."
    )
    ap.add_argument("--example", default=".env.example", type=Path)
    ap.add_argument("--out", default=".env", type=Path)
    ap.add_argument(
        "--rotate",
        action="append",
        default=[],
        metavar="KEY",
        help="Force a new value for KEY even though .env already has one. "
             "Repeatable. Rotating a database password requires the matching "
             "ALTER ROLE; this script does not do that for you.",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Rotate every generated secret. Destructive against a live volume.",
    )
    ap.add_argument("--print-keys", action="store_true",
                    help="List which keys would be generated, then exit.")
    args = ap.parse_args()

    example: Path = args.example
    out: Path = args.out

    if not example.exists():
        print(f"gen-env-secrets: {example} not found (run from the repo root)", file=sys.stderr)
        return 1

    existing = parse_env(out)
    generated: list[str] = []
    kept: list[str] = []
    mirrored: list[str] = []
    values: dict[str, str] = {}

    lines_in = example.read_text(encoding="utf-8").splitlines()

    if args.print_keys:
        for raw in lines_in:
            m = LINE_RE.match(raw)
            if m and m.group("value").strip() == PLACEHOLDER:
                print(m.group("key"))
        return 0

    lines_out: list[str] = []
    for raw in lines_in:
        m = LINE_RE.match(raw)
        if not m:
            lines_out.append(raw)
            continue

        key = m.group("key")
        example_value = m.group("value").strip()

        if example_value != PLACEHOLDER:
            # Not a secret. Prefer whatever .env already says so hand edits to
            # ports and tunables survive a re-run.
            value = existing.get(key, example_value)
            lines_out.append(f"{key}={value}")
            values[key] = value
            continue

        prior = existing.get(key)
        rotate = args.force or key in args.rotate
        if prior and prior != PLACEHOLDER and not rotate:
            value = prior
            kept.append(key)
        else:
            value = gen(key)
            generated.append(key)

        values[key] = value
        lines_out.append(f"{key}={value}")

    # Second pass for mirrors: the source key may appear after the mirror in
    # the file, so this cannot be done inline.
    for mirror_key, source_key in MIRRORS.items():
        if mirror_key in values and source_key in values:
            if values[mirror_key] != values[source_key]:
                values[mirror_key] = values[source_key]
                mirrored.append(f"{mirror_key} := {source_key}")
                for i, line in enumerate(lines_out):
                    mm = LINE_RE.match(line)
                    if mm and mm.group("key") == mirror_key:
                        lines_out[i] = f"{mirror_key}={values[source_key]}"
                        break

    orphans = sorted(set(existing) - set(values))

    if out.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = out.with_name(f"{out.name}.bak-{stamp}")
        shutil.copy2(out, backup)
        print(f"gen-env-secrets: backed up existing {out} -> {backup}")

    text = "\n".join(lines_out) + "\n"
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, out)

    try:
        os.chmod(out, stat.S_IRUSR | stat.S_IWUSR)
        mode_note = "mode 0600"
    except (OSError, NotImplementedError):
        mode_note = "mode unchanged (not supported on this platform)"

    print(f"gen-env-secrets: wrote {out} ({mode_note})")
    if generated:
        print(f"  generated ({len(generated)}): {', '.join(sorted(generated))}")
    if kept:
        print(f"  kept existing ({len(kept)}): {', '.join(sorted(kept))}")
    if mirrored:
        print(f"  mirrored: {', '.join(mirrored)}")
    if orphans:
        print(f"  NOTE keys in {out} that are not in {example} (left untouched): "
              f"{', '.join(orphans)}")

    leftover = [k for k, v in values.items() if v == PLACEHOLDER]
    if leftover:
        print(f"gen-env-secrets: ERROR still `changeme`: {', '.join(leftover)}", file=sys.stderr)
        return 1

    if os.name == "nt":
        print("  NOTE Windows host: file permissions are not enforced. "
              "Keep this repository off shared drives.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
