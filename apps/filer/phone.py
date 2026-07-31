"""phone — filer's "send to phone" backend (KDE Connect).

The context menu's `send to <device>` entry. Two things live here, and both
exist to keep docs/DESIGN.md 10's rule ("a control that is drawn is a control
that works") true for an action whose target is a phone that may simply not be
in the room:

  * `devices()` — the devices that could receive a file RIGHT NOW: paired AND
    reachable, asked of `kdeconnect-cli` on every call. QML calls it while
    building the menu, not once at startup, because a phone that walked out of
    wifi range must leave the menu rather than stay in it as a row that fails.
    ~10ms measured on `top` (2026-07-30), which is why it can be synchronous.
  * `sendable()` — the subset of a selection that can actually be shared.
    `--share` takes a file; a directory is not a thing KDE Connect can send, so
    a selection's directories are counted out of the label up front instead of
    turning into per-file failure toasts afterwards.

The SEND itself is not here. It is `FileOps.run` like every other shell-out
filer does (`["kdeconnect-cli", "-d", <id>, "--share", <path>]`), wrapped in a
`beginBatch`/`endBatch` by the caller — so a multi-file send reports its outcome
through exactly the machinery a multi-item paste does, counts included, and a
missing binary is "cannot run kdeconnect-cli" rather than silence.

`kdeconnect-cli` is resolved through `notify.tool`, not PATH: filer is launched
from a .desktop entry or the Quickshell runner, whose PATH need not carry the
nix profile dirs. It comes from `kdeconnect-kde` in `home/pkgs/desktop/kde.nix`,
which is ungated, so both `top` and `book` have it — on `book` in
`~/.nix-profile/bin`, which is one of the dirs `tool()` falls back to.
"""
import os
import subprocess

from PySide6.QtCore import QObject, Slot

from notify import tool

# kdeconnect-cli talks to kdeconnectd over the session bus. A daemon that is
# wedged must not wedge the menu with it, so every call is bounded; a timeout
# reads as "no devices", which greys the entry rather than hanging the open.
_TIMEOUT = 3.0


class Phone(QObject):
    """`Phone` context property. Read the module docstring first."""

    @Slot(result="QVariantList")
    def devices(self):
        """Paired AND reachable devices, as `[{id, name}]`, newly enumerated.

        `kdeconnect-cli --list-available --id-name-only` prints one `<id> <name>`
        line per device; names contain spaces ("Galaxy S22 Ultra") and ids do
        not, so the split is on the FIRST space only. Anything that goes wrong —
        no daemon, no binary, a timeout, a line that does not parse — yields an
        empty list, and an empty list is what greys the menu entry out.
        """
        try:
            out = subprocess.run(
                [tool("kdeconnect-cli"), "--list-available", "--id-name-only"],
                capture_output=True, text=True, timeout=_TIMEOUT)
        except (OSError, subprocess.SubprocessError):
            return []
        if out.returncode != 0:
            return []
        devs = []
        for line in out.stdout.splitlines():
            dev_id, sep, name = line.strip().partition(" ")
            if sep and dev_id and name.strip():
                devs.append({"id": dev_id, "name": name.strip()})
        return devs

    @Slot(list, result="QVariantList")
    def sendable(self, paths):
        """The members of `paths` that KDE Connect can actually share: regular
        files (symlinks to them included — `isfile` follows). Order preserved,
        so the files go in the order the user is looking at them."""
        return [p for p in (str(x) for x in paths) if os.path.isfile(p)]
