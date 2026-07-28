"""notify — filer's ONE desktop-toast path, and the binary resolver behind it.

filer has no in-window status area: everything it has to say about work that
happens outside the list (a conversion, a failed copy) is said with a desktop
toast, through the same notification server the panel draws. `videoconv.py` grew
that pattern first — a live toast that updates in place via `notify-send
--replace-id`, then a completion or failure toast — and `FileOps` (main.py) now
reports file-operation failures through it too. This module is the one
implementation, so there is exactly one place that knows how a filer toast is
spelled.

`tool()` is here for the same reason it was in videoconv: filer can be launched
from a .desktop entry or the Quickshell runner, whose PATH need not carry the
nix profile dirs, so a bare `notify-send` (or `gio`, or `ffmpeg`) can be "not
found" in a session where it is plainly installed. Resolve against the profile
dirs explicitly rather than trusting PATH.

Wording is DESIGN.md's: lowercase, and ASCII only — the pixel font has no
ellipsis or arrow glyphs, and a line containing one clips (DESIGN.md 2.3).
"""
import os
import shutil
import subprocess

_TOOL_CACHE = {}


def tool(name):
    """Absolute path to a helper binary, or `name` unchanged if nothing was
    found (so the caller still gets a real "could not be started" failure rather
    than a guess). Cached — the answer cannot change within one run."""
    hit = _TOOL_CACHE.get(name)
    if hit is not None:
        return hit
    found = shutil.which(name)
    if not found:
        user = os.environ.get("USER", "")
        for d in (os.path.expanduser("~/.nix-profile/bin"),
                  "/etc/profiles/per-user/%s/bin" % user,
                  "/run/current-system/sw/bin", "/usr/bin"):
            cand = os.path.join(d, name)
            if os.path.exists(cand):
                found = cand
                break
    _TOOL_CACHE[name] = found or name
    return _TOOL_CACHE[name]


def toast(title, body, urgency=None, replace_id=None, value=None, persist=False):
    """Post (or update) one filer toast; returns its id, or None.

    `replace_id` morphs the toast already on screen instead of opening a second
    one. `persist` sends `-t 0` (never expire), which an *ongoing* operation
    must use: the server retires an ordinary toast after a few seconds, and once
    it is gone a later `-r` names an id it no longer has, so every update opens
    a brand-new toast with its own sound. The final toast has nothing left to
    update and keeps the default timeout (DESIGN.md 10.4).
    """
    args = [tool("notify-send"), "-a", "filer", "-p"]
    if persist:
        args += ["-t", "0"]
    if replace_id:
        args += ["-r", str(replace_id)]
    if value is not None:
        args += ["-h", "int:value:%d" % int(value)]
    if urgency:
        args += ["-u", urgency]
    args += [str(title), str(body)]
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return None
    nid = out.stdout.strip()
    return int(nid) if nid.isdigit() else None
