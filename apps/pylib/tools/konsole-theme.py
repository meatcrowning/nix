#!/usr/bin/env python3
"""Konsole's colours, generated from whatever this session calls the theme.

Konsole is a KDE app with its own private palette: a `.colorscheme` file
picked per profile, which follows neither `kdeglobals` nor the panel. So the
one terminal on this box that is not kitty drew Breeze grey on a desktop that
had gone green, and every wallpaper change left it behind.

This writes that file. The source is the same rule every other consumer here
follows (`kdetheme.is_plasma()`, and `pylib/chansource.py` for the 4chan
sheet): the KDE colour scheme in a Plasma session, the panel's
wallpaper-derived `Theme.qml` in the Hyprland one. Both are "the system
theme" — which one that means is a property of the session, not a setting.

    ~/.local/share/konsole/Dynamic.colorscheme    <- written here, ours
    ~/.local/share/konsole/<default>.profile      <- one key patched: ColorScheme

The ANSI mapping is kitty's: foreground and the two "white" slots are TEXT,
the palette's neutral reading pole, while accent stays semantic and the ramp
uses the wallpaper hue with only the four status colours breaking out.

Terminals that are ALREADY OPEN are repainted too, over the xterm
dynamic-colour escapes written to each session's pty — konsole caches a
colour scheme by name for the life of the process, so the file alone only
ever reached the next window. See "the live repaint" below.

    konsole-theme            # write it, patch the default profile, repaint what is open
    konsole-theme --print    # print the scheme, touch nothing
    konsole-theme --source plasma|hypr
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import chansource                                               # noqa: E402
import kdetheme                                                 # noqa: E402

SCHEME_NAME = "Dynamic"

# Terminal background opacity, 0..1. 1 is fully opaque (what this wrote until
# 2026-09-05). Override per run with KONSOLE_OPACITY=0.95 konsole-theme.
# Konsole caches opacity for the life of a window, so unlike the colours — which
# the live repaint below pushes over the pty — a change here only reaches
# terminals opened afterwards.
try:
    OPACITY = float(os.environ.get("KONSOLE_OPACITY", "0.85"))
except ValueError:
    OPACITY = 0.85
OPACITY = min(1.0, max(0.1, OPACITY))
KONSOLE_DIR = Path(os.environ.get("KONSOLE_THEME_DIR")
                   or (Path.home() / ".local" / "share" / "konsole"))
KONSOLERC = Path(os.environ.get("KONSOLE_THEME_RC")
                 or (Path.home() / ".config" / "konsolerc"))


# ---- palette -----------------------------------------------------------------

def palette(source=None):
    """(tokens, provenance) — the twelve `#rrggbb` tokens for this session."""
    plasma = kdetheme.is_plasma() if source is None else (source == "plasma")
    if plasma:
        kde = kdetheme.kde_palette()
        if kde:
            return ({k: kdetheme._hex(v) for k, v in kde.items()},
                    "KDE colour scheme (%s)" % (kdetheme.kde_widget_style() or "unknown style"))
    pal = chansource.panel_palette()
    if not pal:
        raise SystemExit("konsole-theme: no palette — neither a readable "
                         "kdeglobals nor %s" % chansource.PANEL_THEME)
    return (pal, "panel wallpaper palette")


def _rgb(h):
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def _kc(rgb):
    return "%d,%d,%d" % rgb


# ---- the scheme --------------------------------------------------------------

def tones(pal: dict) -> dict:
    """The scheme as plain RGB, one place, so the file and the live repaint
    cannot drift: `bg`/`fg` plus `0`..`7` and their faint/intense tones.

    Konsole wants three tones per slot — the colour, a FAINT one and an
    INTENSE one. Nothing in the wal palette carries those, so they are derived
    the way a terminal expects them to read: faint sunk a third of the way
    into the background, intense lifted a third of the way out of it, rather
    than left equal, which makes `bold` and `dim` indistinguishable."""
    g = lambda k, d="#000000": _rgb(pal.get(k, d))                # noqa: E731
    bg, bgAlt = g("bg"), g("bgAlt", "#000000")
    accent, text, textDim = g("accent", "#ffffff"), g("text", "#ffffff"), g("textDim", "#aaaaaa")
    dim, border = g("dim", "#555555"), g("border", "#333333")
    ok, warn, crit, info = g("ok", "#45b27e"), g("warn", "#a8844e"), g("crit", "#d96262"), g("info", "#475c99")
    white = _mix(bg, (255, 255, 255), 0.98)

    t = {"bg": bg, "bgFaint": bg, "bgIntense": bgAlt,
         "fg": text, "fgFaint": textDim, "fgIntense": _mix(text, white, 0.35)}

    def slot(n, color, faint=None, intense=None):
        t[str(n)] = color
        t["%dFaint" % n] = faint if faint else _mix(color, bg, 0.35)
        t["%dIntense" % n] = intense if intense else _mix(color, white, 0.35)

    slot(0, bg, faint=bg, intense=dim)          # black
    slot(1, crit)
    slot(2, ok)
    slot(3, warn)
    slot(4, info)
    slot(5, textDim, intense=text)              # magenta -> the text tone
    slot(6, accent)
    slot(7, text, faint=border, intense=text)       # white == body text, as in kitty
    return t


def build(pal: dict) -> str:
    """The `.colorscheme` file, for every konsole started from now on."""
    t = tones(pal)

    def slot(n, color, faint, intense):
        out.append("[Color%d]\nColor=%s\n" % (n, _kc(color)))
        out.append("[Color%dFaint]\nColor=%s\n" % (n, _kc(faint)))
        out.append("[Color%dIntense]\nColor=%s\n" % (n, _kc(intense)))

    out = ["# GENERATED by konsole-theme (apps/pylib/tools/konsole-theme.py).\n"
           "# Edits are overwritten on the next theme or wallpaper change.\n\n"]
    for sect, key in (("Background", "bg"), ("BackgroundFaint", "bgFaint"),
                      ("BackgroundIntense", "bgIntense"), ("Foreground", "fg"),
                      ("ForegroundFaint", "fgFaint"), ("ForegroundIntense", "fgIntense")):
        out.append("[%s]\nColor=%s\n" % (sect, _kc(t[key])))
    for n in range(8):
        slot(n, t[str(n)], t["%dFaint" % n], t["%dIntense" % n])
    # Opacity < 1 makes the terminal translucent against whatever is behind the
    # WINDOW (wallpaper, other windows) — KWin composites it; it is not Oxygen's
    # window gradient showing through, which an opaque terminal covers entirely.
    # Blur follows transparency: unblurred text over a busy wallpaper is the
    # thing that makes a translucent terminal unreadable.
    out.append("[General]\nBlur=%s\nColorRandomization=false\n"
               "Description=%s\nOpacity=%s\nWallpaper=\n"
               % ("true" if OPACITY < 1.0 else "false", SCHEME_NAME,
                  ("%g" % OPACITY)))
    return "".join(out)


# ---- the profile -------------------------------------------------------------

def default_profile() -> Path | None:
    """The profile konsolerc calls default, or None when konsole is still on
    its built-in one (which lives in no file and cannot be patched)."""
    try:
        rc = KONSOLERC.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(r"^DefaultProfile=(.+)$", rc, re.M)
    if not m:
        return None
    p = KONSOLE_DIR / m.group(1).strip()
    return p if p.exists() else None


def write_profile(path: Path, pal: dict) -> None:
    """Create the profile we are about to make default. Font matches kitty's
    (docs/DESIGN.md §1) — the pixel font at the same size the rest of the
    desktop uses — because a new profile with no font gets a stock Monospace
    that matches nothing else on screen."""
    path.write_text(
        "[Appearance]\n"
        "AntiAliasFonts=true\n"
        "BoldIntense=true\n"
        "ColorScheme=%s\n"
        "Font=More Perfect DOS VGA,11,-1,5,400,0,0,0,0,0,0,0,0,0,0,1,,0,0\n"
        "\n[General]\nName=%s\nParent=FALLBACK/\n"
        "\n[Scrolling]\nScrollBarPosition=2\n"
        "\n[Terminal Features]\nBlinkingCursorEnabled=true\n" % (SCHEME_NAME, SCHEME_NAME),
        encoding="utf-8")


def patch_profile(path: Path) -> bool:
    """Set ColorScheme in HIS profile and touch nothing else in it — the rest
    of that file (font, scrollback, keys) is his."""
    text = path.read_text(encoding="utf-8", errors="replace")
    new, n = re.subn(r"^ColorScheme=.*$", "ColorScheme=" + SCHEME_NAME, text, count=1, flags=re.M)
    if n == 0:
        if re.search(r"^\[Appearance\]$", text, re.M):
            new = re.sub(r"^\[Appearance\]$", "[Appearance]\nColorScheme=" + SCHEME_NAME,
                         text, count=1, flags=re.M)
        else:
            new = "[Appearance]\nColorScheme=%s\n\n%s" % (SCHEME_NAME, text)
    if new == text:
        return False
    path.write_text(new, encoding="utf-8")
    return True


def set_default(name: str) -> None:
    """konsolerc's [Desktop Entry] DefaultProfile, written by hand rather than
    with kwriteconfig6 so this works with nothing from KDE on PATH."""
    try:
        text = KONSOLERC.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    line = "DefaultProfile=" + name
    if re.search(r"^DefaultProfile=", text, re.M):
        text = re.sub(r"^DefaultProfile=.*$", line, text, count=1, flags=re.M)
    elif re.search(r"^\[Desktop Entry\]$", text, re.M):
        text = re.sub(r"^\[Desktop Entry\]$", "[Desktop Entry]\n" + line, text, count=1, flags=re.M)
    else:
        text = (text.rstrip("\n") + "\n\n" if text else "") + "[Desktop Entry]\n" + line + "\n"
    KONSOLERC.parent.mkdir(parents=True, exist_ok=True)
    KONSOLERC.write_text(text, encoding="utf-8")


# ---- live konsoles -----------------------------------------------------------

def _qdbus() -> str | None:
    for c in ("qdbus", "qdbus6"):
        try:
            subprocess.run([c, "--version"], capture_output=True, timeout=5)
            return c
        except (OSError, subprocess.SubprocessError):
            continue
    return None


def reprofile(qdbus: str | None) -> int:
    """Re-apply each live session's own profile over konsole's D-Bus. Picks up
    everything in the profile EXCEPT the colours, which konsole has already
    cached by scheme name for the life of the process — that half is
    `repaint()` below, and must run after this, because this re-applies the
    stale cached scheme."""
    if qdbus is None:
        return 0
    n = 0
    try:
        services = subprocess.run([qdbus], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return 0
    for svc in services.split():
        if not svc.startswith("org.kde.konsole"):
            continue
        try:
            sessions = subprocess.run([qdbus, svc], capture_output=True, text=True,
                                      timeout=5).stdout
            for obj in sessions.split():
                if not re.fullmatch(r"/Sessions/\d+", obj):
                    continue
                cur = subprocess.run([qdbus, svc, obj, "org.kde.konsole.Session.profile"],
                                     capture_output=True, text=True, timeout=5).stdout.strip()
                subprocess.run([qdbus, svc, obj, "org.kde.konsole.Session.setProfile",
                                cur or SCHEME_NAME],
                               capture_output=True, timeout=5)
                n += 1
        except (OSError, subprocess.SubprocessError):
            continue
    return n


# --- the live repaint ---------------------------------------------------------
#
# Konsole caches a colour scheme by NAME for the life of the process, so
# rewriting `Dynamic.colorscheme` and re-applying the profile repaints
# nothing: a window that was already open kept the old colours until it was
# closed and reopened. What it DOES honour, always and per-session, is the
# xterm dynamic-colour escapes — verified against konsole 26.04.3 by setting
# and reading back: OSC 4;0..15 (the ANSI table), OSC 10 (foreground) and
# OSC 11 (background) all take effect immediately. (OSC 12, the cursor, is
# not implemented — it answers no query — so the cursor stays with the
# profile.)
#
# They are written to each session's pty from OUTSIDE the terminal. Data
# written to the slave device is what the emulator reads as program output,
# so this is the same path a program's own escape would take — it is not
# typed input, nothing reaches the shell's stdin, and a fullscreen TUI in the
# session is undisturbed.

def _pts_of(pid: str) -> str | None:
    """The pts a process is attached to, read straight off its own fds.

    Deliberately not decoded from `tty_nr` in /proc/<pid>/stat: that field is
    `new_encode_dev`, whose minor is split across two bit ranges, and getting
    it slightly wrong yields a plausible-looking `/dev/pts/2048` that simply
    does not exist. The fd link already says the name."""
    for fd in ("0", "1", "2"):
        try:
            dev = os.readlink("/proc/%s/fd/%s" % (pid, fd))
        except OSError:
            continue
        if dev.startswith("/dev/pts/"):
            return dev
    return None


def konsole_ptys() -> list:
    """Every pty owned by a session of a running konsole.

    Walked out of /proc rather than asked over D-Bus: a `processId()` per
    session needs one qdbus round trip each and gives the same answer, and
    this still works with nothing from KDE on PATH."""
    ppid, pids, konsoles = {}, [], set()
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        try:
            stat = (d / "stat").read_text()
            ppid[d.name] = stat[stat.rindex(")") + 2:].split()[1]
            pids.append(d.name)
        except (OSError, ValueError, IndexError):
            continue
        # Identified by the binary, not by `comm`: comm is truncated to 15
        # chars and nixpkgs runs the wrapped `.konsole-wrapped`, so it reads
        # `.konsole-wrappe` — and a substring match on that would also catch
        # `konsole-theme`, i.e. this script's own wrapper, whose children
        # would then be taken for konsole sessions and get the escapes
        # written into whatever terminal launched it.
        try:
            exe = os.path.basename(os.readlink("/proc/%s/exe" % d.name))
        except OSError:
            continue
        if re.fullmatch(r"\.?konsole(-wrapped)?", exe):
            konsoles.add(d.name)
    if not konsoles:
        return []
    out, seen = [], set()
    for p in pids:
        if p in konsoles:                       # konsole's OWN tty is whatever
            continue                            # launched it — often his kitty
        cur, hops, under = ppid.get(p), 0, False
        while cur and hops < 32:                # is a konsole an ancestor?
            if cur in konsoles:
                under = True
                break
            cur, hops = ppid.get(cur), hops + 1
        if not under:
            continue
        dev = _pts_of(p)
        if dev and dev not in seen:
            seen.add(dev)
            out.append(dev)
    return out


def osc(t: dict) -> str:
    """The dynamic-colour escapes for one scheme. Index 0-7 are the base
    tones, 8-15 the intense ones — the same pairing the `.colorscheme` file
    writes, so a live terminal and a fresh one end up identical."""
    seq = ["\033]10;#%02x%02x%02x\007" % t["fg"], "\033]11;#%02x%02x%02x\007" % t["bg"]]
    for n in range(8):
        seq.append("\033]4;%d;#%02x%02x%02x\007" % ((n,) + t[str(n)]))
        seq.append("\033]4;%d;#%02x%02x%02x\007" % ((n + 8,) + t["%dIntense" % n]))
    return "".join(seq)


def repaint(pal: dict) -> int:
    """Recolour every konsole that is already open. Best effort and quiet: a
    pty that has gone away between the scan and the write is not a reason for
    the theme apply to fail."""
    payload = osc(tones(pal)).encode("ascii")
    n = 0
    for dev in konsole_ptys():
        try:
            fd = os.open(dev, os.O_WRONLY | os.O_NONBLOCK | os.O_NOCTTY)
        except OSError:
            continue
        try:
            os.write(fd, payload)
            n += 1
        except OSError:
            pass
        finally:
            os.close(fd)
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", choices=("hypr", "plasma"),
                    help="force the palette source instead of the live session")
    ap.add_argument("--print", dest="dump", action="store_true",
                    help="print the scheme and exit, writing nothing")
    ap.add_argument("--no-default", action="store_true",
                    help="write the scheme but leave the default profile alone")
    a = ap.parse_args()

    pal, prov = palette(a.source)
    scheme = build(pal)
    if a.dump:
        sys.stderr.write("konsole-theme: from %s\n" % prov)
        sys.stdout.write(scheme)
        return 0

    KONSOLE_DIR.mkdir(parents=True, exist_ok=True)
    dest = KONSOLE_DIR / ("%s.colorscheme" % SCHEME_NAME)
    if not dest.exists() or dest.read_text(encoding="utf-8", errors="replace") != scheme:
        dest.write_text(scheme, encoding="utf-8")

    if not a.no_default:
        prof = default_profile()
        if prof is None:
            prof = KONSOLE_DIR / ("%s.profile" % SCHEME_NAME)
            if not prof.exists():
                write_profile(prof, pal)
            set_default(prof.name)
        patch_profile(prof)
        sys.stderr.write("konsole-theme: %s from %s, default profile %s\n"
                         % (dest.name, prov, prof.name))
    else:
        sys.stderr.write("konsole-theme: %s from %s\n" % (dest.name, prov))
    q = _qdbus()
    reprofile(q)                                # font, scrollback — not colours
    live = repaint(pal)                         # colours, on what is already open
    if live:
        sys.stderr.write("konsole-theme: repainted %d live terminal%s\n"
                         % (live, "" if live == 1 else "s"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
