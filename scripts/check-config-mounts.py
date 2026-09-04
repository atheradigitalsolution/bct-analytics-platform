#!/usr/bin/env python3
"""Assert that every bind-mounted CONFIG FILE matches the repo file it comes from.

WHY THIS EXISTS
---------------
Docker resolves a bind mount of a *single file* to one inode when the container starts. Replace the
file on the host -- as opposed to writing it in place -- and the container keeps reading the old
inode forever. Nothing says so. The service is healthy, the file in the repo is correct, and every
tool that reads the config through the container agrees it is valid, because they are all reading
the same stale bytes.

Measured on 2026-09-04, on the edge proxy:

    caddy reload   -> exit 0, "adapted config to JSON"
    caddy validate -> "Valid configuration"
    live config    -> the previous revision, still serving

Both commands were reading the stale file. A change to the edge -- including a security fix -- had
silently not applied, and there was no signal of any kind.

WHY IT COMPARES CONTENT AND NOT INODES
--------------------------------------
Comparing `stat -c %i` on both sides is the obvious check and it is WRONG. Measured: writing a file
via temp+rename freed inode 1866344 and the replacement was immediately allocated the same number,
so an inode comparison reports "attached" for a file that is not. Inode equality is neither
necessary nor sufficient. Bytes are.

WHAT TRIGGERS THE DETACH, measured rather than assumed:

    python write_text / shell `>`   inode kept   (written in place)
    git checkout / stash / pop      inode kept   (git writes in place)
    sed -i                          inode NEW    <-- confirmed trigger
    cp + mv, and editors that save via temp+rename (vim, VS Code)

WHY IT READS THROUGH `docker exec` AND NOT `docker cp`
-----------------------------------------------------
The first version of this script used `docker cp`, because it works on images with no shell. It
reported success against a mount that was provably detached, and that is worth recording: for a
bind-mounted path, `docker cp` resolves the path on the HOST side. It copies the source file, not
the bytes the container sees, so it compared the repo file against itself and always agreed. It was
a check that could not fail -- the exact defect this script exists to find, reproduced inside the
finder. It was caught only because the gate was required to demonstrate a red run before being
believed.

`docker exec cat` reads through the container's own mount namespace, which is the only view that
answers the question. Every image in this stack has `cat`; one that does not is reported as
UNREADABLE and fails the gate rather than passing quietly.

READ-ONLY BY CONSTRUCTION. It inspects and copies out. It never execs a writing command, never
restarts anything, and never edits a config. If it finds drift it says so and exits non-zero;
deciding to restart a container is a human call, because this same edge serves the public site and
the mail host.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys


#: Derived from this file's own location, never spelled out. An absolute path written into a
#: tracked file describes the machine it was written on, and this repository is mirrored publicly.
REPO_ROOT = str(pathlib.Path(__file__).resolve().parent.parent)


def sh(*args: str) -> str:
    out = subprocess.run(args, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(" ".join(args) + ": " + out.stderr.strip())
    return out.stdout


def containers(name_filter: str) -> list[str]:
    raw = sh("docker", "ps", "--filter", "name=" + name_filter, "--format", "{{.Names}}")
    return [n for n in raw.split() if n]


def file_mounts(container: str) -> list[tuple[str, str]]:
    """Bind mounts whose SOURCE is a regular file on this host."""
    raw = sh("docker", "inspect", container, "--format", "{{json .Mounts}}")
    found = []
    for m in json.loads(raw) or []:
        if m.get("Type") != "bind":
            continue
        src, dst = m.get("Source", ""), m.get("Destination", "")
        if src and dst and os.path.isfile(src):
            found.append((src, dst))
    return found


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_in_container(container: str, path: str) -> bytes:
    """Read the bytes THE CONTAINER SEES, through its own mount namespace.

    NOT `docker cp`: for a bind-mounted path that resolves on the host side and returns the source
    file, which makes the comparison vacuous. See the module docstring -- that mistake shipped in
    the first version of this script and was caught by requiring a red run.
    """
    out = subprocess.run(
        ["docker", "exec", container, "cat", "--", path], capture_output=True
    )
    if out.returncode != 0:
        raise RuntimeError(
            (out.stderr.decode("utf-8", "replace").strip() or "cat failed")[:120]
        )
    return out.stdout


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    # No baked-in default. The project name embeds a tenant slug, and a tenant name written into
    # a tracked file is exactly what `make scan-secret` exists to keep out. It comes from the
    # environment the Makefile already exports, or from --filter.
    ap.add_argument(
        "--filter",
        default=os.environ.get("COMPOSE_PROJECT_NAME", ""),
        help="container name filter (default: $COMPOSE_PROJECT_NAME)",
    )
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if not args.filter:
        print("check-config-mounts: FAIL - no container filter; set COMPOSE_PROJECT_NAME or pass --filter")
        return 1

    names = containers(args.filter)
    if not names:
        print(f"check-config-mounts: FAIL - no running container matches {args.filter!r}")
        return 1

    checked = 0
    drift: list[str] = []
    unreadable: list[str] = []

    for container in sorted(names):
        for src, dst in file_mounts(container):
            checked += 1
            host = open(src, "rb").read()
            try:
                inside = read_in_container(container, dst)
            except RuntimeError as exc:
                unreadable.append(f"{container}:{dst} ({exc})")
                continue
            if digest(host) == digest(inside):
                if not args.quiet:
                    print(f"  ok    {container}  {dst}")
            else:
                rel = os.path.relpath(src, REPO_ROOT)
                drift.append(
                    f"{container}:{dst}\n"
                    f"        repo  {rel}  sha256 {digest(host)[:16]}  {len(host)} bytes\n"
                    f"        live  as the container reads it   sha256 {digest(inside)[:16]}  "
                    f"{len(inside)} bytes"
                )

    # A gate that checks nothing and reports success is the defect this file exists to catch.
    if checked == 0:
        print("check-config-mounts: FAIL - zero file mounts inspected; the check proved nothing")
        return 1

    for item in unreadable:
        print(f"  ????  {item}")
    for item in drift:
        print(f"  DRIFT {item}")

    if drift or unreadable:
        print(
            f"check-config-mounts: FAIL - {len(drift)} of {checked} mounted config file(s) differ "
            f"from the repo, {len(unreadable)} unreadable.\n"
            "  The container is reading bytes that are not in the repo. A bind-mounted FILE is\n"
            "  pinned to one inode at container start, so replacing it on the host does not reach\n"
            "  a running container -- and reload/validate will keep reporting success.\n"
            "  Recreating the container re-resolves the mount. That decision is NOT this script's\n"
            "  to make: the edge serves the public site and the mail host."
        )
        return 1

    print(f"check-config-mounts: OK - {checked} mounted config file(s) match the repo byte for byte")
    return 0


if __name__ == "__main__":
    sys.exit(main())
