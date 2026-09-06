#!/usr/bin/env python3
"""Mint the Plasma colour scheme from the wallpaper palette.

In a Plasma session the KDE colour scheme IS the window colour: Oxygen's
blues come out of a `.colors` file, not out of anything wal-set.sh writes.
Until 2026-08-18 wal-set.sh rewrote the kdeglobals `Colors:*` groups directly
from the palette, which is what made a wallpaper change repaint the windows —
and that had to stop (8956ecb), because kdeglobals under Plasma is his whole
global theme (widget style, fonts, icon set), not a private channel.

So this takes the other route: keep the SHAPE of the scheme he picked — either
the light or dark Oxygen template, each with its unfocused palette baked in and
the inactive effect off — and move only its HUE onto the wallpaper's accent.
Structure, contrast and every foreground/background relationship Oxygen defines
survive untouched; the family of blues becomes a family of whatever colour the
wallpaper is.

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

FOUR SCHEMES ARE TEMPLATED: OxygenDarkFlat, OxygenDarkNeutral,
OxygenLightFlat, and
AeroThemePlasma's `Aero` — read out of the system profile, so it exists only
where the aeroshell module put it. The same maths serves each; light schemes'
greys have no saturation to move, so the titlebar, selection and focus
decoration provide the wallpaper colour. See CANDIDATES for why Aero needs its
name forced.

OxygenDarkNeutral is the separately selectable dark live scheme for neutral
surfaces: it applies the wallpaper accent to focus, links, and decorations,
but takes every ordinary background role directly from the wallpaper's darkest
structural colour rather than tinting it from the bright accent. The template's
lightness steps stay intact, so the entire surface ladder fits the wallpaper.

Applying is gated on the live scheme actually BEING one of those: every
candidate is minted, but the push into kdeglobals only happens for the one
kdeglobals already names. A host on some third scheme is left alone rather than
silently repainted.

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
    # The titlebar gradient's light stop. Zero in OxygenDarkFlat (so tinting it
    # is a no-op there), but Aero's is a real colour — leave it and the Win7
    # titlebar keeps a blue top edge under a red wallpaper.
    "activeBlend", "inactiveBlend",
}
TINT_GROUPS = re.compile(r"^\[(Colors:[A-Za-z]+|WM)\]$")
BACKGROUND_GROUPS = {
    "[Colors:Button]",
    "[Colors:Complementary]",
    "[Colors:Tooltip]",
    "[Colors:View]",
    "[Colors:Window]",
}
BACKGROUND_KEYS = {"BackgroundNormal", "BackgroundAlternate"}

SAT_REFERENCE = 0.30
# A structural palette colour supplies the surface HUE, not a second accent.
# Oxygen's BackgroundAlternate includes a saturated blue source value; without
# this cap it would turn into a bright colour on a warm wallpaper instead of a
# quiet dark surface alongside the rest of the theme.
SURFACE_SAT_CAP = 0.22

# The schemes this script knows how to re-mint, as (template path, forced name,
# wallpaper surface hues).
# One is applied per run: whichever one kdeglobals currently NAMES. Anything
# else he picks in System Settings is left alone, exactly as before — the list
# only widens which schemes are ours to follow, never which are ours to
# override.
#
# A forced name is needed for Aero because upstream's file says
# `[General] ColorScheme=BreezeClassic` while Plasma stores and looks the scheme
# up as `Aero` (its filename). Reading the name out of the file would mint
# `BreezeClassic.colors` and then never match the live scheme, i.e. silently
# do nothing forever.
#
# The Aero template is read out of the SYSTEM profile rather than vendored: the
# aeroshell module installs it there (sys/dsk/plasma.nix), so it stays in step
# with the flake pin, and on a host without AeroThemePlasma the path is simply
# absent and the candidate is skipped.
CANDIDATES = [
    (os.path.join(HOME, ".config", "scripts", "plasma-scheme-template.colors"), None, False),
    # A second live scheme built from the same dark template. Its whole surface
    # ladder uses the wallpaper's dark structural hue, not its bright accent.
    (os.path.join(HOME, ".config", "scripts", "plasma-scheme-template.colors"), "OxygenDarkNeutral", True),
    (os.path.join(HOME, ".config", "scripts", "plasma-light-scheme-template.colors"), None, False),
    ("/run/current-system/sw/share/color-schemes/Aero.colors", "Aero", False),
    # book installs AeroThemePlasma from source into Fedora's own prefix, so the
    # same scheme lives here instead. Both paths are listed unconditionally —
    # a missing candidate is skipped, and no host has both.
    ("/usr/share/color-schemes/Aero.colors", "Aero", False),
]


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def tint(rgb, hue, sat_scale):
    r, g, b = (c / 255.0 for c in rgb)
    _, l, s = colorsys.rgb_to_hls(r, g, b)
    s = min(1.0, s * sat_scale)
    r, g, b = colorsys.hls_to_rgb(hue, l, s)
    return tuple(int(round(c * 255)) for c in (r, g, b))


def mint(template_text, accent_hex, force_name=None, background_hex=None,
         surface_hex=None):
    ar, ag, ab = hex_to_rgb(accent_hex)
    hue, _, accent_s = colorsys.rgb_to_hls(ar / 255.0, ag / 255.0, ab / 255.0)
    sat_scale = min(1.0, accent_s / SAT_REFERENCE)
    if surface_hex:
        sr, sg, sb = hex_to_rgb(surface_hex)
        surface_hue, _, surface_s = colorsys.rgb_to_hls(
            sr / 255.0, sg / 255.0, sb / 255.0)
        surface_sat_scale = min(SURFACE_SAT_CAP, surface_s / SAT_REFERENCE)

    out, group = [], ""
    for line in template_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            group = stripped
            out.append(line)
            continue
        key, _, value = stripped.partition("=")
        if (surface_hex and group in BACKGROUND_GROUPS
                and key in BACKGROUND_KEYS
                and re.fullmatch(r"\d{1,3},\d{1,3},\d{1,3}", value)):
            rgb = tuple(int(c) for c in value.split(","))
            out.append("%s=%d,%d,%d" % ((key,) + tint(rgb, surface_hue, surface_sat_scale)))
        elif (surface_hex and group == "[WM]"
              and key in ("activeBackground", "inactiveBackground")
              and re.fullmatch(r"\d{1,3},\d{1,3},\d{1,3}", value)):
            rgb = tuple(int(c) for c in value.split(","))
            out.append("%s=%d,%d,%d" % ((key,) + tint(rgb, surface_hue, surface_sat_scale)))
        elif (background_hex and group in BACKGROUND_GROUPS
                and key in BACKGROUND_KEYS):
            out.append("%s=%s" % (key, ",".join(map(str, hex_to_rgb(background_hex)))))
        elif (background_hex and group == "[WM]"
              and key in ("activeBackground", "inactiveBackground")):
            out.append("%s=%s" % (key, ",".join(map(str, hex_to_rgb(background_hex)))))
        elif (TINT_GROUPS.match(group) and key in TINT_KEYS
                and re.fullmatch(r"\d{1,3},\d{1,3},\d{1,3}", value)):
            rgb = tuple(int(c) for c in value.split(","))
            out.append("%s=%d,%d,%d" % ((key,) + tint(rgb, hue, sat_scale)))
        elif force_name and group == "[General]" and key == "ColorScheme":
            out.append("ColorScheme=%s" % force_name)
        elif force_name == "OxygenDarkNeutral" and group == "[General]" and key == "Name":
            out.append("Name=Oxygen Dark Neutral")
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
    #
    # `--notify` on EVERY write, not just the last one. The signal KConfig emits
    # carries only the groups that invocation changed, and each of these is its
    # own invocation — so notifying on the last write announced `[General]
    # ColorSchemeHash` alone, and every listener that watches a COLOUR group
    # (KColorScheme, the widget style, the Plasma theme) saw a signal about a
    # key it does not care about and never re-read the file. That is why the
    # whole scheme landed in kdeglobals and the Plasma panel and the Qt
    # scrollbars stayed on the old colour until their next restart, while
    # Konsole's terminal area — repainted out of band by konsole-theme.py's
    # escape sequences — changed at once (2026-08-28).
    #
    # It costs nothing on a no-op run: kwriteconfig6 emits the signal only when
    # the value it writes is actually different, so a re-apply of the palette
    # that is already live is still silent.
    for grp, key, value in writes:
        subprocess.run([kw, "--notify", "--file", "kdeglobals", "--group", grp,
                        "--key", key, "--", value], check=False)
    # Plasma stores the sha1 of the .colors file here; the KCM reads it to tell
    # "this scheme" from "this scheme, edited".
    subprocess.run([kw, "--notify", "--file", "kdeglobals", "--group", "General",
                    "--key", "ColorSchemeHash", "--", digest], check=False)

    # ---- and the legacy broadcast, which is the one that actually repaints ---
    #
    # KConfig's ConfigChanged is not enough, measured on book 2026-08-28: with
    # --notify on every colour key the Qt apps' own palettes did follow (Konsole's
    # toolbar and titlebar went purple at once) while the PLASMA PANEL and every
    # Oxygen-drawn SCROLLBAR stayed on the old colour until their process
    # restarted. Both of those repaint on `KGlobalSettings::notifyChange`, the
    # KDE4-era session-bus broadcast that KDE's own colour KCM still emits after
    # it writes kdeglobals — nothing replaced it for these two consumers.
    # Sending it here is what makes a wallpaper change land on the whole desktop
    # rather than most of it. 0 = PaletteChanged, 2 = StyleChanged (Oxygen
    # re-reads its own cached tiles on the second one).
    ds = shutil.which("dbus-send")
    if ds:
        for change in ("0", "2"):
            subprocess.run([ds, "--session", "--type=signal", "/KGlobalSettings",
                            "org.kde.KGlobalSettings.notifyChange",
                            "int32:" + change, "int32:0"], check=False)
    # Oxygen's KWin decoration caches its titlebar palette independently of
    # KGlobalSettings. Plasma and Qt have already repainted from the signals
    # above, but without this supported KWin reconfigure a newly selected
    # dynamic scheme can leave its titlebars on the previously selected file.
    # It is deliberately after every role write: KWin reads the final complete
    # palette, never the short-lived mixture while this loop is still writing.
    busctl = shutil.which("busctl")
    if busctl:
        subprocess.run([busctl, "--user", "call", "org.kde.KWin", "/KWin",
                        "org.kde.KWin", "reconfigure"], check=False)
    print("plasma-scheme: pushed %d keys into kdeglobals%s"
          % (len(writes) + 1, "" if ds else " (no dbus-send: no live repaint)"))


def live_scheme():
    """Which colour scheme kdeglobals is currently running.

    `[General] ColorScheme` is the answer — but when this cannot find it the
    whole script becomes a SILENT no-op: it mints happily, applies nothing, and
    the desktop keeps the colours of the last successful push for ever. That is
    what book was in on 2026-08-28 — every run printed "live scheme is '', not
    one of ours" and the windows stayed on an accent two wallpapers old, through
    logouts and reboots, while everything not driven by the KDE scheme (the
    panel, kitty, the border) had moved. So there are two nets under it.

    So fall back to the HASH. Plasma stores the sha1 of the .colors file it
    applied, and our own push writes it; if it matches a candidate's file on
    disk byte for byte, then that file IS what kdeglobals is running and the
    scheme is ours whatever the name key says. It cannot adopt somebody else's
    scheme by accident — a third-party scheme's hash is the hash of a file we
    are not minting, so it matches nothing here. A successful push writes
    `ColorScheme` back, which repairs the name for everything else that reads it.
    """
    # kreadconfig6 FIRST, because the name is usually not in ~/.config/kdeglobals
    # at all. KConfig cascades: `~/.config/kdedefaults/kdeglobals` (written by
    # plasma-apply-colorscheme and the global-theme KCM) already carries
    # `ColorScheme=OxygenDarkFlat`, and KConfig never writes a key back into the
    # user file when its value equals what it inherits — so our own push writes
    # that key on every run and the user file never gains it. Reading the file
    # by hand therefore answers "no scheme" on a perfectly ordinary Plasma
    # install, which is why book stopped applying (2026-08-28). kreadconfig6
    # reads the whole cascade, the way every KDE reader does.
    kr = shutil.which("kreadconfig6")
    if kr:
        try:
            out = subprocess.run([kr, "--file", "kdeglobals", "--group",
                                  "General", "--key", "ColorScheme"],
                                 capture_output=True, text=True, timeout=10)
            name = out.stdout.strip()
            if name:
                return name
        except (OSError, subprocess.SubprocessError):
            pass

    try:
        with open(os.path.join(HOME, ".config", "kdeglobals")) as fh:
            kg = fh.read()
    except OSError:
        return ""

    name = scheme_name(kg)
    if name:
        return name

    m = re.search(r"^ColorSchemeHash=([0-9a-f]{40})$", kg, re.M)
    if not m:
        return ""
    live_hash = m.group(1)
    for path, forced, _ in CANDIDATES:
        try:
            with open(path) as fh:
                cand = forced or scheme_name(fh.read())
        except OSError:
            continue
        if not cand:
            continue
        out = os.path.join(HOME, ".local", "share", "color-schemes",
                           "%s.colors" % cand)
        try:
            with open(out) as fh:
                body = fh.read()
        except OSError:
            continue
        if hashlib.sha1(body.encode()).hexdigest() == live_hash:
            print("plasma-scheme: kdeglobals has no ColorScheme key; "
                  "identified '%s' by its hash" % cand, file=sys.stderr)
            return cand
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--accent", required=True, help="bare hex, e.g. d1a8a7")
    ap.add_argument("--template", default=None,
                    help="mint only this template (default: every candidate)")
    ap.add_argument("--name", default=None,
                    help="scheme name to force for --template")
    ap.add_argument("--out", default=None)
    ap.add_argument("--background", default=None,
                    help="optional bare hex override for Colors:Window BackgroundNormal")
    ap.add_argument("--surface-color", default=None,
                    help="dark wallpaper structural colour for surface-ladder schemes")
    ap.add_argument("--no-apply", action="store_true")
    args = ap.parse_args()

    candidates = ([(args.template, args.name, bool(args.surface_color))] if args.template
                  else list(CANDIDATES))
    live = live_scheme()
    applied = False

    for path, forced, surface_hue in candidates:
        try:
            with open(path) as fh:
                template = fh.read()
        except OSError as exc:
            # Not a Plasma host, or that theme is not installed here.
            if args.template:
                print("plasma-scheme: no template (%s)" % exc, file=sys.stderr)
            continue

        name = forced or scheme_name(template)
        if not name:
            print("plasma-scheme: %s has no [General] ColorScheme=" % path,
                  file=sys.stderr)
            continue

        out_path = args.out or os.path.join(
            HOME, ".local", "share", "color-schemes", "%s.colors" % name)
        surface = args.surface_color if surface_hue else None
        minted = mint(template, args.accent, force_name=forced,
                      background_hex=args.background, surface_hex=surface)

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

        if args.no_apply or live != name:
            continue
        push_to_kdeglobals(minted, name,
                           hashlib.sha1(minted.encode()).hexdigest())
        applied = True

    if not (args.no_apply or applied):
        print("plasma-scheme: live scheme is %r, not one of ours — not applying"
              % live)
    return 0


if __name__ == "__main__":
    sys.exit(main())
