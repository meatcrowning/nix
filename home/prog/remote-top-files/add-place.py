#!/usr/bin/env python3
"""Add the `sftp://top/` place to Dolphin's sidebar, once, without disturbing
the rest of user-places.xbel.

Called from home/prog/remote-top.nix on every `home-manager switch` (book only),
so it must be idempotent and must never damage the file: user-places.xbel is
live KDE state holding the user's own places, and a mangled one reads as an
EMPTY sidebar rather than as an error.

Deliberately text insertion, not an XML round-trip — see the note in
remote-top.nix. Anything unexpected is a no-op: a sidebar that is missing one
entry is a nuisance, a clobbered one is lost work.
"""

import os
import sys
import tempfile

PLACES = os.path.expanduser("~/.local/share/user-places.xbel")
HREF = "sftp://top/"
CLOSE = "</xbel>"

# The ID only has to be unique within the file; KDE treats it as an opaque
# string. The literal prefix keeps it clear of the timestamp/N ids KDE mints
# for itself, so it cannot collide with one.
BLOCK = """ <bookmark href="sftp://top/">
  <title>top (/)</title>
  <info>
   <metadata owner="http://freedesktop.org">
    <bookmark:icon name="folder-remote"/>
   </metadata>
   <metadata owner="http://www.kde.org">
    <ID>nix-remote-top/0</ID>
    <isSystemItem>false</isSystemItem>
   </metadata>
  </info>
 </bookmark>
"""


def main() -> int:
    # No file yet means KDE has never written one (no Plasma/Dolphin run on this
    # machine). Creating it from scratch would mean inventing the whole header,
    # and KDE will seed it properly on first run — so leave it and pick the
    # place up on the next switch.
    if not os.path.isfile(PLACES):
        return 0

    try:
        with open(PLACES, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        print(f"remote-top: cannot read {PLACES}: {exc}", file=sys.stderr)
        return 0

    if HREF in text:
        return 0

    # Insert before the LAST </xbel> — rindex, not str.replace, which would hit
    # every occurrence if the file ever grew a second one.
    cut = text.rfind(CLOSE)
    if cut < 0:
        print("remote-top: no </xbel> in places file, leaving it alone", file=sys.stderr)
        return 0

    updated = text[:cut] + BLOCK + text[cut:]

    # Write via a temp file in the same directory + rename, so a crash or a full
    # disk mid-write cannot leave a truncated places file behind.
    directory = os.path.dirname(PLACES)
    handle, tmp = tempfile.mkstemp(dir=directory, prefix=".user-places.xbel.")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            fh.write(updated)
        os.chmod(tmp, 0o644)
        os.replace(tmp, PLACES)
    except OSError as exc:
        print(f"remote-top: cannot write {PLACES}: {exc}", file=sys.stderr)
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return 0

    print("remote-top: added the top (/) place to Dolphin's sidebar")
    return 0


if __name__ == "__main__":
    sys.exit(main())
