#!/usr/bin/env python3
"""Set keys in one section of an XDG ini file under ~/.config, in place.

Called from home/prog/mime-defaults.nix on every home-manager activation with
`key=value` pairs on argv. Defaults to `mimeapps.list` / `[Default
Applications]`; `--file` / `--section` / `--only-if-exists` retarget it (the
second caller is `kdeglobals` / `[General]`, for KDE's BrowserApplication).

Why not `xdg.mimeApps` (home-manager's own option): it wants to OWN the whole
file. A real ~/.config/mimeapps.list already exists on both machines with the
user's hand-made associations (kate, mpv/umpv, the claude-cli scheme handler,
[Added Associations] that home-manager would not reproduce) — handing it over
would either refuse with a clobber error or, with force, silently discard them.

Why not `xdg-mime default`: its behaviour forks on the detected desktop
environment, and during activation there is no XDG_CURRENT_DESKTOP, so what it
does depends on the machine and on whether kde-config/kwriteconfig happen to be
on PATH. This does exactly one deterministic thing everywhere.

Contract: only the named keys in the named section are touched. Every other
section (notably [Added Associations]), every other key, comments and ordering
survive verbatim. Rewrites the file only when something actually changed, so
re-running is a no-op — which matters because activation runs on every switch.
"""

import os
import sys
from pathlib import Path


def main(argv):
    filename = "mimeapps.list"
    section = "[Default Applications]"
    only_if_exists = False

    pairs = {}
    rest = list(argv)
    while rest:
        a = rest.pop(0)
        if a == "--file" and rest:
            filename = rest.pop(0)
        elif a == "--section" and rest:
            section = rest.pop(0)
        elif a == "--only-if-exists":
            only_if_exists = True
        elif "=" in a:
            k, v = a.split("=", 1)
            pairs[k.strip()] = v.strip()
        else:
            print(f"mime-defaults: ignoring malformed argument {a!r}", file=sys.stderr)
    if not pairs:
        return 0
    if not (section.startswith("[") and section.endswith("]")):
        section = f"[{section}]"

    cfg = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    path = cfg / filename

    try:
        lines = path.read_text().splitlines()
    except FileNotFoundError:
        if only_if_exists:
            return 0
        lines = []
    except OSError as e:
        print(f"mime-defaults: cannot read {path}: {e}", file=sys.stderr)
        return 1

    original = list(lines)

    # Locate the section and the slice of lines belonging to it.
    start = None
    for i, ln in enumerate(lines):
        if ln.strip() == section:
            start = i
            break
    if start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(section)
        start = len(lines) - 1
    end = len(lines)
    for i in range(start + 1, len(lines)):
        s = lines[i].strip()
        if s.startswith("[") and s.endswith("]"):
            end = i
            break

    remaining = dict(pairs)
    for i in range(start + 1, end):
        s = lines[i].strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key = s.split("=", 1)[0].strip()
        if key in remaining:
            lines[i] = f"{key}={remaining.pop(key)}"

    # Anything not already present is appended at the end of the section, after
    # the last non-blank line so we don't grow a run of blanks on every switch.
    if remaining:
        insert = end
        while insert > start + 1 and not lines[insert - 1].strip():
            insert -= 1
        new = [f"{k}={v}" for k, v in remaining.items()]
        lines[insert:insert] = new

    if lines == original:
        return 0

    text = "\n".join(lines) + "\n"
    tmp = path.with_name(path.name + ".hm-new")
    try:
        tmp.write_text(text)
        os.replace(tmp, path)
    except OSError as e:
        print(f"mime-defaults: cannot write {path}: {e}", file=sys.stderr)
        try:
            tmp.unlink()
        except OSError:
            pass
        return 1
    print(f"mime-defaults: updated {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
