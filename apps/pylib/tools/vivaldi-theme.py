#!/usr/bin/env python3
"""Put this desktop's look on Vivaldi's own interface.

Vivaldi's UI is a Chromium page whose every colour comes from about ninety CSS
custom properties (`pylib/vivaldichrome.py` builds them from the live palette),
so the browser can be re-themed the way a web page is — no patched build, and
no source to build even if one wanted to. Two surfaces, written here:

    --ui      ~/.local/share/vivaldi-ui/custom.css, and the folder each
              INSTALLED profile is pointed at — the flatpak build reads only
              the one he picked through the file-chooser portal (its sandbox
              cannot open the data dir above), so it is discovered and written
              too, or the browser just looks untouched there.
              The colour ladder, Oxygen's relief on the surfaces that have one
              (header, toolbar, tabs, address field, buttons) and the page
              scrollbar sheet, in one file. Read at startup: a change shows at
              the next launch, and the `vivaldi-ui-css` path unit keeps it
              current in the meantime.

    --prefs   the theme entry in ~/.config/vivaldi/Default/Preferences, AND
              the setting that points Vivaldi at the folder above.

              **`~` IS NOT EXPANDED.** `css_ui_mods_directory` is handed to the
              filesystem verbatim, so a path typed into Settings as
              `~/.local/share/vivaldi-ui` silently resolves to nothing and the
              css never loads — no error, no complaint, just a browser that
              looks untouched. That is why this writes the setting itself, as
              an absolute path, rather than telling anyone to type it.
              Vivaldi decides for itself whether its UI is light or dark from
              the THEME's colours — which sets icon polarity and a few things
              no stylesheet reaches — so the theme has to agree with the
              palette even though custom.css does the real work. It also means
              the look survives with CSS modifications switched off.
              **Only while Vivaldi is closed**: it rewrites Preferences from
              memory on exit, so a write underneath a running browser is
              discarded. This refuses rather than lose the edit.

              The load-bearing part is NOT `themes.current`, which on its own
              is ignored at startup — measured on 8.1 against both a generated
              id and a built-in one, with `themes.system` present and absent.
              What the theme engine actually reads is `vivaldi.theme.schedule`
              (`o_s.light` / `o_s.dark`), so this writes the id into both and
              leaves `enabled` at 0. If he has scheduling switched ON, that map
              is his and this refuses to touch it.

    apps/pylib/tools/vivaldi-theme.py             # both (prefs if it can)
    apps/pylib/tools/vivaldi-theme.py --ui
    apps/pylib/tools/vivaldi-theme.py --prefs
    apps/pylib/tools/vivaldi-theme.py --css       # print, write nothing
    apps/pylib/tools/vivaldi-theme.py --source hypr|plasma
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import scrollcss                                                # noqa: E402
import vivaldichrome                                            # noqa: E402

DATA = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
UI_DIR = Path(os.environ.get("VIVALDI_UI_DIR") or (DATA / "vivaldi-ui"))
PREFS = Path(os.environ.get("VIVALDI_PREFS")
             or (Path.home() / ".config" / "vivaldi" / "Default" / "Preferences"))
# The flatpak build keeps its own profile, and its sandbox cannot see
# `~/.local/share/vivaldi-ui` at all — the only seat it reads is the folder he
# picked through the file-chooser portal, which lands in the pref as an
# ephemeral `/run/user/N/doc/<id>/...` path. So both profiles are discovered
# and each is written where IT can read from. (book runs the flatpak; the nix
# vivaldi is installed on both hosts.)
FLATPAK_PREFS = (Path.home() / ".var" / "app" / "com.vivaldi.Vivaldi"
                 / "config" / "vivaldi" / "Default" / "Preferences")
FLATPAK_UI_DIR = Path.home() / ".config" / "vivaldi-mods" / "chrome"
THEME_ID = "desktop-live"


def _doc_origins():
    """Portal document id -> the real path it stands for."""
    try:
        out = subprocess.run(["flatpak", "documents", "--columns=id,origin"],
                             capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return {}
    origins = {}
    for line in out.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 2 and parts[0] and parts[1].startswith("/"):
            origins[parts[0].strip()] = Path(parts[1].strip())
    return origins


def host_path(p: Path) -> Path:
    """A path a sandboxed Vivaldi named, as this side of the sandbox sees it.

    `/run/user/1000/doc/<id>/chrome` is the document portal's view of
    `~/.config/vivaldi-mods/chrome`; writing through the fuse mount works but
    the mount only exists while the portal is up, so resolve to the real path.
    """
    parts = p.parts
    if len(parts) >= 6 and parts[1] == "run" and parts[2] == "user" and parts[4] == "doc":
        origin = _doc_origins().get(parts[5])
        if origin is not None:
            rest = list(parts[6:])
            if rest and rest[0] == origin.name:
                rest = rest[1:]
            return origin.joinpath(*rest)
    return p


def profiles():
    """(Preferences, where THAT profile reads custom.css from), for each install."""
    if os.environ.get("VIVALDI_PREFS"):
        return [(PREFS, UI_DIR)]
    found = []
    for prefs, fallback in ((PREFS, UI_DIR), (FLATPAK_PREFS, FLATPAK_UI_DIR)):
        if prefs.exists():
            found.append((prefs, mods_dir(prefs, fallback)))
    return found or [(PREFS, UI_DIR)]


def mods_dir(prefs: Path, fallback: Path) -> Path:
    """Where this profile is already told to read UI css from, if anywhere."""
    try:
        data = json.loads(prefs.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback
    named = (data.get("vivaldi", {}).get("appearance", {})
             .get("css_ui_mods_directory"))
    if named:
        real = host_path(Path(named))
        if real.is_dir():
            return real
    return fallback

HEADER = """\
/* Vivaldi wearing this desktop's look — %s.
 *
 * Generated by ~/nix/apps/pylib/tools/vivaldi-theme.py — do not hand-edit,
 * re-run it (the vivaldi-ui-css path unit does, on every palette change).
 * Read at Vivaldi STARTUP only: a change here shows at the next launch.
 */
"""


def build_css(source=None, style=None):
    bar, barprov = scrollcss.build(source, style)
    css, prov = vivaldichrome.build(source, extra=bar)
    return css, "%s; scrollbar: %s" % (prov, barprov)


def write_ui(source=None, style=None, directory=UI_DIR):
    css, prov = build_css(source, style)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "custom.css"
    surface = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state")) / "plasma-panel-surface.png"
    if surface.exists():
        shutil.copy2(surface, directory / "oxygen-window.png")
    text = HEADER % prov + css + "\n"
    # Unchanged content is not rewritten: the path unit calls this on every
    # palette write, and a quiet rewrite would only churn the file's mtime.
    try:
        if path.read_text(encoding="utf-8") == text:
            return path, prov, False
    except OSError:
        pass
    path.write_text(text, encoding="utf-8")
    return path, prov, True


def vivaldi_running(prefs=PREFS) -> bool:
    """Is the browser holding THIS profile open?

    Chromium's own answer, not a process name: `SingletonLock` in the user-data
    dir is a symlink to `<host>-<pid>` while an instance owns the profile. A
    bare `pgrep vivaldi-bin` says yes to any Vivaldi on the box — including the
    isolated one `tools/vivaldi-probe.py` runs, which is how this first refused
    to write a profile nothing was using.
    """
    lock = prefs.parent.parent / "SingletonLock"
    try:
        target = os.readlink(lock)
    except OSError:
        return False
    try:
        pid = int(target.rsplit("-", 1)[1])
    except (IndexError, ValueError):
        return True                       # a lock we cannot parse is still a lock
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False                      # stale lock from a crash
    except PermissionError:
        return True


def write_prefs(source=None, prefs=PREFS, force=False, ui_dir=UI_DIR):
    """Install the generated theme and make it current. Returns (path, changed)."""
    if vivaldi_running(prefs) and not force:
        raise SystemExit("vivaldi is running — it rewrites Preferences on exit, so this "
                         "write would be discarded. Close it and re-run (or --force).")
    try:
        data = json.loads(prefs.read_text(encoding="utf-8"))
    except OSError as e:
        raise SystemExit("no Vivaldi Preferences at %s (%s)" % (prefs, e))
    except ValueError as e:
        raise SystemExit("Preferences is not readable JSON (%s)" % e)

    import chansource
    import kdetheme
    plasma = kdetheme.is_plasma() if source is None else (source == "plasma")
    colors = kdetheme.kde_palette() if plasma else None
    pal = ({k: kdetheme._hex(v) for k, v in colors.items()} if colors
           else chansource.panel_palette())
    if not pal:
        raise SystemExit("no palette to build a theme from")

    # The setting that makes custom.css load at all — absolute, because a
    # tilde is not expanded and fails silently.
    appearance = data.setdefault("vivaldi", {}).setdefault("appearance", {})
    was_dir = appearance.get("css_ui_mods_directory")
    # A pref already naming this directory is left VERBATIM: under flatpak it
    # is a document-portal path, and the real path we would write in its place
    # is one the sandbox cannot open.
    if not (was_dir and host_path(Path(was_dir)) == ui_dir.resolve()):
        appearance["css_ui_mods_directory"] = str(ui_dir.resolve())

    entry = vivaldichrome.theme(pal.__getitem__)
    entry["id"] = THEME_ID
    vivaldi = data.setdefault("vivaldi", {})
    themes = vivaldi.setdefault("themes", {})
    user = themes.setdefault("user", [])
    if not isinstance(user, list):
        raise SystemExit("vivaldi.themes.user is not a list — refusing to touch it")
    # Replace ours in place; never disturb a theme he made himself.
    before = json.dumps([u for u in user if isinstance(u, dict) and u.get("id") == THEME_ID],
                        sort_keys=True)
    user = [u for u in user if not (isinstance(u, dict) and u.get("id") == THEME_ID)]
    user.append(entry)
    themes["user"] = user
    was_current = themes.get("current")
    themes["current"] = THEME_ID

    # `themes.current` alone does nothing at startup (measured). The engine
    # resolves the theme through the light/dark SCHEDULE map, so the id has to
    # be in there too — with `enabled` 0, which is "no scheduling", not "no
    # theme". A schedule he has actually switched on is his: leave it alone.
    schedule = vivaldi.setdefault("theme", {}).setdefault("schedule", {})
    if schedule.get("enabled"):
        raise SystemExit("Vivaldi's theme SCHEDULE is switched on — it owns which theme "
                         "applies when, and overwriting it would change that. Turn "
                         "scheduling off in Settings > Themes, or pick %r there yourself."
                         % THEME_ID)
    was_map = dict(schedule.get("o_s") or {})
    # His previous light/dark mapping is unused while scheduling is off, but it
    # is his — keep a copy beside the css so putting it back is a file, not a
    # reconstruction.
    if was_map and was_map != {"dark": THEME_ID, "light": THEME_ID}:
        try:
            UI_DIR.mkdir(parents=True, exist_ok=True)
            (UI_DIR / "previous-theme-schedule.json").write_text(
                json.dumps({"o_s": was_map, "current": was_current}, indent=1),
                encoding="utf-8")
        except OSError:
            pass
    schedule["enabled"] = 0
    schedule["o_s"] = {"dark": THEME_ID, "light": THEME_ID}
    changed = (before != json.dumps([entry], sort_keys=True)
               or was_current != THEME_ID
               or was_map != schedule["o_s"]
               or was_dir != appearance.get("css_ui_mods_directory"))
    if changed:
        prefs.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    return prefs, changed


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", choices=("hypr", "plasma"),
                    help="force the palette source instead of the live session")
    ap.add_argument("--style", choices=scrollcss.STYLES,
                    help="force a desktop scrollbar variant instead of the settings pick")
    ap.add_argument("--ui", action="store_true", help="write only custom.css")
    ap.add_argument("--prefs", action="store_true", help="write only the theme entry")
    ap.add_argument("--css", action="store_true", help="print the css, write nothing")
    ap.add_argument("--force", action="store_true",
                    help="write Preferences even with Vivaldi running (it will be lost)")
    ap.add_argument("--dir", type=Path, default=None,
                    help="write custom.css here instead of each install's own folder")
    a = ap.parse_args()

    if a.css:
        sys.stdout.write(build_css(a.source, a.style)[0])
        return 0
    both = not (a.ui or a.prefs)
    seats = [(PREFS, a.dir)] if a.dir else profiles()
    written = set()
    for prefs, ui_dir in seats:
        if a.ui or both:
            if ui_dir not in written:
                written.add(ui_dir)
                path, prov, changed = write_ui(a.source, a.style, ui_dir)
                print("%s\n  %s — %s"
                      % (path, "rewritten" if changed else "unchanged", prov))
        if a.prefs or both:
            if both and vivaldi_running(prefs):
                print("%s: skipped, vivaldi is running (it would be overwritten "
                      "on exit). Close it and run: vivaldi-theme --prefs" % prefs)
                continue
            path, changed = write_prefs(a.source, prefs=prefs, force=a.force,
                                        ui_dir=ui_dir)
            print("%s\n  theme %r %s, made current, and custom UI modifications"
                  " pointed at %s"
                  % (path, THEME_ID, "written" if changed else "already installed",
                     ui_dir.resolve()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
