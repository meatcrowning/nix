#!/usr/bin/env python3
"""Scan tracked repository content for values kept in private configuration."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys


CONFIG_REL = Path("docs/private-config/settings.json")


def fail(message):
    print(f"privacy-check: {message}", file=sys.stderr)
    return 2


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def required_config(repo):
    path = repo / CONFIG_REL
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("cannot read valid private config") from exc
    if not isinstance(data, dict):
        raise ValueError("private config must be a JSON object")

    def obj(name):
        value = data.get(name)
        if not isinstance(value, dict):
            raise ValueError(f"private config field {name!r} must be an object")
        return value

    location = obj("location")
    for key in ("timeZone", "place", "plasmaPlace"):
        if not isinstance(location.get(key), str) or not location[key]:
            raise ValueError(f"private config location.{key} must be a non-empty string")
    devices = obj("devices")
    if not devices or not all(isinstance(v, str) and v for v in devices.values()):
        raise ValueError("private config devices must contain non-empty strings")
    repositories = obj("repositories")
    for key, value in repositories.items():
        if not isinstance(value, str) or not value:
            raise ValueError(f"private config repositories.{key} must be a non-empty string")
    for key in ("lanCidr", "bluetoothAddress"):
        if not isinstance(data.get(key), str) or not data[key]:
            raise ValueError(f"private config field {key!r} must be a non-empty string")
    if not isinstance(data.get("builderKeys"), list) or not data["builderKeys"]:
        raise ValueError("private config builderKeys must be a non-empty list")
    if not all(isinstance(v, str) and v for v in data["builderKeys"]):
        raise ValueError("private config builderKeys must contain strings")
    audit = obj("audit")
    for key in ("privateEmail", "previousHandle"):
        if not isinstance(audit.get(key), str) or not audit[key]:
            raise ValueError(f"private config audit.{key} must be a non-empty string")
    return data


def add_value(patterns, value, category, *, insensitive=True):
    if not value:
        return
    flags = re.IGNORECASE if insensitive else 0
    patterns.append((re.compile(re.escape(value), flags), category))


def patterns(data):
    result = []
    location = data["location"]
    for key, category in (("timeZone", "timeZone"), ("place", "place"), ("plasmaPlace", "plasmaPlace")):
        add_value(result, location[key], category)

    for value in data["devices"].values():
        add_value(result, value, "devicePath")
        add_value(result, Path(value).name, "deviceBasename")
    for value in data.get("smartDevices", []):
        if isinstance(value, str):
            add_value(result, value, "devicePath")
            add_value(result, Path(value).name, "deviceBasename")

    for value in data["builderKeys"]:
        parts = value.split()
        add_value(result, value, "builderKey", insensitive=False)
        if len(parts) >= 2:
            add_value(result, parts[1], "builderKey", insensitive=False)

    for value in ([data["builderHostKey"]] if isinstance(data.get("builderHostKey"), str) else []):
        parts = value.split()
        add_value(result, value, "builderHostKey", insensitive=False)
        if len(parts) >= 2:
            add_value(result, parts[1], "builderHostKey", insensitive=False)
    for value in data["audit"].get("publicKeys", []):
        if isinstance(value, str):
            parts = value.split()
            add_value(result, value, "recipientKey", insensitive=False)
            if len(parts) >= 2:
                add_value(result, parts[1], "recipientKey", insensitive=False)

    add_value(result, data["lanCidr"], "lanCidr")
    add_value(result, data["bluetoothAddress"], "bluetoothAddress")
    add_value(result, data["audit"]["privateEmail"], "privateEmail")
    add_value(result, data["audit"]["previousHandle"], "previousHandle")
    for key, value in data["repositories"].items():
        if key != "sounds" and re.match(r"https?://", value, re.IGNORECASE):
            add_value(result, value, "repositoryURL", insensitive=False)
    return result


def tracked_files(repo):
    result = git(repo, "ls-files", "-z")
    if result.returncode:
        raise ValueError(result.stderr.strip() or "git ls-files failed")
    return [Path(x) for x in result.stdout.split("\0") if x]


def identities(repo):
    values = []
    for key in ("user.name", "user.email"):
        result = git(repo, "config", "--get", key)
        if result.returncode != 0 or not result.stdout.strip():
            raise ValueError("effective Git user.name and user.email are required")
        values.append(result.stdout.strip())
    return values


def identity_leaks(data, values):
    private = {data["audit"]["privateEmail"].casefold(), data["audit"]["previousHandle"].casefold()}
    return any(value.casefold() in private for value in values)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    try:
        data = required_config(repo)
        git_identity = identities(repo)
        pats = patterns(data)
        files = tracked_files(repo)
    except ValueError as exc:
        return fail(str(exc))

    findings = set()
    lock_path = repo / "flake.lock"
    if lock_path.exists():
        try:
            nodes = json.loads(lock_path.read_text())["nodes"]
            private_node = nodes.get("private-config")
            if private_node is not None and (
                private_node.get("locked", {}).get("path") != "./lib/private-defaults"
                or private_node.get("original", {}).get("path") != "./lib/private-defaults"
            ):
                findings.add(("flake.lock", 1, "privateInput"))
        except (OSError, UnicodeError, ValueError, KeyError, TypeError, AttributeError):
            return fail("cannot validate public flake lock")
    for relative in files:
        path = repo / relative
        try:
            if not path.exists() or path.is_symlink():
                continue
            text = path.read_bytes().decode("utf-8", errors="replace")
        except OSError:
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            for pattern, category in pats:
                if pattern.search(line):
                    findings.add((relative.as_posix(), line_no, category))
    if identity_leaks(data, git_identity):
        findings.add(("git-config", 1, "gitIdentity"))
    for path, line, category in sorted(findings):
        print(f"{path}:{line} {category}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
