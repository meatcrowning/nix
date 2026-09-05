#!/usr/bin/env python3
"""Run the app checks that are safe to execute unattended.

The manifest is deliberately an allowlist. A harness is absent until its
owner has established that it is pure, offscreen, or isolated behind its own
compositor; discovering a new test file must never make it run automatically.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
MANIFEST = HERE / "checks.json"
KINDS = {"pure", "offscreen", "nested"}
HOSTS = {"top", "book"}


def load_checks() -> list[dict]:
    doc = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if doc.get("schema") != 1 or not isinstance(doc.get("checks"), list):
        raise ValueError("unsupported checks manifest")

    seen: set[str] = set()
    for check in doc["checks"]:
        name = check.get("name")
        command = check.get("command")
        hosts = check.get("hosts")
        if not isinstance(name, str) or not name or name in seen:
            raise ValueError(f"invalid or duplicate check name: {name!r}")
        if not (isinstance(command, list) and command
                and all(isinstance(part, str) and part for part in command)):
            raise ValueError(f"{name}: command must be a non-empty string list")
        if check.get("kind") not in KINDS:
            raise ValueError(f"{name}: unsupported safety kind")
        if not (isinstance(hosts, list) and hosts and set(hosts) <= HOSTS):
            raise ValueError(f"{name}: invalid hosts")
        timeout = check.get("timeout")
        if not isinstance(timeout, int) or timeout < 1:
            raise ValueError(f"{name}: timeout must be a positive integer")
        seen.add(name)
    return doc["checks"]


def isolated_env(root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env.pop("WAYLAND_DISPLAY", None)
    env.pop("DISPLAY", None)
    for key, leaf in (
        ("XDG_CACHE_HOME", "cache"),
        ("XDG_CONFIG_HOME", "config"),
        ("XDG_DATA_HOME", "data"),
        ("XDG_RUNTIME_DIR", "runtime"),
        ("XDG_STATE_HOME", "state"),
    ):
        path = root / leaf
        path.mkdir(mode=0o700)
        env[key] = str(path)
    return env


def command_for(check: dict) -> list[str]:
    return [part.replace("{python}", sys.executable)
            for part in check["command"]]


def run(check: dict, verbose: bool) -> tuple[bool, float, str]:
    root = Path(tempfile.mkdtemp(prefix=f"app-check-{check['name']}-"))
    started = time.monotonic()
    try:
        proc = subprocess.run(
            command_for(check), cwd=REPO, env=isolated_env(root),
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=check["timeout"], check=False,
        )
        output = proc.stdout.rstrip()
        ok = proc.returncode == 0
    except subprocess.TimeoutExpired as exc:
        output = ((exc.stdout or "") + (exc.stderr or "")).rstrip()
        output += f"\nTIMEOUT after {check['timeout']}s"
        ok = False
    finally:
        shutil.rmtree(root, ignore_errors=True)
    elapsed = time.monotonic() - started
    if verbose or not ok:
        return ok, elapsed, output
    return ok, elapsed, ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("names", nargs="*", help="checks to run (default: all)")
    parser.add_argument("--host", choices=sorted(HOSTS),
                        default=os.uname().nodename.split(".", 1)[0])
    parser.add_argument("--list", action="store_true", help="list selected checks")
    parser.add_argument("--verbose", action="store_true", help="show passing output")
    args = parser.parse_args()

    try:
        checks = load_checks()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"manifest: {exc}", file=sys.stderr)
        return 2

    known = {check["name"] for check in checks}
    unknown = set(args.names) - known
    if unknown:
        print("unknown check(s): " + ", ".join(sorted(unknown)), file=sys.stderr)
        return 2
    selected = [check for check in checks
                if (not args.names or check["name"] in args.names)
                and args.host in check["hosts"]]

    if args.list:
        for check in selected:
            print(f"{check['name']}\t{check['kind']}\t{','.join(check['hosts'])}")
        return 0
    if not selected:
        print("no checks selected", file=sys.stderr)
        return 2

    failures = 0
    for check in selected:
        ok, elapsed, output = run(check, args.verbose)
        print(f"{'ok' if ok else 'FAIL'}  {check['name']}  {elapsed:.2f}s")
        if output:
            print("\n".join("    " + line for line in output.splitlines()))
        failures += not ok
    print(f"{len(selected) - failures}/{len(selected)} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
