#!/usr/bin/env python3
"""tools/nix-eval-diff.py — eval-only drv-closure diff, no builds.

The technique from docs/agents/updater-per-input-diff.md §2 (nix-diff's
algorithm): a derivation's identity lives in its .drv FILENAME
(<hash>-<name>-<version>.drv), and a .drv embeds the paths of everything it
depends on — so `nix-store -qR <drv>` gives the full transitive rebuild set
with no building at all (forcing drvPath only writes .drv files). Diffing two
closures by name/version reproduces the same `pkg: old -> new` list
`nix store diff-closures` gives on the REALIZED closures, without paying for
either build.

Usage: nix-eval-diff.py OLD_DRV NEW_DRV

Prints `pkg: old -> new` rows for every name whose version changed between
the two closures, then a one-line count of same-version drvs that rebuilt for
other reasons (a dependency moved) — those are not a package version change
and are folded into the count rather than listed.
"""
import re
import subprocess
import sys
from collections import defaultdict

HASH_RE = re.compile(r"^[0-9a-z]{32}-(.+)$")
# Nix's own parseDrvName: the name/version split is at the first '-' that is
# immediately followed by a digit.
NAME_VERSION_RE = re.compile(r"^(.*?)-(\d.*)$")

# Drv-closure noise: build-only inputs (patches, tarballs, vendored sources,
# config fragments) that are not "packages" in the sense the row wants.
NOISE_RE = re.compile(
    r"\.(patch|patch\.gz|diff|conf|cfg|tar|tar\.gz|tar\.xz|tar\.bz2|tar\.zst"
    r"|zip|crate|whl|gem|json|txt|list)$"
    r"|(^|[-_])(vendor|cargo-vendor|registry|src|source|sources|deps)([-_]|$)"
)


def closure(drv):
    out = subprocess.run(["nix-store", "-qR", drv],
                          capture_output=True, text=True, check=True)
    return {line for line in out.stdout.splitlines() if line.endswith(".drv")}


def name_version(path):
    base = path.rsplit("/", 1)[-1]
    if base.endswith(".drv"):
        base = base[:-4]
    m = HASH_RE.match(base)
    stripped = m.group(1) if m else base
    m = NAME_VERSION_RE.match(stripped)
    if m:
        return m.group(1), m.group(2)
    return stripped, ""


def group_by_name(paths):
    byname = defaultdict(set)
    for p in paths:
        if NOISE_RE.search(p):
            continue
        name, version = name_version(p)
        byname[name].add(version)
    return byname


def main():
    if len(sys.argv) != 3:
        print("usage: nix-eval-diff.py OLD_DRV NEW_DRV", file=sys.stderr)
        return 2
    old_drv, new_drv = sys.argv[1], sys.argv[2]

    old_paths = closure(old_drv)
    new_paths = closure(new_drv)
    removed = old_paths - new_paths
    added = new_paths - old_paths

    removed_by_name = group_by_name(removed)
    added_by_name = group_by_name(added)

    changed_names = sorted(set(removed_by_name) & set(added_by_name))
    rows = 0
    same_version_rebuilds = 0
    for name in changed_names:
        old_v = ",".join(sorted(removed_by_name[name]))
        new_v = ",".join(sorted(added_by_name[name]))
        if old_v == new_v:
            same_version_rebuilds += len(removed_by_name[name])
            continue
        print("%s: %s -> %s" % (name, old_v, new_v))
        rows += 1

    only_removed = len(set(removed_by_name) - set(added_by_name))
    only_added = len(set(added_by_name) - set(removed_by_name))
    if rows == 0:
        print("no package version changes")
    if same_version_rebuilds or only_removed or only_added:
        print("  (%d dependency-only rebuilds, %d names removed, %d names "
              "added, not shown as version changes)"
              % (same_version_rebuilds, only_removed, only_added))
    return 0


if __name__ == "__main__":
    sys.exit(main())
