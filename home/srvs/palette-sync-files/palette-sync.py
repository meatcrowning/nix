#!/usr/bin/env python3
"""palette-sync.py — keep the wallpaper colour-theme knobs the same on both machines.

The palette is DERIVED from the wallpaper, but how it is derived is a set of
settings, and those settings were machine-local. Measured 2026-08-28 on the one
wallpaper both hosts had prepared (`paper_13.jpg`): identical clusters, and
accent `766cbe` on top against `9fb7c7` on book — hue 247 vs 204, i.e. the
Plasma windows purple on one machine and blue-grey on the other, from the same
picture. The cause was entirely settings: `paletteVariant` normal/muted,
`paletteColorCount` 17/16, and four dropped clusters on top that book did not
have. Nothing was broken; the two machines had simply never been told they were
supposed to agree.

WHAT IS SYNCED: the three keys above, and nothing else in settings.json. They
are the inputs to wal-extract.py that decide WHICH colours come out of an
image — the rest of the Appearance page (lightMode, pureBlackBg, gamma, the
panel's own live state) stays local, deliberately: this is about the two hosts
disagreeing on one picture, not about making the laptop a mirror of the desktop.

HOW, AND WHY NOT ONE SHARED FILE. Transport is docs/, which already syncs both
ways every 5 minutes, so this needs no remote, no auth and no second daemon.
But a single `docs/palette.json` written by both machines is the shape that
wedges: a git conflict in docs/ aborts the whole tick and stops syncing in
either direction, and the boards' recency driver would fall back to a UNION
merge, which for JSON means a file that does not parse. So the boards' answer
applies here too — ONE FILE PER HOST, `docs/palette.<host>.json`, written only
by the machine it is named for and merely read by the other. Two writers, two
files, nothing to merge, ever.

Each file carries {stamp, values}; `stamp` is the settings.json mtime the
values were last read at, which is what orders two concurrent edits. Local
state (`~/.local/state/palette-sync/mirror.json`) records the values this host
last agreed to, so "the user changed something here" and "the other machine
changed something" are distinguishable rather than guessed at.

BOOTSTRAP: [his, 2026-08-28] "implying tops should override airs at first until
the user changes any on either system". With no mirror yet, a host that has not
published adopts the other's file outright; `docs/palette.top.json` is seeded in
the same commit as this script, so book adopts top's palette on its first tick
and top — whose own file already matches its settings — adopts nothing. After
that neither host is privileged and the most recent edit wins, on either
machine.

Applying writes settings.json in place (read-modify-write, atomic rename). The
panel's SettingsStore has watchChanges on, so it reloads and SettingsApply
re-runs wal-set.sh by itself: the desktop repaints with nothing restarted. With
no panel running the mtime bump alone is enough — wal-prepare.sh keys its
palette cache on settings.json being newer than the theme file.
"""

import json
import os
import socket
import sys
import tempfile

HOME = os.path.expanduser("~")
SETTINGS = os.path.join(HOME, ".config/quickshell/settings.json")
DOCS = os.path.join(HOME, "nix/docs")
STATE = os.path.join(HOME, ".local/state/palette-sync")
MIRROR = os.path.join(STATE, "mirror.json")

KEYS = ("paletteVariant", "paletteColorCount", "paletteDropped")


def log(msg):
    print(f"palette-sync: {msg}", file=sys.stderr)


def read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write_json(path, obj):
    """Atomic, and only when the content actually changed.

    Rewriting an unchanged docs file every tick would mint a docs commit every
    tick on a machine nobody is touching — the same rule board-spend-export
    follows.
    """
    old = read_json(path)
    if old == obj:
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".palette-sync.")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise
    return True


def host():
    """The OS hostname (`top` / `book`), never the flake attribute.

    Same rule as boardparse.board_path(): every runtime writer has only the
    hostname, and `air` is a name that exists solely inside flake.nix.
    """
    return socket.gethostname().split(".")[0]


def apply_values(values):
    """Write the synced keys into settings.json, leaving every other key alone."""
    cur = read_json(SETTINGS)
    if cur is None:
        log("settings.json unreadable; not applying")
        return False
    cur.update(values)
    return write_json(SETTINGS, cur)


def main():
    settings = read_json(SETTINGS)
    if settings is None:
        return 0
    if not os.path.isdir(os.path.join(DOCS, ".git")):
        return 0  # docs/ not cloned yet — the transport does not exist

    # A key the panel has never written has no entry; syncing a missing key as
    # null would push that null onto the other host. Take only what is there.
    local = {k: settings[k] for k in KEYS if k in settings}
    if not local:
        return 0
    stamp = int(os.path.getmtime(SETTINGS))

    me = host()
    mine_path = os.path.join(DOCS, f"palette.{me}.json")
    mine = read_json(mine_path)
    mirror = read_json(MIRROR)

    theirs = None
    for name in sorted(os.listdir(DOCS)):
        if not (name.startswith("palette.") and name.endswith(".json")):
            continue
        if name == f"palette.{me}.json":
            continue
        cand = read_json(os.path.join(DOCS, name))
        if cand and isinstance(cand.get("values"), dict):
            if theirs is None or cand.get("stamp", 0) > theirs.get("stamp", 0):
                theirs = cand

    os.makedirs(STATE, exist_ok=True)

    # ---- bootstrap ---------------------------------------------------------
    if mirror is None:
        if mine and mine.get("values") == local:
            mirror = mine
            write_json(MIRROR, mirror)
        elif theirs:
            if apply_values(theirs["values"]):
                log(f"bootstrap: adopted {theirs.get('host')}'s palette")
            write_json(MIRROR, theirs)
            write_json(mine_path, {"host": me, "stamp": theirs["stamp"],
                                   "values": theirs["values"]})
            return 0
        else:
            mirror = {"host": me, "stamp": stamp, "values": local}
            write_json(MIRROR, mirror)
            write_json(mine_path, mirror)
            return 0

    # ---- steady state ------------------------------------------------------
    if local != mirror.get("values"):
        # Changed here. Publishing is all this host does: the other machine
        # decides for itself whether our stamp beats its own.
        rec = {"host": me, "stamp": stamp, "values": local}
        write_json(MIRROR, rec)
        if write_json(mine_path, rec):
            log(f"published {local}")
        return 0

    if theirs and theirs["values"] != local and \
            theirs.get("stamp", 0) > mirror.get("stamp", 0):
        if apply_values(theirs["values"]):
            log(f"applied {theirs.get('host')}'s palette: {theirs['values']}")
        write_json(MIRROR, theirs)
        write_json(mine_path, {"host": me, "stamp": theirs["stamp"],
                               "values": theirs["values"]})
        return 0

    if mine is None or mine.get("values") != local:
        write_json(mine_path, {"host": me, "stamp": mirror.get("stamp", stamp),
                               "values": local})
    return 0


if __name__ == "__main__":
    sys.exit(main())
