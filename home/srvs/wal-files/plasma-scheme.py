#!/usr/bin/env python3
"""Mint the Plasma colour scheme from the wallpaper palette.

In a Plasma session the KDE colour scheme IS the window colour: Oxygen's
blues come out of a `.colors` file, not out of anything wal-set.sh writes.
Until 2026-08-18 wal-set.sh rewrote the kdeglobals `Colors:*` groups directly
from the palette, which is what made a wallpaper change repaint the windows —
and that had to stop (8956ecb), because kdeglobals under Plasma is his whole
global theme (widget style, fonts, icon set), not a private channel.

So this takes the other route: keep the SHAPE of the scheme he picked — the
template, `OxygenDarkFlat.colors`, with its unfocused palette baked in and the
inactive effect off (7e659ba) — and move only its HUE onto the wallpaper's
accent. Structure, contrast and every foreground/background relationship
Oxygen defines survive untouched; the family of blues becomes a family of
whatever colour the wallpaper is.

The maths, per tinted value: RGB -> HLS, hue replaced by the accent's hue,
lightness kept exactly, saturation scaled by `accent_saturation / 0.30`
(capped at 1.0). Keeping L is what preserves the scheme's contrast ratios.
The saturation scale is the degenerate-case guard: a grey wallpaper has no
meaningful hue, and without it Oxygen's own saturation would paint the windows
an arbitrary colour at full strength. 0.30 is a mid-range reference, so a
vivid wallpaper keeps Oxygen's punch and a grey one goes grey.

NOT tinted: `ForegroundNormal` (near-white body text), the three semantic
roles (`ForegroundNegative`/`Neutral`/`Positive` — a red error stays red on a
green wallpaper), and everything outside `[Colors:*]`/`[WM]`.

Applying is gated on the live scheme actually BEING this template's scheme:
the file is always minted, but the push into kdeglobals only happens when
kdeglobals already names it. A host on some other scheme (top's aerotheme
Plasma session) is left alone rather than silently repainted.

WHY NOT `plasma-apply-colorscheme`. Because it refuses: "The requested theme
OxygenDarkFlat is already set as the theme for the current Plasma session" —
it compares the NAME, and the name never moves here, only the file behind it.
So this writes the scheme's own groups into kdeglobals the way that tool would
(`kwriteconfig6`, then one `--notify` so KConfigWatcher pokes running apps),
and stamps `ColorSchemeHash` = sha1 of the .colors file, which is exactly what
Plasma stores it as. Only `Colors:*`, `WM`, `ColorEffects:*` and those two
`General` keys are touched — widget style, icon set and fonts are his.
"""

import argparse
import colorsys
import hashlib
import os
import re
import shutil
import subprocess
import sys

HOME = os.path.expanduser("~")

# Roles whose colour is part of the scheme's hue family. Backgrounds and
# decorations carry the window colour; ForegroundActive/Link/Visited are the
# accent-derived text roles; ForegroundInactive is Oxygen's blue-grey.
TINT_KEYS = {
    "BackgroundNormal", "BackgroundAlternate",
    "DecorationFocus", "DecorationHover",
    "ForegroundActive", "ForegroundLink", "ForegroundVisited",
    "ForegroundInactive",
    "activeBackground", "inactiveBackground",
}
TINT_GROUPS = re.compile(r"^\[(Colors:[A-Za-z]+|WM)\]$")

SAT_REFERENCE = 0.30


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def tint(rgb, hue, sat_scale):
    r, g, b = (c / 255.0 for c in rgb)
    _, l, s = colorsys.rgb_to_hls(r, g, b)
    s = min(1.0, s * sat_scale)
    r, g, b = colorsys.hls_to_rgb(hue, l, s)
    return tuple(int(round(c * 255)) for c in (r, g, b))


def mint(template_text, accent_hex):
    ar, ag, ab = hex_to_rgb(accent_hex)
    hue, _, accent_s = colorsys.rgb_to_hls(ar / 255.0, ag / 255.0, ab / 255.0)
    sat_scale = min(1.0, accent_s / SAT_REFERENCE)

    out, group = [], ""
    for line in template_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            group = stripped
            out.append(line)
            continue
        key, _, value = stripped.partition("=")
        if (TINT_GROUPS.match(group) and key in TINT_KEYS
                and re.fullmatch(r"\d{1,3},\d{1,3},\d{1,3}", value)):
            rgb = tuple(int(c) for c in value.split(","))
            out.append("%s=%d,%d,%d" % ((key,) + tint(rgb, hue, sat_scale)))
        else:
            out.append(line)
    return "\n".join(out) + "\n"


def scheme_name(text):
    m = re.search(r"^ColorScheme=(.+)$", text, re.M)
    return m.group(1).strip() if m else ""


# The groups a colour scheme owns. Everything else in kdeglobals — [KDE]
# widgetStyle, [Icons] Theme, the font roles — belongs to his global theme and
# is never written here (that is the whole point of the 2026-08-18 gate).
PUSH_GROUPS = re.compile(r"^\[(Colors:[A-Za-z]+|WM|ColorEffects:[A-Za-z]+)\]$")


def push_to_kdeglobals(minted, name, digest):
    """Write the scheme's groups into kdeglobals, then notify running apps."""
    kw = shutil.which("kwriteconfig6")
    if not kw:
        print("plasma-scheme: kwriteconfig6 not on PATH, not pushing")
        return
    writes, group = [], ""
    for line in minted.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            group = stripped
            continue
        if not PUSH_GROUPS.match(group) or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        writes.append((group[1:-1], key, value))
    writes.append(("General", "ColorScheme", name))
    # `--` before the value, always: ColorAmount=-0.9 is otherwise parsed as
    # options ("Unknown options: 0, ., 9") and the inactive-effect group —
    # the one 7e659ba switched off — silently fails to write.
    for grp, key, value in writes:
        subprocess.run([kw, "--file", "kdeglobals", "--group", grp,
                        "--key", key, "--", value], check=False)
    # Plasma stores the sha1 of the .colors file here; the KCM reads it to tell
    # "this scheme" from "this scheme, edited". Last write carries --notify so
    # every running KConfigWatcher re-reads the file exactly once.
    subprocess.run([kw, "--notify", "--file", "kdeglobals", "--group", "General",
                    "--key", "ColorSchemeHash", "--", digest], check=False)
    print("plasma-scheme: pushed %d keys into kdeglobals" % (len(writes) + 1))


def live_scheme():
    try:
        with open(os.path.join(HOME, ".config", "kdeglobals")) as fh:
            return scheme_name(fh.read())
    except OSError:
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--accent", required=True, help="bare hex, e.g. d1a8a7")
    ap.add_argument("--template",
                    default=os.path.join(HOME, ".config", "scripts",
                                         "plasma-scheme-template.colors"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-apply", action="store_true")
    args = ap.parse_args()

    try:
        with open(args.template) as fh:
            template = fh.read()
    except OSError as exc:
        print("plasma-scheme: no template (%s)" % exc, file=sys.stderr)
        return 0                      # not a Plasma host — nothing to do

    name = scheme_name(template)
    if not name:
        print("plasma-scheme: template has no [General] ColorScheme=", file=sys.stderr)
        return 1

    out_path = args.out or os.path.join(
        HOME, ".local", "share", "color-schemes", "%s.colors" % name)
    minted = mint(template, args.accent)

    try:
        with open(out_path) as fh:
            unchanged = fh.read() == minted
    except OSError:
        unchanged = False
    if not unchanged:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        # Truncate + write in place, never tmp+mv: the scheme file is watched
        # by inode elsewhere in this desktop (same rule as Theme.qml).
        with open(out_path, "w") as fh:
            fh.write(minted)
    print("plasma-scheme: %s %s from #%s"
          % (name, "unchanged" if unchanged else "minted", args.accent))

    if args.no_apply:
        return 0
    live = live_scheme()
    if live != name:
        print("plasma-scheme: live scheme is %r, not %r — not applying"
              % (live, name))
        return 0
    push_to_kdeglobals(minted, name,
                       hashlib.sha1(minted.encode()).hexdigest())
    return 0


if __name__ == "__main__":
    sys.exit(main())
